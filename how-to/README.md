# Build Your Own Local AI Agent

These how-tos explain how to build **your own** local, privacy-preserving AI agent. Pathfinder is used only as an example; you can adapt the patterns to any domain (research assistant, coding tutor, health Q&A, etc.).

---

## What You Will Build

| Component | Purpose |
|-----------|---------|
| **Agent backend** | HTTP API (e.g. `/chat`) that coordinates everything |
| **Graph + vector memory** | Neo4j for users, documents, skills, and semantic search |
| **Local LLMs** | LM Studio for reasoning and (optionally) vision |
| **Embeddings** | Ollama for document and query embeddings |
| **Orchestration** | LangChain, LangGraph, Langflow for agent logic |
| **Optional** | Web search, MCP tools, custom UI/client |

---

## Prerequisites

Before starting, ensure you have:

- **Python 3.10+** and `pip`
- **Node.js** (if using a web UI)
- **Docker** (for Neo4j)
- **~16 GB RAM** (for local models; more for larger models)
- **~20 GB disk** (for models and data)

---

## Quick Links: All How-Tos (Recommended to follow as per this list)

| Guide | Topic |
|-------|--------|
| [docker-for-local-services.md](docker-for-local-services.md) | Run Neo4j and other services in Docker |
| [neo4j-and-graph-memory.md](neo4j-and-graph-memory.md) | Graph schema, vector index, Cypher patterns |
| [ollama-embeddings.md](ollama-embeddings.md) | Local embeddings for semantic search |
| [lmstudio-local-llms.md](lmstudio-local-llms.md) | Local reasoning/vision models (OpenAI-compatible) |
| [agent-orchestration-tools.md](agent-orchestration-tools.md) | LangChain, LangGraph, Langflow, SqliteSaver |
| [backend-service-and-agent-graph.md](backend-service-and-agent-graph.md) | `.env` creation, API design, wiring services |
| [web-search-and-tools.md](web-search-and-tools.md) | Web search and external tools (optional) |
| [mcp-exposing-your-tools.md](mcp-exposing-your-tools.md) | Expose tools via MCP (optional) |
| [client-and-ui-options.md](client-and-ui-options.md) | Web UI, CLI, or other clients (optional) |

Each guide follows the same structure: **How to install** → **Why use it** → **How to set up and use** → **Common pitfalls** → **Official docs**.

---

## Recommended Reading Order

1. **[docker-for-local-services.md](docker-for-local-services.md)** – Run Neo4j in Docker
2. **[neo4j-and-graph-memory.md](neo4j-and-graph-memory.md)** – Set up graph and vector memory
3. **[ollama-embeddings.md](ollama-embeddings.md)** – Install and use Ollama for embeddings
4. **[lmstudio-local-llms.md](lmstudio-local-llms.md)** – Run local LLMs via LM Studio
5. **[agent-orchestration-tools.md](agent-orchestration-tools.md)** – LangChain, LangGraph, Langflow
6. **[backend-service-and-agent-graph.md](backend-service-and-agent-graph.md)** – Build the API and agent graph
7. Optional: **[web-search-and-tools.md](web-search-and-tools.md)**, **[mcp-exposing-your-tools.md](mcp-exposing-your-tools.md)**, **[client-and-ui-options.md](client-and-ui-options.md)**

**Minimal path:** Neo4j + Ollama + LM Studio + small backend. Add the rest as needed.

---

## Minimal End-to-End Checklist

After going through the guides, your typical flow:

### 1. Start Infrastructure

```bash
cd docker  # or wherever docker-compose.yml lives
docker compose up -d
curl -s http://localhost:7474  # verify Neo4j
```

### 2. Start Local Models

```bash
ollama serve
ollama pull mxbai-embed-large
# In LM Studio: load model, enable server at http://localhost:1234/v1
curl -s http://localhost:1234/v1/models  # verify
```

### 3. Start Backend

```bash
cp .env.example .env   # edit .env with your values
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
curl -s http://localhost:8001/api/v1/health  # verify
```

### 4. (Optional) Start Client

```bash
cd frontend && npm install && npm run dev
# Or use a CLI, notebook, or MCP client
```

---

## For Thesis / Demo

Use these guides to tell the story:

1. **Architecture** (this file) – Local agent, graph memory, local models
2. **Building blocks** – Docker, Neo4j, Ollama, LM Studio
3. **Orchestration** – LangChain/LangGraph/Langflow
4. **Agent design** – Backend, graph, roles, tools
5. **Extensions** – Web search, MCP, client options

Focus on **how someone else can build their own agent** using the same ideas and tools.
