# Pathfinder: Current System Architecture

> Single-source architecture reference for the Pathfinder codebase.
> Last updated: 2026-04-11

---

## 1. What Pathfinder Is

Pathfinder is a local-first advising system that combines:

- a FastAPI backend
- a LangGraph multi-agent workflow
- Neo4j for profile, evidence, and graph memory
- SQLite checkpointers for conversational continuity
- a React frontend with SSE-based chat streaming

The current implementation is broader than the earlier "academic guidance only" framing. It now supports:

- academic advising
- course planning
- program and eligibility reasoning
- career matching and planning
- interview preparation
- document ingestion and profile extraction
- replay/evaluation workflows
- saved recommendations with outcome tracking

---

## 2. Current Architectural Shape

### Core runtime

1. The frontend sends chat, profile, settings, and replay requests to FastAPI.
2. The backend builds a `PathfinderState` object for the request.
3. LangGraph routes the request through a multi-step agent workflow.
4. Agents retrieve profile memory, semantic evidence, and web results as needed.
5. An evaluator checks groundedness and quality before response synthesis.
6. The responder streams progress and answer tokens back over SSE.

### Main storage layers

- `Neo4j`: long-lived student profile, document evidence, graph entities, recommendation state
- `SQLite` via LangGraph `SqliteSaver`: per-session conversational checkpointing
- local filesystem: replay artifacts, logs, uploaded files, eval fixtures

### Main integration points

- LM Studio text model
- LM Studio vision model
- Ollama embeddings
- web search provider chain
- MCP server for external tool access

---

## 3. High-Level Diagram

```text
Browser UI
  -> FastAPI routes
  -> LangGraph StateGraph
  -> agent nodes
  -> retrieval / memory / web tools
  -> evaluator
  -> responder
  -> SSE stream back to UI

FastAPI / LangGraph depend on:
  - Neo4j graph + vector memory
  - SQLite conversation checkpoints
  - LM Studio text + vision inference
  - Ollama embeddings
  - web search adapters
```

---

## 4. Runtime Decisions In The Current Code

| Area | Current implementation |
|---|---|
| Workflow engine | `langgraph.graph.StateGraph` |
| Shared state | `app/core/state.py::PathfinderState` |
| Checkpointing | LangGraph SQLite checkpointer in `app/core/memory.py` |
| Profile + evidence store | Neo4j via `app/adapters/neo4j/graph_store.py` |
| Semantic retrieval | Neo4j-backed retrieval / memory pack flow |
| Web search | Tavily -> Google CSE -> Brave -> DuckDuckGo |
| Document ingestion | PDF/image/DOCX extraction via `app/adapters/pdf/extractor.py` |
| Streaming | Server-Sent Events from `/api/v1/chat` |
| External tool exposure | MCP server in `app/mcp_server.py` |

Two important changes from the older document:

- the active retrieval model is now best described as a `memory_pack` pipeline rather than a simple "vector search plus graph query" design
- the active agent graph has 16 nodes, not the older 10+1 layout

---

## 5. LangGraph Workflow

### Registered nodes

The compiled graph in [`app/core/graph.py`](/path/to/Pathfinder/app/core/graph.py) currently registers these nodes:

1. `input_guard`
2. `orchestrator`
3. `clarifier`
4. `doc_analyst`
5. `profile_manager`
6. `web_researcher`
7. `fact_extractor`
8. `course_planner`
9. `program_advisor`
10. `career_matcher`
11. `eligibility_reasoner`
12. `academic_advisor`
13. `career_planner`
14. `interview_prep`
15. `evaluator`
16. `responder`

### Routing pattern

```text
input_guard
  -> responder        if blocked
  -> orchestrator     otherwise

orchestrator
  -> clarifier
  -> doc_analyst
  -> profile_manager
  -> web_researcher
  -> fact_extractor
  -> course_planner
  -> program_advisor
  -> career_matcher
  -> eligibility_reasoner
  -> academic_advisor
  -> career_planner
  -> interview_prep
  -> evaluator
  -> responder

clarifier -> responder

doc_analyst / profile_manager / web_researcher / fact_extractor
  -> next planned node

advisor/planner/reasoner nodes
  -> evaluator

evaluator
  -> responder

responder
  -> END
```

### Design intent in the current code

- `input_guard` blocks unsafe or off-scope requests
- `orchestrator` decides the workflow and next node
- retrieval and evidence gathering happen before advice-heavy nodes when needed
- `fact_extractor` converts mixed evidence into structured records
- planning/advising nodes generate a structured decision payload
- `evaluator` checks support, issues, and groundedness
- `responder` turns the result into user-facing streamed output

---

## 6. Shared State Model

The shared state has grown well beyond the earlier minimal schema. The current `PathfinderState` includes:

### Inputs and runtime controls

- `messages`
- `query`
- `files`
- `session_id`
- `student_id`
- `is_global_upload`
- `advisor_mode`
- `request_plan`
- `runtime_policy`

### Orchestration and planning

- `intent`
- `plan`
- `next_node`
- `missing_info`
- `workflow`
- `target_entity`
- `source_policy`
- `task_graph`
- `working_memory`
- `dependency_status`
- `trace_summary`
- `stop_reason`

### Student and session continuity

- `session_summary`
- `student_strategy`
- `student_operating_model`
- `recommendation_outcome_profile`
- `decision_continuity`
- `compacted_session`
- `session_memory`
- `short_memory_policy`

### Retrieved and extracted evidence

- `profile_data`
- `retrieved_documents`
- `web_results`
- `semantic_memory`
- `memory_pack`
- `evidence_pack`
- `latest_ingestion_result`
- `conflicts`
- `extracted_entities`
- `document_roles`
- `transcript_states`
- `targeted_web_questions`
- `evidence_records`
- `decision_payload`
- `tool_call_log`

### Evaluation and output

- `draft_answer`
- `confidence_score`
- `is_grounded`
- `profile_updates`
- `citations`
- `final_answer`
- `step_progress`

### Guardrails

- `is_blocked`
- `block_reason`
- `topic_guard_enabled`
- `blocked_reasons`
- `recovery_events`

This is now a workflow-and-evidence state model, not just a chat state plus a few retrieval fields.

---

## 7. Memory And Retrieval

### Conversation memory

- Implemented with LangGraph checkpointing
- Backed by SQLite
- Scoped to session/thread continuity

### Long-lived student memory

- Stored in Neo4j
- Includes personal info, academics, skills, projects, documents, profile facts, candidate facts, recommendation outcomes, and evidence links

### Retrieval model

The active retrieval strategy is exposed as `memory_pack` in [`app/services/execution_registry.py`](/path/to/Pathfinder/app/services/execution_registry.py).

In practice this means downstream nodes work from a normalized evidence envelope instead of directly consuming raw vector search results alone.

Key supporting modules:

- [`app/services/retrieval.py`](/path/to/Pathfinder/app/services/retrieval.py)
- [`app/services/memory_ingestion.py`](/path/to/Pathfinder/app/services/memory_ingestion.py)
- [`app/services/consolidation.py`](/path/to/Pathfinder/app/services/consolidation.py)
- [`app/core/quality.py`](/path/to/Pathfinder/app/core/quality.py)

---

## 8. Neo4j Responsibilities

Neo4j is doing more than "knowledge graph only" in the current code. It now acts as the durable structured memory backbone.

Major responsibilities handled by [`app/adapters/neo4j/graph_store.py`](/path/to/Pathfinder/app/adapters/neo4j/graph_store.py):

- student creation and resolution
- profile reads and profile completeness summaries
- entity CRUD
- document storage and promotion
- candidate fact storage and conflict resolution
- memory item persistence and evidence linking
- recommendation persistence and outcome updates
- graph data export for visualization

The architecture should therefore be described as:

- `Neo4j = profile store + evidence graph + memory ledger + recommendation state`

not just:

- `Neo4j = course/skill/project graph`

---

## 9. Document Ingestion

Pathfinder currently supports:

- PDF
- image
- DOCX
- free-text profile input

The ingestion path is split across:

- [`app/adapters/pdf/extractor.py`](/path/to/Pathfinder/app/adapters/pdf/extractor.py)
- [`app/services/memory_ingestion.py`](/path/to/Pathfinder/app/services/memory_ingestion.py)
- [`app/agents/doc_analyst.py`](/path/to/Pathfinder/app/agents/doc_analyst.py)

Current behavior:

- uploaded files are classified and ingested
- chunks and extracted entities become memory/evidence
- document role inference is tracked
- transcript-specific state can be derived
- session documents can later be promoted to global scope

---

## 10. Web Search

The configured provider chain is:

1. Tavily
2. Google CSE
3. Brave
4. DuckDuckGo

This is implemented through the execution registry and adapter modules:

- [`app/adapters/web_search/tavily.py`](/path/to/Pathfinder/app/adapters/web_search/tavily.py)
- [`app/adapters/web_search/google_cse.py`](/path/to/Pathfinder/app/adapters/web_search/google_cse.py)
- [`app/adapters/web_search/brave.py`](/path/to/Pathfinder/app/adapters/web_search/brave.py)
- [`app/adapters/web_search/duckduckgo.py`](/path/to/Pathfinder/app/adapters/web_search/duckduckgo.py)

---

## 11. API Surface

The active API in [`app/api/routes.py`](/path/to/Pathfinder/app/api/routes.py) is broader than the previous architecture doc.

### Chat and ingestion

- `POST /api/v1/chat`
- `GET /api/v1/documents/check`
- `POST /api/v1/documents`
- `POST /api/v1/profile/text`

### Profiles and graph memory

- `GET /api/v1/profiles`
- `POST /api/v1/profiles`
- `GET /api/v1/profile`
- `PUT /api/v1/profile`
- `DELETE /api/v1/profile/entity/{entity_label}/{entity_name}`
- `PUT /api/v1/profile/entity`
- `DELETE /api/v1/profile/reset`
- `GET /api/v1/profile/conflicts`
- `POST /api/v1/profile/conflicts/self-resolve`
- `POST /api/v1/profile/conflicts/resolve`
- `GET /api/v1/profile/graph`

### Recommendations and outcomes

- `GET /api/v1/recommendations`
- `POST /api/v1/recommendations`
- `PUT /api/v1/recommendations/{recommendation_id}/outcome`

### Sessions, replay, and eval

- `GET /api/v1/sessions`
- `DELETE /api/v1/sessions/{session_id}`
- `PUT /api/v1/sessions/{session_id}/promote-doc`
- `GET /api/v1/replays`
- `GET /api/v1/replays/{replay_id}`
- `GET /api/v1/replays/{replay_id}/evaluate`
- `GET /api/v1/replays/evaluate/recent`
- `GET /api/v1/eval/benchmarks`
- `GET /api/v1/eval/analytics`

### Settings and ops

- `GET /api/v1/settings`
- `PUT /api/v1/settings`
- `DELETE /api/v1/settings/delete-all-data`
- `GET /api/v1/health`
- `GET /api/v1/background/status`

This means Pathfinder should now be thought of as:

- an advising runtime
- a profile/memory management backend
- a replay/evaluation system
- a recommendation tracking system

---

## 12. Frontend

The current router in [`frontend/src/App.jsx`](/path/to/Pathfinder/frontend/src/App.jsx) exposes these pages:

- `/chat`
- `/profile`
- `/profile/conflicts`
- `/replays`
- `/settings`

So the frontend is no longer just "Chat / My Profile / Settings". It also includes:

- conflict resolution UX
- replay inspection/evaluation UX

Key current page files:

- [`frontend/src/pages/ChatPage.jsx`](/path/to/Pathfinder/frontend/src/pages/ChatPage.jsx)
- [`frontend/src/pages/ProfilePage.jsx`](/path/to/Pathfinder/frontend/src/pages/ProfilePage.jsx)
- [`frontend/src/pages/ProfileConflictsPage.jsx`](/path/to/Pathfinder/frontend/src/pages/ProfileConflictsPage.jsx)
- [`frontend/src/pages/ReplayPage.jsx`](/path/to/Pathfinder/frontend/src/pages/ReplayPage.jsx)
- [`frontend/src/pages/SettingsPage.jsx`](/path/to/Pathfinder/frontend/src/pages/SettingsPage.jsx)

---

## 13. MCP Server

Pathfinder exposes an MCP server through [`app/mcp_server.py`](/path/to/Pathfinder/app/mcp_server.py).

At a high level it provides tools for:

- searching the student knowledge graph
- semantic document search
- getting the structured profile
- document analysis / ingestion

This is still an important architectural feature and remains consistent with the earlier design.

---

## 14. Quality And Guardrails

Guardrails are now distributed across several layers rather than living only in a single "guardrail node" concept.

### Current quality layers

- `input_guard` for blocking and scope checks
- `orchestrator` for planning discipline
- `fact_extractor` for structured evidence extraction
- `evaluator` for answer review and repair
- `app/core/quality.py` for evidence normalization, task-graph logic, source audits, and scoring helpers

This makes the current system closer to:

- `guard + plan + extract + evaluate + respond`

than the earlier simpler:

- `guard + answer + check`

---

## 15. Current Project Structure

```text
app/
  api/                 FastAPI routes
  agents/              LangGraph node implementations
  adapters/            Neo4j, LLM, embeddings, PDF, web search adapters
  config/              runtime settings
  core/                graph assembly, shared state, memory, quality
  schemas/             API request/response models
  services/            retrieval, ingestion, consolidation, replay/eval, runtime helpers
  utils/               ids and misc helpers
  mcp_server.py        MCP tool server
  main.py              FastAPI entrypoint

frontend/
  src/pages/           chat, profile, conflicts, replays, settings
  src/components/      chat/layout/shared UI
  src/services/api.js  HTTP + SSE client

tests/
  replay and benchmark fixtures

data/
  local profile/document artifacts

graphify-out/
  generated repo-understanding graph artifacts
```

---

## 16. What This Document Now Assumes

This architecture document intentionally describes the code as it exists now, not the original proposal-only design.

That means:

- the graph has 16 workflow nodes
- replay/eval and recommendation tracking are first-class parts of the system
- the state model is significantly richer than a basic RAG chatbot state
- Neo4j acts as durable memory infrastructure, not just a visualization graph
- the frontend includes conflicts and replay pages

If the code changes again, this file should be updated alongside:

- [`app/core/graph.py`](/path/to/Pathfinder/app/core/graph.py)
- [`app/core/state.py`](/path/to/Pathfinder/app/core/state.py)
- [`app/api/routes.py`](/path/to/Pathfinder/app/api/routes.py)
- [`frontend/src/App.jsx`](/path/to/Pathfinder/frontend/src/App.jsx)
