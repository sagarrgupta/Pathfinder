# Pathfinder: Current System Architecture

> Single-source architecture reference for the Pathfinder codebase.
> Last updated: 2026-04-12

---

## 1. What Pathfinder Is

Pathfinder is a local-first advising runtime with:

- a FastAPI backend
- a React frontend
- a LangGraph chat workflow
- Neo4j as the durable profile, memory, and evidence store
- SQLite checkpointing for per-session continuity
- replay and evaluation support for completed turns

The current implementation supports:

- academic guidance and course/program questions
- career and internship guidance
- general profile and document-aware assistance
- document ingestion from chat and direct upload endpoints
- profile text ingestion
- saved recommendations and replay artifacts
- editable long-context notes that are passed into specialist turns

---

## 2. Current Architectural Shape

### Runtime shape

The live `/api/v1/chat` path is now a simplified MCP-first flow:

1. FastAPI accepts the request and validates uploads.
2. `build_chat_runtime_session()` assembles request metadata and dependency status.
3. `app/core/graph.py` compiles a 5-node LangGraph.
4. The graph runs:
   - `input_guard`
   - `orchestrator`
   - `specialist_runner`
   - `light_validator`
   - `responder`
5. The route streams progress events, token events, and a final `done` payload over SSE.
6. After the turn, Pathfinder persists a decision record and replay artifact on a best-effort basis.

### Main storage layers

- `Neo4j`: student profile, entities, documents, candidate facts, memory items, evidence links, recommendations
- `SQLite` via LangGraph `SqliteSaver`: per-session message/checkpoint continuity
- local filesystem: replay artifacts, generated data, eval fixtures

### Main integration points

- LM Studio text model
- LM Studio vision model
- Ollama embeddings
- web search provider chain
- MCP-style tool registry used by the specialist runner

---

## 3. High-Level Diagram

```text
Browser UI
  -> FastAPI routes
  -> Chat runtime session assembly
  -> LangGraph StateGraph
  -> input_guard
  -> orchestrator
  -> specialist_runner
  -> light_validator
  -> responder
  -> SSE stream back to UI

The runtime depends on:
  - Neo4j graph + memory store
  - SQLite conversation checkpoints
  - LM Studio text + vision inference
  - Ollama embeddings
  - web search adapters
  - replay / decision persistence
```

---

## 4. Runtime Decisions In The Current Code

| Area | Current implementation |
|---|---|
| Workflow engine | `langgraph.graph.StateGraph` |
| Shared state | `app/core/state.py::PathfinderState` |
| Checkpointing | LangGraph SQLite checkpointer in `app/core/memory.py` |
| Chat routing model | simplified 5-node MCP-first graph |
| Specialist selection | deterministic keyword/profile-signal routing in `app/agents/orchestrator.py` |
| Specialist execution | one selected specialist prompt family plus shared tool registry |
| Retrieval strategy label | `memory_pack` in `app/services/execution_registry.py` |
| Document ingestion | `app/agents/doc_analyst.py` plus PDF/image/DOCX extractors |
| Streaming | SSE from `POST /api/v1/chat` |
| External tool exposure | MCP server in `app/mcp_server.py` |

Important implementation notes:

- the current chat graph is not the older multi-branch 16-node workflow
- the retrieval strategy is still described as `memory_pack`, but the live turn consumes profile data, relevant memories, retrieved documents, and tool results through the selected specialist rather than a dedicated `build_memory_pack()` node
- profile memory consolidation is simplified and no longer exposes a dedicated conflict-resolution flow

---

## 5. LangGraph Workflow

The compiled graph in [`app/core/graph.py`](/path/to/Pathfinder/app/core/graph.py) currently registers exactly these nodes:

1. `input_guard`
2. `orchestrator`
3. `specialist_runner`
4. `light_validator`
5. `responder`

### Routing pattern

```text
input_guard
  -> responder           if blocked
  -> orchestrator        otherwise

orchestrator
  -> specialist_runner   normal path
  -> responder           short-circuit path

specialist_runner
  -> light_validator     normal path
  -> responder           short-circuit path

light_validator
  -> responder

responder
  -> END
```

### Design intent in the current code

- `input_guard` blocks unsafe/off-scope requests
- `orchestrator` selects one of three specialist families: `academic`, `career`, or `general`
- `specialist_runner` prepares compact profile/session context, optionally pre-ingests uploaded files, and lets the specialist call the canonical tool registry
- `light_validator` checks response shape, derives citations from tool provenance, and sets a lightweight confidence score
- `responder` returns the final answer with minimal rewriting

---

## 6. Shared State Model

The current `PathfinderState` is intentionally smaller than the older architecture drafts.

### Inputs and runtime controls

- `messages`
- `query`
- `files`
- `session_id`
- `student_id`
- `is_global_upload`
- `reasoning`
- `request_plan`

### Orchestration output

- `selected_specialist`
- `routing_scores`
- `routing_reason`
- `next_node`
- `session_summary`
- `dependency_status`
- `recovery_events`
- `stop_reason`
- `durable_profile_facts`

### Data gathered during the turn

- `profile_data`
- `retrieved_documents`
- `web_results`
- `semantic_memory`
- `latest_ingestion_result`
- `extracted_entities`
- `document_roles`
- `transcript_states`
- `tool_call_log`
- `specialist_output`

### Evaluation and output

- `draft_answer`
- `confidence_score`
- `is_grounded`
- `citations`
- `final_answer`
- `step_progress`

### Guard fields

- `is_blocked`
- `block_reason`
- `topic_guard_enabled`

This is a compact specialist-runtime state, not the older large workflow/planning state that included many intermediate advisor nodes.

---

## 7. Memory And Retrieval

### Conversation memory

- implemented with LangGraph checkpointing
- backed by SQLite
- keyed by `student_id:session_id` thread IDs

### Long-lived student memory

- stored in Neo4j
- includes profile entities, documents, candidate facts, memory items, evidence links, and recommendation state

### Live retrieval used by `/chat`

The current specialist path gathers context from:

- `get_full_profile(...)`
- `build_session_summary(...)`
- `get_relevant_memories(...)`
- `hybrid_search(...)`
- MCP-style tools invoked during specialist execution

The execution registry still exposes the retrieval strategy as `memory_pack`, but there is no dedicated live graph node named `build_memory_pack()` in the current `/chat` flow.

### Durable long context

The current profile/runtime bridge now exposes a shared long-context payload:

- a manifest of available entity/document groups
- small durable profile facts
- editable `long_context_notes`

This same payload is:

- shown on the profile page for inspection
- stored on the student record through `long_context_notes`
- passed into the specialist runner for live turns

Key modules:

- [`app/services/consolidation.py`](/path/to/Pathfinder/app/services/consolidation.py)
- [`app/services/long_context.py`](/path/to/Pathfinder/app/services/long_context.py)
- [`app/services/runtime_session.py`](/path/to/Pathfinder/app/services/runtime_session.py)
- [`app/agents/specialist_runner.py`](/path/to/Pathfinder/app/agents/specialist_runner.py)

---

## 8. Neo4j Responsibilities

Neo4j acts as the durable structured memory backbone.

Major responsibilities handled by [`app/adapters/neo4j/graph_store.py`](/path/to/Pathfinder/app/adapters/neo4j/graph_store.py):

- student creation and lookup
- full profile reads
- entity CRUD
- document storage and deletion
- candidate fact storage and student profile updates
- memory item persistence and evidence linking
- recommendation persistence and outcome tracking
- graph data export for visualization

The architecture is best described as:

- `Neo4j = profile store + evidence graph + memory ledger + recommendation state`

---

## 9. Document Ingestion

Pathfinder currently supports:

- PDF
- image
- DOCX
- free-text profile input

The ingestion path is split across:

- [`app/adapters/pdf/extractor.py`](/path/to/Pathfinder/app/adapters/pdf/extractor.py)
- [`app/agents/doc_analyst.py`](/path/to/Pathfinder/app/agents/doc_analyst.py)
- [`app/services/profile_text.py`](/path/to/Pathfinder/app/services/profile_text.py)

Current behavior:

- uploaded chat files are pre-ingested inside `specialist_runner`
- direct document uploads use the `/api/v1/documents` endpoint and call `doc_analyst` directly
- profile free text uses `/api/v1/profile/text`
- document/profile ingestion can trigger consolidation and candidate-fact cleanup

---

## 10. Web Search

The configured provider chain is:

1. Tavily
2. Google CSE
3. Brave
4. DuckDuckGo

Implemented through:

- [`app/services/execution_registry.py`](/path/to/Pathfinder/app/services/execution_registry.py)
- [`app/adapters/web_search/tavily.py`](/path/to/Pathfinder/app/adapters/web_search/tavily.py)
- [`app/adapters/web_search/google_cse.py`](/path/to/Pathfinder/app/adapters/web_search/google_cse.py)
- [`app/adapters/web_search/brave.py`](/path/to/Pathfinder/app/adapters/web_search/brave.py)
- [`app/adapters/web_search/duckduckgo.py`](/path/to/Pathfinder/app/adapters/web_search/duckduckgo.py)

---

## 11. API Surface

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

---

## 12. Frontend

The current router in [`frontend/src/App.jsx`](/path/to/Pathfinder/frontend/src/App.jsx) exposes:

- `/chat`
- `/profile`
- `/replays`
- `/settings`

Key pages:

- [`frontend/src/pages/ChatPage.jsx`](/path/to/Pathfinder/frontend/src/pages/ChatPage.jsx)
- [`frontend/src/pages/ProfilePage.jsx`](/path/to/Pathfinder/frontend/src/pages/ProfilePage.jsx)
- [`frontend/src/pages/ReplayPage.jsx`](/path/to/Pathfinder/frontend/src/pages/ReplayPage.jsx)
- [`frontend/src/pages/SettingsPage.jsx`](/path/to/Pathfinder/frontend/src/pages/SettingsPage.jsx)

The profile UI now also surfaces the long-context payload that is passed to specialists and lets the user edit the `long_context_notes` portion directly.

---

## 13. MCP Server

Pathfinder exposes an MCP server through [`app/mcp_server.py`](/path/to/Pathfinder/app/mcp_server.py).

At a high level it provides tools for:

- searching graph/profile context
- document and memory access
- saved recommendation inspection
- web/document retrieval helpers through the shared tool surface

This shared registry is also what the specialist runner uses internally during chat turns.

---

## 14. Quality And Guardrails

Current quality layers:

- `input_guard` for blocking and scope checks
- `orchestrator` for deterministic specialist routing
- `specialist_runner` for bounded tool-based reasoning
- `light_validator` for response-shape validation and citation extraction
- `responder` for final answer rendering

This is closer to:

- `guard + route + run specialist + validate + respond`

than the older:

- `guard + many preparation nodes + evaluator-heavy orchestration`

---

## 15. Current Project Structure

```text
app/
  api/                 FastAPI routes
  agents/              LangGraph node implementations
  adapters/            Neo4j, LLM, embeddings, PDF, web search adapters
  config/              runtime settings
  core/                graph assembly, shared state, memory, quality helpers
  schemas/             API request/response models
  services/            runtime helpers, consolidation, replay/eval, profile text
  tools/               canonical internal/MCP tool registry
  utils/               ids and misc helpers
  mcp_server.py        MCP server entrypoint
  main.py              FastAPI entrypoint

frontend/
  src/pages/           chat, profile, replays, settings
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

## 16. What This Document Assumes

This document intentionally describes the code as it exists now.

That means:

- the chat graph has 5 workflow nodes
- specialist routing is `academic` / `career` / `general`
- replay/eval and recommendation tracking are first-class parts of the system
- Neo4j acts as durable memory infrastructure
- the profile page exposes editable long-context notes that are fed into specialist turns

If the implementation changes again, update this file alongside:

- [`app/core/graph.py`](/path/to/Pathfinder/app/core/graph.py)
- [`app/core/state.py`](/path/to/Pathfinder/app/core/state.py)
- [`app/api/routes.py`](/path/to/Pathfinder/app/api/routes.py)
- [`app/agents/orchestrator.py`](/path/to/Pathfinder/app/agents/orchestrator.py)
- [`app/agents/specialist_runner.py`](/path/to/Pathfinder/app/agents/specialist_runner.py)
