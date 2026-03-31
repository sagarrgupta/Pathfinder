# Backend Service and Agent Graph

This guide explains how to build the backend that wires together Neo4j, Ollama, LM Studio, and your LangGraph agent—and how to expose an API that accepts parameters and forwards them to your agent.

---

## 1. How to Install (Minimal Backend)

**Prerequisites:** Python 3.10+, virtual environment

```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# Core web framework
pip install fastapi "uvicorn[standard]"

# Configuration
pip install pydantic pydantic-settings

# Agent stack
pip install langchain langchain-community langchain-openai langgraph langgraph-checkpoint-sqlite aiosqlite

# Database and services
pip install neo4j
```

Create a project structure (example):

```
your-agent/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI app
│   ├── config/
│   │   └── settings.py  # Pydantic settings
│   ├── api/
│   │   └── routes.py    # API endpoints
│   └── core/
│       ├── graph.py     # LangGraph assembly
│       └── memory.py    # SqliteSaver checkpointer
├── .env                 # Your config (create from .env.example)
├── .env.example         # Template
└── requirements.txt
```

---

## 2. How to Create the .env File

### 2.1 Create the File

The `.env` file holds secrets and config. **Never commit it to git.** Use `.env.example` as a template.

**Step 1 – Copy the template:**

```bash
# From your project root
cp .env.example .env
```

**Step 2 – Place `.env` in the project root** (same directory as `main.py` or where you run `uvicorn` from).

**Step 3 – Edit `.env`** with your values. Example content:

```env
# Neo4j (required for graph + vector memory)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-actual-password

# LM Studio (local LLM)
LLM_BASE_URL=http://localhost:1234/v1
LLM_MODEL=openai/gpt-oss-20b

# Ollama (embeddings)
OLLAMA_URL=http://localhost:11434
EMBEDDING_MODEL=mxbai-embed-large

# SQLite (conversation memory – path to the DB file)
SQLITE_DB_PATH=data/agent.db

# Optional: Web search API keys
TAVILY_API_KEY=
BRAVE_API_KEY=
```

**Step 4 – Ensure `.env` is in `.gitignore`:**

```
.env
*.db
data/
```

### 2.2 Loading .env in Code

Use **Pydantic Settings** so your app reads `.env` automatically:

```python
# app/config/settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = ""
    LLM_BASE_URL: str = "http://localhost:1234/v1"
    LLM_MODEL: str = "openai/gpt-oss-20b"
    OLLAMA_URL: str = "http://localhost:11434"
    SQLITE_DB_PATH: str = "data/agent.db"

settings = Settings()
```

Import `settings` anywhere you need config: `from app.config.settings import settings`.

---

## 3. How to Write an API That Accepts Parameters and Passes to Your Agent

### 3.1 API Design Options

| Approach | When to Use | Example |
|---------|-------------|---------|
| **Form data** | File uploads + simple fields (chat with attachments) | `query`, `session_id`, `files` |
| **JSON body** | Structured payloads without files | `{"query": "...", "session_id": "..."}` |

For a chat endpoint that may include file uploads, use **Form** parameters. For profile updates or settings, use **JSON**.

### 3.2 Example: Chat API with Form Parameters

```python
# app/api/routes.py
import uuid
from fastapi import APIRouter, Form, File, UploadFile, HTTPException
from typing import Optional

router = APIRouter()

@router.post("/chat")
async def chat(
    query: str = Form(..., description="User message"),
    session_id: Optional[str] = Form(None, description="Conversation ID; generated if omitted"),
    files: list[UploadFile] = File(default=[]),
):
    """Accept user query and optional files, pass to agent graph."""
    if not session_id:
        session_id = "sess_" + str(uuid.uuid4())[:8]  # or use your ID generator

    # 1. Parse uploaded files into a format your graph expects
    file_data = []
    for f in files:
        content = await f.read()
        file_data.append({"filename": f.filename, "content": content})

    # 2. Build initial state for the graph
    initial_state = {
        "messages": [("human", query)],
        "query": query,
        "files": file_data,
        "session_id": session_id,
    }

    # 3. Config for LangGraph checkpointer (uses session_id as thread_id)
    config = {"configurable": {"thread_id": session_id}, "recursion_limit": 15}

    # 4. Get compiled graph (from your graph module) and invoke
    graph = await get_compiled_graph()  # Your function that returns the compiled graph
    result = await graph.ainvoke(initial_state, config=config)

    # 5. Extract answer and return to client
    return {"answer": result.get("final_answer", ""), "session_id": session_id}
```

### 3.3 Example: Chat API with JSON Body (No Files)

```python
from pydantic import BaseModel

class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None

@router.post("/chat/json")
async def chat_json(req: ChatRequest):
    """JSON alternative when no file uploads."""
    session_id = req.session_id or f"sess_{uuid.uuid4().hex[:8]}"
    initial_state = {"messages": [("human", req.query)], "query": req.query, "session_id": session_id}
    config = {"configurable": {"thread_id": session_id}}
    graph = await get_compiled_graph()
    result = await graph.ainvoke(initial_state, config=config)
    return {"answer": result.get("final_answer", ""), "session_id": session_id}
```

### 3.4 Passing Parameters to the Graph and Other Services

The flow is:

```
Client → FastAPI endpoint → Parse params → Build state dict → Invoke graph (config) → Extract result → Return to client
```

**What goes into the state dict:**

- **query**: User message (string)
- **session_id**: Unique conversation ID (used as `thread_id` for the checkpointer)
- **files**: List of `{filename, content}` for document processing
- **messages**: Conversation history (the checkpointer loads prior messages if you use the same `thread_id`)

**What goes into config:**

- `configurable.thread_id`: Must match `session_id` so the SqliteSaver loads the right conversation.
- `recursion_limit`: Safety cap on graph steps (e.g. 15).

Your graph nodes (planner, worker, responder) receive `state` and can call:

- Neo4j (via a shared driver)
- Ollama embeddings (via a shared client)
- LM Studio (via LangChain ChatOpenAI)
- Web search tools

All of these are typically initialized once at app startup and injected into the graph or passed via closure.

### 3.5 Example: Wiring Services at Startup

```python
# app/main.py
from fastapi import FastAPI
from app.api.routes import router
from app.config.settings import settings

app = FastAPI(title="My Agent API")
app.include_router(router, prefix="/api/v1")

@app.on_event("startup")
async def startup():
    # Create Neo4j driver, checkpointer, etc.
    # Store in app.state or module-level variables for routes to use
    pass

# Run with: uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

---

## 4. Why You Need a Backend Service

- **Single place to wire services**: Neo4j, Ollama, LM Studio, web tools in one process.
- **Agent coordination**: Host your LangGraph graph; manage roles (planner, advisor, evaluator).
- **API boundary**: Expose HTTP so clients (web UI, CLI, MCP) don’t reimplement logic.
- **Configuration**: Load `.env` once; share settings across all components.

---

## 5. Defining Your Agent Graph

Conceptually:

- **Nodes**: Planner, doc analyst, profile manager, web researcher, advisor, evaluator, responder.
- **State**: Shared TypedDict (messages, query, retrieved_docs, draft_answer, final_answer, etc.).
- **Custom agents**: Different system prompts and tools per role.

Each node:

1. Reads `state`.
2. Calls tools (Neo4j, web search) and/or the LLM.
3. Returns a partial state update (only the keys it changes).

See `agent-orchestration-tools.md` for LangGraph and SqliteSaver details.

---

## 6. Common Pitfalls and Fixes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `FileNotFoundError` or settings not loading | `.env` in wrong directory or wrong cwd | Put `.env` in project root; run uvicorn from project root |
| `/chat` returns 500 | Neo4j, Ollama, or LM Studio unreachable | Check each service with curl; log connection errors at startup |
| Conversation memory lost | Wrong or missing `thread_id` | Use same `session_id` in `config["configurable"]["thread_id"]` for a conversation |
| Requests hang | Graph loop or tool timeout | Add `recursion_limit`; add logging; simplify graph |
| State key errors | TypedDict mismatch | Define shared state schema; each node only updates its own keys |
| Prompt changes have no effect | System prompt not used | Ensure each node explicitly adds your system prompt when building messages |

---

## 7. Official Documentation

- **FastAPI:** https://fastapi.tiangolo.com/
- **FastAPI – Request Forms:** https://fastapi.tiangolo.com/tutorial/request-forms/
- **Pydantic Settings:** https://docs.pydantic.dev/latest/concepts/pydantic_settings/
- **Uvicorn:** https://www.uvicorn.org/
