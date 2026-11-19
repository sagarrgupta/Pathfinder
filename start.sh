#!/bin/bash
# Pathfinder local stack startup script.
# Starts local dependencies, the configured model provider, backend, and frontend.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$ROOT_DIR/docker"
VENV_DIR="$ROOT_DIR/venv"
FRONTEND_DIR="$ROOT_DIR/frontend"
LOG_DIR="$ROOT_DIR/logs"
REQ_FILE="$ROOT_DIR/requirements.txt"
REQ_STAMP="$VENV_DIR/.requirements_installed"
EMBEDDING_MODEL="${EMBEDDING_MODEL:-mxbai-embed-large}"

mkdir -p "$LOG_DIR"

require_command() {
    local cmd="$1"
    if ! command -v "$cmd" > /dev/null 2>&1; then
        echo "Required command not found: $cmd"
        exit 1
    fi
}

select_lmstudio_model() {
    local requested_model="${1:-}"
    python3 -c '
import json
import sys
import urllib.request

requested = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
with urllib.request.urlopen("http://localhost:1234/v1/models", timeout=10) as resp:
    payload = json.load(resp)

models = payload.get("data", [])
ids = [str(item.get("id", "")).strip() for item in models if str(item.get("id", "")).strip()]

if requested and requested in ids:
    print(requested)
elif ids:
    print(ids[0])
' "$requested_model"
}

kill_port_listener() {
    local port="$1"
    local name="$2"
    local pid
    pid="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
    if [ -n "$pid" ]; then
        echo "  Killing existing $name process on port $port (pid: $pid)"
        kill -9 $pid 2>/dev/null || true
        sleep 1
    fi
}

wait_for_http() {
    local url="$1"
    local name="$2"
    local attempts="${3:-30}"
    for i in $(seq 1 "$attempts"); do
        if curl -s "$url" > /dev/null 2>&1; then
            echo "  $name is ready."
            return 0
        fi
        echo "  Waiting for $name... ($i/$attempts)"
        sleep 2
    done
    return 1
}

echo "=== Pathfinder Startup ==="

require_command docker
require_command curl
require_command lsof
require_command ollama
require_command npm
require_command python3

if [ ! -d "$DOCKER_DIR" ]; then
    echo "Docker directory not found: $DOCKER_DIR"
    exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
    echo "Virtual environment not found at $VENV_DIR"
    echo "Create it first with: python3 -m venv venv"
    exit 1
fi

if [ ! -d "$FRONTEND_DIR" ]; then
    echo "Frontend directory not found: $FRONTEND_DIR"
    exit 1
fi

cd "$ROOT_DIR"
echo "[1/6] Activating Python virtual environment..."
source "$VENV_DIR/bin/activate"
mkdir -p "$ROOT_DIR/data"

if [ ! -f "$REQ_STAMP" ] || [ "$REQ_FILE" -nt "$REQ_STAMP" ]; then
    echo "  Installing Python dependencies..."
    python -m pip install -r "$REQ_FILE"
    touch "$REQ_STAMP"
else
    echo "  Python dependencies already look up to date."
fi

LLM_PROVIDER="$(python -c 'from app.config.settings import settings; print(settings.llm_provider)')"

echo "[2/6] Restarting Neo4j..."
kill_port_listener 7474 "Neo4j HTTP"
kill_port_listener 7687 "Neo4j Bolt"
(
    cd "$DOCKER_DIR"
    docker compose up -d
)
if ! wait_for_http "http://localhost:7474" "Neo4j" 30; then
    echo "Neo4j did not become ready on http://localhost:7474"
    exit 1
fi

echo "[3/6] Restarting Ollama..."
kill_port_listener 11434 "Ollama"
nohup ollama serve > "$LOG_DIR/ollama.log" 2>&1 &
OLLAMA_PID=$!
if ! wait_for_http "http://localhost:11434/api/tags" "Ollama" 30; then
    echo "Ollama did not become ready on http://localhost:11434"
    exit 1
fi
if ! ollama list | grep -q "$EMBEDDING_MODEL"; then
    echo "  Pulling Ollama embedding model: $EMBEDDING_MODEL"
    ollama pull "$EMBEDDING_MODEL"
fi

echo "[4/6] Preparing model provider: $LLM_PROVIDER..."
if [ "$LLM_PROVIDER" = "lmstudio" ]; then
    kill_port_listener 1234 "LM Studio API"
    if command -v open > /dev/null 2>&1; then
        open -a "LM Studio" || true
    else
        echo "  'open' command is unavailable. Start LM Studio manually."
    fi
    if ! wait_for_http "http://localhost:1234/v1/models" "LM Studio API" 45; then
        echo "LM Studio API did not become ready on http://localhost:1234/v1/models"
        echo "Open LM Studio, load your model, and enable the local server."
        exit 1
    fi

    SELECTED_LLM_MODEL="$(select_lmstudio_model "${LLM_MODEL:-}")"
    if [ -z "$SELECTED_LLM_MODEL" ]; then
        echo "LM Studio is running, but no served models were returned from /v1/models."
        echo "Load any model in LM Studio and start the local server."
        exit 1
    fi
    echo "  LM Studio available model: $SELECTED_LLM_MODEL"
else
    echo "  Using the saved NVIDIA configuration."
fi

echo "[5/6] Restarting backend..."
kill_port_listener 8001 "Pathfinder backend"
nohup uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
if ! wait_for_http "http://localhost:8001/api/v1/health" "Pathfinder backend" 45; then
    echo "Pathfinder backend did not become ready on http://localhost:8001/api/v1/health"
    exit 1
fi

echo "[6/6] Restarting frontend..."
kill_port_listener 3000 "Vite frontend"
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    echo "  Installing frontend dependencies..."
    (
        cd "$FRONTEND_DIR"
        npm install
    )
fi
cd "$FRONTEND_DIR"
nohup npm run dev -- --host 0.0.0.0 --port 3000 > "$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
cd "$ROOT_DIR"
if ! wait_for_http "http://localhost:3000" "Frontend" 45; then
    echo "Frontend did not become ready on http://localhost:3000"
    exit 1
fi

echo
echo "Pathfinder is up."
echo "  Neo4j:    http://localhost:7474"
echo "  Backend:  http://localhost:8001"
echo "  Frontend: http://localhost:3000"
echo
echo "Logs:"
echo "  Ollama:   $LOG_DIR/ollama.log"
echo "  Backend:  $LOG_DIR/backend.log"
echo "  Frontend: $LOG_DIR/frontend.log"
echo
echo "PIDs:"
echo "  Ollama:   $OLLAMA_PID"
echo "  Backend:  $BACKEND_PID"
echo "  Frontend: $FRONTEND_PID"
