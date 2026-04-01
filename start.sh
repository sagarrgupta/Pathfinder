#!/bin/bash
# Pathfinder - Start Script
# Starts Neo4j (Docker) and the FastAPI backend

set -e

echo "=== Pathfinder Startup ==="

# 1. Start Neo4j
echo "[1/3] Starting Neo4j..."
cd docker
docker compose up -d
cd ..

echo "[2/3] Waiting for Neo4j to be ready..."
for i in {1..30}; do
    if curl -s http://localhost:7474 > /dev/null 2>&1; then
        echo "  Neo4j is ready!"
        break
    fi
    echo "  Waiting... ($i/30)"
    sleep 2
done

# 3. Create data directory for SQLite
mkdir -p data

# 4. Start FastAPI
echo "[3/3] Starting Pathfinder API server..."
if [ -x "venv/bin/uvicorn" ]; then
    VENV_UVICORN="venv/bin/uvicorn"
elif [ -x ".venv/bin/uvicorn" ]; then
    VENV_UVICORN=".venv/bin/uvicorn"
else
    echo "No project virtualenv uvicorn found in venv/ or .venv/"
    exit 1
fi

"$VENV_UVICORN" app.main:app --host 0.0.0.0 --port 8001 --reload
