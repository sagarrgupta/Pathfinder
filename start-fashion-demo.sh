#!/bin/bash
# Reuse the current frontend and model servers with isolated demo storage.
# Run the student backend and this backend one at a time.
set -euo pipefail

DEMO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEMO_PYTHON="$DEMO_ROOT/venv/bin/python"
DEMO_STORAGE="$DEMO_ROOT/data/fashion-demo"
cd "$DEMO_ROOT"

if [ ! -x "$DEMO_PYTHON" ]; then
    echo "The project Python environment is missing: $DEMO_PYTHON"
    exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is required. Start Docker Desktop before running this launcher."
    exit 1
fi
if ! command -v lsof >/dev/null 2>&1; then
    echo "lsof is required to check that the backend port is available."
    exit 1
fi
if lsof -tiTCP:8001 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port 8001 is in use. Stop the existing backend before starting the fashion demo."
    echo "The frontend can keep running on port 3000."
    exit 1
fi

# Environment overrides take precedence over .env, which remains untouched.
# Pin every storage target rather than inheriting student settings from a shell.
export NEO4J_URI="bolt://localhost:7688"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="${FASHION_NEO4J_PASSWORD:-pathfinder-fashion-demo}"
export SQLITE_DB_PATH="$DEMO_STORAGE/pathfinder.db"
export REPLAY_ARTIFACT_DIR="$DEMO_STORAGE/replays"
export LLM_DEBUG_LOG_PATH="$DEMO_STORAGE/llm_debug.log"
export HOST="127.0.0.1"
export PORT="8001"
mkdir -p "$REPLAY_ARTIFACT_DIR"

docker compose -p pathfinder-fashion-demo \
    -f "$DEMO_ROOT/docker/docker-compose.fashion.yml" up -d

# Wait for the demo database only. This never connects to the student endpoint.
"$DEMO_PYTHON" - <<'PY'
import asyncio
import os

from neo4j import AsyncGraphDatabase


async def wait_for_database():
    async with AsyncGraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
        connection_timeout=2,
        connection_acquisition_timeout=2,
    ) as driver:
        for attempt in range(30):
            try:
                await asyncio.wait_for(driver.verify_connectivity(), timeout=2)
                return
            except Exception:
                if attempt == 29:
                    raise SystemExit(
                        "The fashion database is unavailable. Check Docker Desktop "
                        "and the demo database credentials."
                    ) from None
                await asyncio.sleep(1)


asyncio.run(wait_for_database())
PY

echo "Starting the fashion backend on http://localhost:8001"
echo "Demo chat and replay files: $DEMO_STORAGE"
echo "Demo Neo4j browser: http://localhost:7475"
echo "Reuse the frontend on http://localhost:3000 in a private browser window."
echo "If needed, start the frontend in another terminal: cd frontend && npm run dev"
echo "Keep your configured model server and Ollama running."
echo "Use this launcher for the fashion demo; start.sh targets the student storage."
exec "$DEMO_PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 8001
