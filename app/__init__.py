"""Pathfinder application package.

This is the top of the server-side code. The package is organized into
a few focused layers that each own one concern:

- `config/`   : environment-driven settings (single source of truth).
- `core/`     : the LangGraph runtime — shared state, workflow wiring,
                checkpointer, system prompts.
- `nodes/`    : one file per step in a chat turn (input guard,
                orchestrator, specialist runner, responder, ...).
- `tools/`    : tool specs the LLM can call (graph / vector / web /
                utility), plus the MCP server that exposes them.
- `adapters/` : thin wrappers around external services (Neo4j, Ollama
                embeddings, LM Studio chat, PDF extraction, web search).
- `services/` : side-effect helpers that don't belong to a single node
                (e.g. replay artifact storage).
- `api/`      : FastAPI routes — the HTTP entry point to the workflow.
- `schemas/`  : Pydantic request/response models shared by the API.
- `utils/`    : cross-cutting helpers used by multiple nodes.
- `main.py`   : FastAPI app factory and process-level startup/shutdown.

The whole thing is `import app.main:app` for uvicorn.
"""
