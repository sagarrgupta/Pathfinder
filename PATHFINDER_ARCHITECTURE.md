# Pathfinder: System Architecture

> Single source of truth for the Pathfinder academic guidance agent.
> Last updated: 2026-02-06

---

## 1. Vision & Goals

Pathfinder is a private, always-available AI agent that helps students make informed academic and career decisions. Students upload personal documents (transcripts, resumes), enter free-text profile information, and ask natural-language questions. The system combines personal data with external information to deliver personalized, cited, and reliable guidance.

**Core Principles:**
- Privacy: student data never leaves their control
- Personalization: every answer considers the student's unique profile
- Transparency: the student can see and edit everything the system knows
- Reliability: answers are grounded in real data, with confidence scores and citations
- Modularity: multi-agent collaboration with clear separation of concerns

---

## 2. Architectural Decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Multi-Agent Pattern | Collaborative Swarm (LangGraph StateGraph) | True multi-agent collaboration; native LangGraph paradigm; agents hand off dynamically |
| 2 | KG Extraction | Hybrid: LLM + Rule-based | Rule-based for structured docs (transcripts); LLM for unstructured text |
| 3 | Knowledge Store | Neo4j only (graph + vector) | Single DB for graph traversal AND semantic search; drop ChromaDB |
| 4 | Memory | SqliteSaver (conversations) + Neo4j (profile + KG) | LangGraph-native checkpointer; Neo4j for structured knowledge |
| 5 | Doc Processing | Adaptive: text-first, vision model fallback | Fast for text PDFs; vision model for scanned/complex docs |
| 6 | Web Search | Fallback chain: Tavily -> Google CSE -> Brave -> DuckDuckGo | Resilient multi-source; best quality first, free fallback last |
| 7 | Streaming | Step-by-step progress + token streaming (SSE) | User sees agent progress and words appearing in real-time |
| 8 | Guardrails | Moderate + topic guardrail toggle (default ON) | Hallucination detection, confidence scoring; topic filter is configurable |
| 9 | Frontend | React + Vite + Tailwind + shadcn/ui | Existing stack + polished components; no migration cost |
| 10 | MCP | Real MCP Server for tool serving | Proper MCP protocol; tools usable by external MCP clients |
| 11 | Node Design | 10+1 nodes | Comprehensive coverage: guard, plan, clarify, process, retrieve, advise, evaluate, respond |

---

## 3. Models

| Role | Model | Host | Notes |
|---|---|---|---|
| Text LLM | `openai/gpt-oss-20b` | LM Studio (`localhost:1234`) | OpenAI-compatible API; used by all reasoning nodes |
| Vision LLM | `qwen/qwen3-vl-8b` | LM Studio (`localhost:1234`) | Fallback for scanned/image-based documents |
| Text Embeddings | `mxbai-embed-large` | Ollama (`localhost:11434`) | 1024-dim embeddings for Neo4j vector index |

---

## 4. Infrastructure

```
┌──────────────────────────────────────────────────────┐
│                    Client Browser                     │
│            React + Vite + Tailwind + shadcn/ui        │
│         Pages: Chat | My Profile | Settings           │
└───────────────────────┬──────────────────────────────┘
                        │ HTTP / SSE
                        ▼
┌──────────────────────────────────────────────────────┐
│                   FastAPI Backend                      │
│                  (port 8001)                           │
│                                                        │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │  API Routes  │  │  MCP Server  │  │  SSE Stream  │ │
│  └──────┬──────┘  └──────┬───────┘  └──────┬───────┘ │
│         └────────────────┼─────────────────┘          │
│                          ▼                             │
│         ┌────────────────────────────┐                │
│         │   LangGraph StateGraph      │                │
│         │   (10+1 Agent Nodes)        │                │
│         └─────────┬──────────────────┘                │
│                   │                                    │
│    ┌──────────────┼──────────────┐                    │
│    ▼              ▼              ▼                     │
│ ┌───────┐  ┌──────────┐  ┌──────────┐               │
│ │Neo4j  │  │ SQLite   │  │ Web      │               │
│ │Graph+ │  │ Memory   │  │ Search   │               │
│ │Vector │  │(SqliteSvr)│ │ Chain    │               │
│ └───┬───┘  └──────────┘  └──────────┘               │
└─────┼────────────────────────────────────────────────┘
      │
      ▼
┌──────────┐   ┌──────────┐   ┌──────────┐
│  Neo4j   │   │ LM Studio│   │  Ollama  │
│ (Docker) │   │ gpt-oss  │   │ mxbai-   │
│ port 7687│   │ qwen3-vl │   │ embed    │
│ bolt     │   │ port 1234│   │ port     │
│ port 7474│   │          │   │ 11434    │
│ browser  │   │          │   │          │
└──────────┘   └──────────┘   └──────────┘
```

---

## 5. LangGraph Agent Nodes (10+1)

### Node Diagram

```
User Input
    │
    ▼
┌─────────────┐
│ INPUT GUARD  │──blocked──► RESPONDER ──► Output
└──────┬──────┘
       │ safe
       ▼
┌─────────────┐
│ ORCHESTRATOR │──missing info──► CLARIFIER ──► Output
└──────┬──────┘
       │ routes to one or more nodes
       ├──► DOC ANALYST ──► PROFILE MANAGER ──► EVALUATOR
       ├──► PROFILE MANAGER ──► WEB RESEARCHER ──► ACADEMIC ADVISOR ──► EVALUATOR
       ├──► PROFILE MANAGER ──► WEB RESEARCHER ──► CAREER PLANNER ──► EVALUATOR
       ├──► PROFILE MANAGER ──► WEB RESEARCHER ──► INTERVIEW PREP ──► EVALUATOR
       ├──► WEB RESEARCHER ──► EVALUATOR
       └──► RESPONDER (direct/simple questions)
                │
                ▼
          EVALUATOR
           │    │
           │    └── profile updates ──► PROFILE MANAGER
           │    └── not grounded ──► ORCHESTRATOR (retry)
           ▼
        RESPONDER ──► Streamed Output (SSE)
```

### Node Specifications

| # | Node | Module | Responsibility | LangChain Components |
|---|---|---|---|---|
| 1 | Input Guard | `app/agents/input_guard.py` | Validate input; topic filter (toggle); prompt injection detection | -- |
| 2 | Orchestrator | `app/agents/orchestrator.py` | Classify intent; check available data; create plan; route | `ChatOpenAI`, `JsonOutputParser` |
| 3 | Clarifier | `app/agents/clarifier.py` | Identify missing info; ask user; suggest uploads | `ChatOpenAI` |
| 4 | Doc Analyst | `app/agents/doc_analyst.py` | Adaptive doc processing; chunk + embed; entity extraction | `PyPDFLoader`, `RecursiveCharacterTextSplitter`, `OllamaEmbeddings`, `ChatOpenAI` |
| 5 | Profile Manager | `app/agents/profile_manager.py` | Neo4j KG CRUD; vector search; profile queries | `Neo4jGraph`, `Neo4jVector`, `GraphCypherQAChain` |
| 6 | Web Researcher | `app/agents/web_researcher.py` | Fallback search chain; extract info; cite sources | `TavilySearchResults`, `GoogleSerperAPIWrapper`, `BraveSearchWrapper`, `DuckDuckGoSearchResults` |
| 7 | Academic Advisor | `app/agents/academic_advisor.py` | Major/university/course guidance; compare profile vs requirements | `ChatOpenAI` |
| 8 | Career Planner | `app/agents/career_planner.py` | Job matching; skill gap analysis; career paths; course scheduling | `ChatOpenAI` |
| 9 | Interview Prep | `app/agents/interview_prep.py` | Mock interviews; personalized Q generation; answer feedback | `ChatOpenAI` |
| 10 | Evaluator | `app/agents/evaluator.py` | Groundedness check; confidence scoring; hallucination detection; passive profile learning | `ChatOpenAI` |
| 11 | Responder | `app/agents/responder.py` | Format answer; stream via SSE; add citations; step progress | `ChatOpenAI` (for synthesis) |

---

## 6. Shared State Schema

All nodes read from and write to a shared `TypedDict` state that flows through the graph:

```python
class PathfinderState(TypedDict):
    # Input
    messages: Annotated[list, add_messages]  # Conversation history (LangGraph managed)
    query: str                                # Current user query
    files: list[UploadedFile]                 # Files uploaded in this turn
    session_id: str                           # Chat session ID
    is_global_upload: bool                    # Whether uploaded docs go to global profile

    # Orchestrator output
    intent: str                               # Classified intent (academic, career, interview, document, general, etc.)
    plan: list[str]                           # Ordered list of agent nodes to execute
    next_node: str                            # Next node to route to
    missing_info: list[str]                   # Info the system needs but doesn't have

    # Data gathered by nodes
    profile_data: dict                        # Student profile from Neo4j KG
    retrieved_documents: list[dict]           # Chunks from Neo4j vector search
    graph_results: list[dict]                 # Structured results from Neo4j graph queries
    web_results: list[dict]                   # Results from web search
    extracted_entities: list[dict]            # Entities extracted from documents

    # Evaluation
    draft_answer: str                         # Answer before evaluation
    confidence_score: float                   # 0.0 to 1.0
    is_grounded: bool                         # Whether answer is grounded in sources
    profile_updates: list[dict]               # Profile updates detected from conversation
    citations: list[dict]                     # Sources for the answer

    # Output
    final_answer: str                         # Final formatted answer
    step_progress: list[str]                  # Progress messages for SSE streaming

    # Guard
    is_blocked: bool                          # Whether input was blocked by guard
    block_reason: str                         # Why input was blocked
    topic_guard_enabled: bool                 # Whether topic filtering is active
```

---

## 7. Neo4j Graph Schema

### Node Types

| Label | Properties | Purpose |
|---|---|---|
| `Student` | `id`, `name`, `email`, `gpa`, `university`, `program`, `semester`, `created_at`, `updated_at` | Central student node |
| `Course` | `code`, `name`, `grade`, `credits`, `semester`, `year` | Academic course |
| `Skill` | `name`, `proficiency`, `years_experience` | Technical/soft skill |
| `Department` | `name` | Academic department |
| `Document` | `id`, `filename`, `type` (transcript/resume/other), `scope` (global/session), `session_id`, `uploaded_at` | Uploaded document metadata |
| `Chunk` | `id`, `text`, `embedding` (vector), `page_number`, `chunk_index` | Document chunk with embedding |
| `Company` | `name`, `role`, `start_date`, `end_date` | Work experience |
| `Goal` | `type` (phd/masters/job/etc), `field`, `description` | Student goals |
| `Interest` | `name`, `category` | Academic/career interests |
| `Project` | `name`, `description`, `technologies` | Student projects |

### Relationship Types

| Relationship | From | To | Properties |
|---|---|---|---|
| `TOOK` | Student | Course | `semester`, `year` |
| `HAS_SKILL` | Student | Skill | `source` (resume/manual/inferred) |
| `IN_DEPARTMENT` | Course | Department | -- |
| `UPLOADED` | Student | Document | `timestamp` |
| `FROM_DOCUMENT` | Chunk | Document | `page_number` |
| `HAS_GOAL` | Student | Goal | `priority` |
| `INTERESTED_IN` | Student | Interest | `source` |
| `WORKED_AT` | Student | Company | `role`, `duration` |
| `COMPLETED` | Student | Project | -- |
| `STRENGTH_IN` | Student | Department | `avg_grade` |
| `WEAKNESS_IN` | Student | Department | `avg_grade` |
| `ENROLLED_AT` | Student | University | `program`, `start_year` |

### Vector Index

```cypher
CREATE VECTOR INDEX chunk_embeddings IF NOT EXISTS
FOR (c:Chunk) ON (c.embedding)
OPTIONS {indexConfig: {
  `vector.dimensions`: 1024,
  `vector.similarity_function`: 'cosine'
}}
```

---

## 8. Document Processing Pipeline

```
Document Upload
    │
    ├── PDF File
    │     │
    │     ▼
    │   pypdf text extraction
    │     │
    │     ├── text OK ──► chunk text ──► embed chunks ──► Neo4j Chunk nodes
    │     │                                                     │
    │     │                                                     ▼
    │     │                                            entity extraction
    │     │                                            (rule-based for transcripts,
    │     │                                             LLM for unstructured)
    │     │                                                     │
    │     │                                                     ▼
    │     │                                            Neo4j graph nodes
    │     │                                            (Course, Skill, Company, etc.)
    │     │
    │     └── text empty/garbage (scanned)
    │           │
    │           ▼
    │         convert pages to images
    │           │
    │           ▼
    │         vision model (qwen3-vl-8b)
    │           │
    │           ▼
    │         structured text output ──► chunk ──► embed ──► Neo4j
    │
    └── Free Text Input (from profile page)
          │
          ▼
        LLM entity extraction
          │
          ▼
        Neo4j graph nodes
```

### Document Scoping

- **Global documents** (uploaded in My Profile): entities stored with `scope: 'global'`; available in ALL chat sessions
- **Session documents** (uploaded in a chat): entities stored with `scope: 'session'`, `session_id: '<id>'`; only available in that session
- **Promote to global**: user toggle in chat → changes scope from session to global, merges into global KG

---

## 9. Web Search Fallback Chain

```
Search Request
    │
    ▼
┌──────────┐  fail/rate-limited  ┌──────────┐  fail  ┌──────────┐  fail  ┌──────────┐
│  Tavily  │ ──────────────────► │ Google   │ ─────► │  Brave   │ ─────► │DuckDuckGo│
│ (AI-opt) │                     │   CSE    │        │ Search   │        │(unlimited)│
└──────────┘                     └──────────┘        └──────────┘        └──────────┘
```

Each adapter implements the same interface: `async search(query: str, max_results: int) -> list[SearchResult]`

---

## 10. Memory Architecture

### Layer 1: Conversation Memory (Short-term)
- **Store**: SQLite via LangGraph `SqliteSaver`
- **Scope**: per chat session (thread_id = session_id)
- **Contains**: message history (user + assistant + tool calls)
- **Persistence**: survives server restarts (SQLite file)

### Layer 2: Student Profile (Long-term)
- **Store**: Neo4j knowledge graph
- **Scope**: global (shared across all sessions)
- **Contains**: structured student data (GPA, skills, courses, goals, etc.)
- **Updated by**: Doc Analyst (document processing), Evaluator (passive learning), Profile Manager (explicit edits)

### Layer 3: Session Knowledge Graph
- **Store**: Neo4j (tagged with session_id)
- **Scope**: per chat session
- **Contains**: entities from session-scoped documents
- **Promotable**: user can toggle to move to global scope

---

## 11. API Endpoints

| Method | Path | Purpose | Response |
|---|---|---|---|
| `POST` | `/api/v1/chat` | Main chat (SSE streaming) | SSE stream: progress events + token stream |
| `POST` | `/api/v1/documents` | Upload document (global or session) | `{document_id, entities_extracted, scope}` |
| `GET` | `/api/v1/profile` | Get student profile | `{profile_data, documents, graph_summary}` |
| `PUT` | `/api/v1/profile` | Update profile field | `{updated_fields}` |
| `DELETE` | `/api/v1/profile/entity/{id}` | Delete a profile entity | `{deleted}` |
| `POST` | `/api/v1/profile/text` | Add free text info to profile | `{entities_extracted, graph_updated}` |
| `GET` | `/api/v1/profile/graph` | Get KG data for visualization | `{nodes, relationships}` |
| `GET` | `/api/v1/sessions` | List chat sessions | `[{session_id, title, last_message, created_at}]` |
| `DELETE` | `/api/v1/sessions/{id}` | Delete a chat session | `{deleted}` |
| `PUT` | `/api/v1/sessions/{id}/promote-doc` | Promote session doc to global | `{promoted, graph_updated}` |
| `GET` | `/api/v1/settings` | Get current settings | `{topic_guard_enabled, ...}` |
| `PUT` | `/api/v1/settings` | Update settings | `{updated}` |
| `GET` | `/api/v1/health` | Health check | `{status, neo4j, lm_studio, ollama}` |

---

## 12. Frontend Pages

### Page 1: Chat
- Chat message list with SSE streaming (step progress + token stream)
- File upload with toggle: "Add to global profile"
- Sidebar: session list, new chat, switch sessions
- Method/confidence badges on messages
- Expandable source citations

### Page 2: My Profile
- **Input methods**: document upload + free text input box
- **Profile viewer** (tabs): Personal Info, Academic, Skills, Courses, Goals, Documents
- **Edit/Delete** on each section → updates Neo4j graph in real-time
- **Knowledge graph** data display

### Page 3: Settings
- Topic guardrail toggle (ON/OFF)
- Model info display (read-only)
- Session management

---

## 13. Project Structure

```
pathfinder/
├── app/
│   ├── __init__.py
│   ├── main.py                          # FastAPI app entry point
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py                  # Pydantic settings (Neo4j, LLM, search keys, etc.)
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py                    # All API endpoints
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── input_guard.py               # Node 1: Input validation + topic filter
│   │   ├── orchestrator.py              # Node 2: Intent classification + planning
│   │   ├── clarifier.py                 # Node 3: Ask for missing info
│   │   ├── doc_analyst.py               # Node 4: Document processing pipeline
│   │   ├── profile_manager.py           # Node 5: Neo4j KG CRUD + queries
│   │   ├── web_researcher.py            # Node 6: Web search fallback chain
│   │   ├── academic_advisor.py          # Node 7: Academic guidance
│   │   ├── career_planner.py            # Node 8: Career + job guidance
│   │   ├── interview_prep.py            # Node 9: Interview preparation
│   │   ├── evaluator.py                 # Node 10: Quality + groundedness check
│   │   └── responder.py                 # Node 11: Format + stream response
│   ├── core/
│   │   ├── __init__.py
│   │   ├── graph.py                     # LangGraph StateGraph assembly
│   │   ├── state.py                     # Shared state TypedDict
│   │   └── memory.py                    # SqliteSaver checkpointer
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── llm/
│   │   │   ├── __init__.py
│   │   │   └── lmstudio.py             # ChatOpenAI wrapper for LM Studio
│   │   ├── embeddings/
│   │   │   ├── __init__.py
│   │   │   └── ollama.py               # OllamaEmbeddings wrapper
│   │   ├── neo4j/
│   │   │   ├── __init__.py
│   │   │   ├── graph_store.py           # Neo4j graph operations (Cypher CRUD)
│   │   │   └── vector_store.py          # Neo4j vector index operations
│   │   ├── pdf/
│   │   │   ├── __init__.py
│   │   │   └── extractor.py             # PDF text + vision extraction
│   │   └── web_search/
│   │       ├── __init__.py
│   │       ├── tavily.py                # Tavily search adapter
│   │       ├── google_cse.py            # Google Custom Search adapter
│   │       ├── brave.py                 # Brave Search adapter
│   │       ├── duckduckgo.py            # DuckDuckGo adapter
│   │       └── fallback_chain.py        # Orchestrates fallback chain
│   ├── mcp_server.py                    # Real MCP server (tool serving)
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── models.py                    # Pydantic models (API request/response)
│   └── utils/
│       ├── __init__.py
│       └── ids.py                       # ID generation utilities
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── components.json                  # shadcn/ui config
│   └── src/
│       ├── main.jsx
│       ├── App.jsx                      # React Router setup
│       ├── index.css
│       ├── lib/
│       │   └── utils.js                 # shadcn/ui utility (cn function)
│       ├── components/
│       │   ├── ui/                      # shadcn/ui components
│       │   ├── chat/
│       │   │   ├── ChatInterface.jsx
│       │   │   ├── MessageList.jsx
│       │   │   ├── Message.jsx
│       │   │   ├── InputArea.jsx
│       │   │   └── StreamingMessage.jsx
│       │   ├── profile/
│       │   │   ├── ProfilePage.jsx
│       │   │   ├── ProfileViewer.jsx
│       │   │   ├── DocumentUpload.jsx
│       │   │   └── TextInput.jsx
│       │   ├── settings/
│       │   │   └── SettingsPage.jsx
│       │   ├── layout/
│       │   │   ├── Sidebar.jsx
│       │   │   └── Header.jsx
│       │   └── shared/
│       │       └── ErrorBoundary.jsx
│       ├── context/
│       │   └── AppContext.jsx           # Global state (sessions, profile, settings)
│       ├── services/
│       │   └── api.js                   # API client (HTTP + SSE)
│       └── pages/
│           ├── ChatPage.jsx
│           ├── ProfilePage.jsx
│           └── SettingsPage.jsx
├── docker/
│   ├── docker-compose.yml               # Neo4j + app services
│   └── Dockerfile
├── data/
│   └── pathfinder.db                    # SQLite memory (auto-created)
├── requirements.txt
├── start.sh
├── PATHFINDER_ARCHITECTURE.md           # This file
└── .env.example                         # Environment variable template
```

---

## 14. Guardrails

### Input Guard
- **Topic filter** (toggleable): Reject queries unrelated to academics/career when enabled
- **Prompt injection detection**: Block attempts to override system prompts
- **Input validation**: Max length, empty query check

### Evaluator
- **Groundedness check**: Compare answer against retrieved sources; flag unsupported claims
- **Confidence scoring**: 0.0-1.0 based on source quality and coverage
- **Hallucination detection**: If answer contains specific facts not in any source, add disclaimer
- **Passive profile learning**: Extract preferences/facts mentioned in conversation, update KG

---

## 15. MCP Server

Exposes Pathfinder tools via the Model Context Protocol standard:

| Tool Name | Description |
|---|---|
| `search_knowledge_graph` | Query the student's Neo4j knowledge graph |
| `search_documents` | Semantic search over document chunks |
| `search_web` | Search external sources via fallback chain |
| `get_student_profile` | Get structured student profile |
| `analyze_document` | Process and extract entities from a document |

Any MCP-compatible client (Claude Desktop, Cursor, etc.) can connect to the Pathfinder MCP server and use these tools.

---

## 16. SSE Streaming Protocol

The `/api/v1/chat` endpoint returns an SSE stream with typed events:

```
event: progress
data: {"node": "orchestrator", "message": "Analyzing your question..."}

event: progress
data: {"node": "profile_manager", "message": "Checking your academic profile..."}

event: progress
data: {"node": "web_researcher", "message": "Searching for university requirements..."}

event: progress
data: {"node": "academic_advisor", "message": "Comparing your profile with requirements..."}

event: progress
data: {"node": "evaluator", "message": "Verifying answer quality..."}

event: token
data: {"content": "Based"}

event: token
data: {"content": " on"}

event: token
data: {"content": " your"}

...

event: done
data: {"confidence": 0.85, "citations": [...], "method": "rag+web", "profile_updates": [...]}
```
