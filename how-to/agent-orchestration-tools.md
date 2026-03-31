# Agent Orchestration Tools (LangChain, LangGraph, Langflow)

This guide covers three core tools for building AI agents: **LangChain** (components and chains), **LangGraph** (stateful graphs and memory), and **Langflow** (visual prototyping). Each section includes installation, key functions, setup, and official documentation links.

---

## 1. LangChain

### 1.1 How to Install

**Prerequisites:** Python 3.10+, `pip`

```bash
# Create and activate a virtual environment first
python -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate

# Install LangChain packages
pip install langchain langchain-community langchain-openai
pip install langchain-ollama  # if using Ollama for embeddings
```

### 1.2 Why Use LangChain for Your Agent

- **Unified model interface**: swap OpenAI, Anthropic, LM Studio, Ollama, etc. with minimal code changes.
- **Tool abstraction**: define functions as tools so the LLM can decide when to call them.
- **Retrievers**: plug in Neo4j, ChromaDB, or any vector store for semantic search.
- **Document loaders**: load PDFs, DOCX, web pages, and extract text for chunking.
- **Prompt templates**: reusable prompts with variables for different agent roles.
- **Chains**: compose LLM calls, tools, and retrievers into pipelines.

### 1.3 Key Functions and Capabilities

| Capability | What It Does | Example Use |
|------------|--------------|-------------|
| **ChatOpenAI** | Connect to any OpenAI-compatible API (e.g. LM Studio) | Main LLM for reasoning, planning, answering |
| **OllamaEmbeddings** | Generate embeddings via local Ollama | Semantic search over documents |
| **Tool / @tool** | Wrap functions so the LLM can call them | Web search, Neo4j query, document retrieval |
| **Retriever** | Fetch relevant chunks given a query | RAG: inject context into the LLM prompt |
| **Document loaders** | Load PDF, DOCX, web page, etc. | Ingest user-uploaded files |
| **RecursiveCharacterTextSplitter** | Split text into overlapping chunks | Prepare documents for embedding |
| **PromptTemplate** | Parameterized prompts | Define system prompts per agent role |
| **LCEL (LangChain Expression Language)** | Chain components with `|` | `prompt \| llm \| output_parser` |
| **create_agent** | Prebuilt agent with tools | Quick-start agent in under 10 lines |

### 1.4 How to Set Up and Use

**Example: LLM client for LM Studio**

```python
from langchain_openai import ChatOpenAI
import os

llm = ChatOpenAI(
    base_url=os.environ.get("LLM_BASE_URL", "http://localhost:1234/v1"),
    api_key="not-used",  # LM Studio ignores this
    model=os.environ.get("LLM_MODEL", "openai/gpt-oss-20b"),
    temperature=0.2,
)
```

**Example: Define a tool**

```python
from langchain_core.tools import tool

@tool
def search_knowledge_graph(query: str) -> str:
    """Search the user's knowledge graph for entities matching the query."""
    # Your Neo4j query logic here
    return "Found: ..."
```

**Example: Simple RAG chain**

```python
# 1. Embed query, 2. Retrieve chunks, 3. Call LLM with context
# (Implementation depends on your retriever; see neo4j-and-graph-memory.md)
```

### 1.5 Official Documentation

- **Main docs:** https://python.langchain.com/docs/
- **Installation:** https://python.langchain.com/oss/python/langchain/install
- **Quickstart:** https://python.langchain.com/oss/python/langchain/quickstart
- **Tools:** https://python.langchain.com/oss/python/langchain/tools
- **Integrations (providers):** https://python.langchain.com/oss/python/integrations/providers/overview
- **Memory concepts:** https://docs.langchain.com/oss/python/concepts/memory

---

## 2. LangGraph

### 2.1 How to Install

```bash
pip install langgraph
pip install langgraph-checkpoint-sqlite aiosqlite  # for persistent memory
```

### 2.2 Why Use LangGraph for Your Agent

- **Stateful multi-node graphs**: turn a sequence of LLM/tool calls into a directed graph with shared state.
- **Durable execution**: resume from checkpoints if a node fails.
- **Conversation memory**: persist chat history across requests using a checkpointer.
- **Human-in-the-loop**: interrupt and inspect state at any node.
- **Conditional routing**: route to different nodes based on LLM or rule-based decisions.
- **Subgraphs**: nest graphs for complex workflows.

### 2.3 Key Functions and Capabilities

| Capability | What It Does | Example Use |
|------------|--------------|-------------|
| **StateGraph** | Create a graph with a typed state schema | Define your agent workflow |
| **add_node** | Add a node (Python function) to the graph | Planner, worker, evaluator, responder |
| **add_edge** | Connect nodes: `A -> B` | Linear flow: planner → worker → responder |
| **add_conditional_edges** | Route based on state or function | Branch: "needs_docs" vs "direct_answer" |
| **compile** | Build the runnable graph | Add checkpointer for memory |
| **invoke** / **astream** | Run the graph (sync or async) | Process a user message |
| **get_state** | Read current state of a thread | Inspect or debug |
| **MessagesState** | Built-in state with `messages` channel | Chat history + reducer for appending |
| **START, END** | Graph entry and exit constants | Wire first and last nodes |

### 2.4 SqliteSaver Setup (Persistent Memory)

SqliteSaver stores graph state (messages, retrieved docs, etc.) in a SQLite file so your agent remembers past turns. **You must use it as a context manager or manage the connection lifecycle.**

**Install:**

```bash
pip install langgraph-checkpoint-sqlite aiosqlite
```

**Setup (async, for FastAPI):**

```python
import os
import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# 1. Ensure data directory exists
db_path = os.environ.get("SQLITE_DB_PATH", "data/agent.db")
db_dir = os.path.dirname(db_path)
if db_dir:
    os.makedirs(db_dir, exist_ok=True)

# 2. Create connection and checkpointer
conn = await aiosqlite.connect(db_path)
checkpointer = AsyncSqliteSaver(conn)
await checkpointer.setup()

# 3. Compile graph with checkpointer
graph = workflow.compile(checkpointer=checkpointer)
```

**Usage when invoking:**

```python
config = {"configurable": {"thread_id": session_id}}  # session_id = unique per conversation
result = await graph.ainvoke(initial_state, config=config)
```

**Important:** Every request for the same conversation must use the same `thread_id` so the checkpointer loads prior messages.

### 2.5 How to Set Up and Use

**Example: 3-node graph**

```python
from langgraph.graph import StateGraph, START, END
from typing import TypedDict

class AgentState(TypedDict):
    messages: list
    query: str
    retrieved_docs: list

def planner(state: AgentState):
    # Decide next step; return updated state
    return {"next_node": "worker"}

def worker(state: AgentState):
    # Call tools, LLM; return state with draft answer
    return {"retrieved_docs": [...], "draft_answer": "..."}

def responder(state: AgentState):
    # Format final answer
    return {"messages": state["messages"] + [("ai", state["draft_answer"])]}

workflow = StateGraph(AgentState)
workflow.add_node("planner", planner)
workflow.add_node("worker", worker)
workflow.add_node("responder", responder)
workflow.add_edge(START, "planner")
workflow.add_edge("planner", "worker")
workflow.add_edge("worker", "responder")
workflow.add_edge("responder", END)

# Compile with checkpointer for memory (see 2.4)
graph = workflow.compile(checkpointer=checkpointer)
```

### 2.6 Official Documentation

- **LangGraph overview:** https://langchain-ai.github.io/langgraph/
- **Install:** https://docs.langchain.com/oss/python/langgraph/install
- **Persistence (SqliteSaver, checkpoints):** https://docs.langchain.com/oss/python/langgraph/concepts/persistence
- **Add memory:** https://docs.langchain.com/oss/python/langgraph/add-memory
- **Interrupts (human-in-the-loop):** https://docs.langchain.com/oss/python/langgraph/interrupts
- **StateGraph API:** https://langchain-ai.github.io/langgraph/reference/graphs/

---

## 3. Langflow

### 3.1 How to Install

```bash
pip install langflow
```

### 3.2 Why Use Langflow for Your Agent

- **Visual flow builder**: drag-and-drop components instead of writing glue code.
- **Playground**: test flows in real time before integrating into your app.
- **MCP support**: use Langflow as an MCP client or server.
- **Prebuilt components**: LLMs, embeddings, retrievers, agents, tools.
- **Export**: prototype in the UI, then implement logic in code.

### 3.3 Key Functions and Capabilities

| Capability | What It Does | Example Use |
|------------|--------------|-------------|
| **Visual editor** | Connect components (inputs, LLMs, tools, outputs) | Design RAG or agent flow |
| **Playground** | Run flows with sample inputs | Debug and tune prompts |
| **Components** | Prebuilt nodes for models, embeddings, vector stores | LM Studio, Ollama, Neo4j, etc. |
| **Flows** | Serializable workflow definition | Share or version control designs |
| **Langflow API** | Trigger flows via HTTP | Embed flows in your backend |
| **MCP client/server** | Connect to or expose MCP tools | Integrate with IDEs, other agents |
| **Custom components** | Create Python components | Add your own tools or logic |

### 3.4 How to Set Up and Use

```bash
langflow run
```

- Open the URL printed in the terminal (e.g. `http://127.0.0.1:7860`).
- Create a new flow: add Input → Chat Model (configure LM Studio URL) → Output.
- Add a Retriever component if you have a vector store.
- Use the Playground to test.
- Publish the flow to get an API endpoint, or use the design as a blueprint for your code.

### 3.5 Official Documentation

- **Langflow docs:** https://docs.langflow.org/
- **Installation:** https://docs.langflow.org/get-started-installation
- **Quickstart:** https://docs.langflow.org/get-started-quickstart
- **Components:** https://docs.langflow.org/concepts-components
- **Flows:** https://docs.langflow.org/concepts-flows
- **MCP:** https://docs.langflow.org/mcp-server

---

## 4. Common Pitfalls and Fixes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ImportError: cannot import name 'ChatOpenAI'` | Missing `langchain-openai` | `pip install langchain-openai` |
| LangChain calls api.openai.com | `base_url` not set | Pass `base_url` to ChatOpenAI |
| `AttributeError: '_GeneratorContextManager' has no attribute 'get_next_version'` | SqliteSaver used without proper setup | Use `AsyncSqliteSaver(conn)` + `await checkpointer.setup()` (see 2.4) |
| Graph loops or never ends | Edges or conditional routing misconfigured | Add logging; start with 2–3 nodes; verify exit conditions |
| State key errors | TypedDict mismatch | Define shared state schema; add defaults for optional keys |
| `langflow: command not found` | Virtualenv not activated | Activate venv; `pip install langflow` |
| Conversation memory lost | Wrong or missing `thread_id` | Use same `session_id` per conversation in `config["configurable"]["thread_id"]` |

---

## 5. How These Fit Together

- **Langflow**: Design and prototype flows visually; explain your architecture in demos.
- **LangChain**: Implement LLM clients, tools, retrievers, and prompts in code.
- **LangGraph**: Build the multi-node agent graph, wire in LangChain components, add SqliteSaver for memory.
- **Backend**: Host the compiled graph, expose `/chat` (or similar) that accepts parameters and invokes the graph with the right `thread_id`.
