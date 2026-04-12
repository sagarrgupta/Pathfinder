# Pathfinder Architecture Flow

This document describes the current live implementation of Pathfinder from request entry through final SSE output.

Key implementation entry points:

- API entry: `app/main.py`
- Route handler: `app/api/routes.py`
- Runtime assembly: `app/services/runtime_session.py`
- Graph assembly: `app/core/graph.py`
- Shared state: `app/core/state.py`
- Specialist execution: `app/agents/specialist_runner.py`

## 1. End-to-End Chat Flow

```mermaid
flowchart TD
    U["User sends chat query<br/>optional files, session_id, student_id"] --> API["FastAPI app<br/>app/main.py"]
    API --> ROUTE["POST /api/v1/chat<br/>app/api/routes.py::chat()"]

    ROUTE --> SID["Resolve student_id<br/>Create session_id if missing"]
    SID --> REPLACE{"replace_filenames provided?"}
    REPLACE -- Yes --> DELDOC["Find matching documents<br/>Cascade delete old document graph"]
    REPLACE -- No --> FILES["Continue"]
    DELDOC --> FILES["Validate and read uploads"]

    FILES --> RUNTIME["Build ChatRuntimeSession"]
    RUNTIME --> SNAP["Capture dependency snapshot<br/>neo4j / llm / embeddings / web_search"]
    SNAP --> INIT["Build initial PathfinderState"]
    INIT --> GRAPH["Compile 5-node LangGraph with SQLite checkpointer"]
    GRAPH --> STREAM["Run graph.astream(initial_state, config)"]

    STREAM --> IG["input_guard"]
    IG -->|blocked| RESPBLOCK["responder returns block_reason"]
    IG -->|passed| ORCH["orchestrator"]
    ORCH --> SPEC["specialist_runner"]
    SPEC --> VALID["light_validator"]
    VALID --> RESP["responder"]

    RESP --> FINALSTATE["Accumulate final_state"]
    RESPBLOCK --> FINALSTATE
    FINALSTATE --> TOKENS["Split final_answer into words<br/>emit SSE token events"]
    TOKENS --> DONE["Build done payload"]
    DONE --> DECISION["Best-effort persist decision record"]
    DECISION --> REPLAY["Best-effort persist replay artifact"]
    REPLAY --> SSE["Send SSE done event"]
```

## 2. Runtime Layers

```mermaid
flowchart LR
    subgraph Client
        UI["Frontend / caller"]
    end

    subgraph API
        MAIN["FastAPI app"]
        ROUTER["app/api/routes.py"]
    end

    subgraph Runtime
        SESSION["runtime_session.py"]
        GRAPH["core/graph.py"]
        STATE["core/state.py"]
    end

    subgraph Graph
        G["input_guard"]
        O["orchestrator"]
        S["specialist_runner"]
        V["light_validator"]
        R["responder"]
    end

    subgraph Data_and_Tools
        NEO["Neo4j profile + memory store"]
        VEC["Neo4j vector search"]
        LLM["LM Studio text / vision"]
        EMB["Ollama embeddings"]
        TOOLS["Canonical tool registry"]
        WEB["Web search adapters"]
        SQLITE["SQLite checkpointer"]
        REPLAY["Decision + replay persistence"]
    end

    UI --> MAIN --> ROUTER --> SESSION --> GRAPH
    GRAPH --> SQLITE
    GRAPH --> G --> O --> S --> V --> R
    S --> NEO
    S --> VEC
    S --> LLM
    S --> EMB
    S --> TOOLS
    TOOLS --> WEB
    R --> REPLAY
```

## 3. Current LangGraph Execution Flow

This is the runtime graph defined in `app/core/graph.py`.

```mermaid
flowchart TD
    START["Graph entry"] --> IG["input_guard"]
    IG -->|blocked| RESP["responder"]
    IG -->|passed| ORCH["orchestrator"]

    ORCH -->|normal path| SPEC["specialist_runner"]
    ORCH -->|short-circuit| RESP

    SPEC -->|normal path| VALID["light_validator"]
    SPEC -->|short-circuit| RESP

    VALID --> RESP
    RESP --> END["END"]
```

### What each node does

- `input_guard`
  - blocks unsafe or out-of-scope requests
  - sets `is_blocked` and `block_reason` when needed

- `orchestrator`
  - loads the current profile
  - builds a session summary
  - scores the query against `academic`, `career`, and `general`
  - stores the selected specialist and routing explanation

- `specialist_runner`
  - pre-ingests uploaded files by calling `doc_analyst` when files are present
  - refreshes profile context with `get_full_profile(...)`
  - loads semantic memories with `get_relevant_memories(...)`
  - runs vector retrieval with `hybrid_search(...)`
  - invokes the selected specialist prompt with shared MCP-style tools
  - records tool provenance in `tool_call_log`

- `light_validator`
  - normalizes the specialist output
  - derives citations from successful tool calls
  - assigns a lightweight confidence score

- `responder`
  - returns the block reason for blocked turns
  - otherwise returns `draft_answer` as `final_answer` with minimal rewriting

## 4. Request Assembly Before The Graph Starts

`build_chat_runtime_session()` does the pre-graph setup:

- records dependency status for:
  - Neo4j
  - text LLM
  - embeddings
  - web search configuration
- stores the selected retrieval strategy label as `memory_pack`
- builds the initial request plan:
  - `reasoning`
  - `has_files`
  - `has_url`
- builds the initial state consumed by the graph

This is intentionally deterministic and lightweight. Most of the actual reasoning happens inside the selected specialist.

## 5. Specialist Selection Flow

```mermaid
flowchart TD
    Q["Query + files + request_plan"] --> P["Load full profile"]
    P --> S["Build session_summary"]
    S --> SCORE["Score query against keyword families"]
    SCORE --> FILES{"Files attached?"}
    FILES -- Yes --> ADDG["Boost general score"]
    FILES -- No --> URLS{"URL in query?"}
    ADDG --> URLS
    URLS -- Yes --> ADDA["Boost academic and career scores"]
    URLS -- No --> PROFILE{"Profile signal present?"}
    ADDA --> PROFILE
    PROFILE -- Yes --> ADDP["Boost general score"]
    PROFILE -- No --> PICK["Pick highest score"]
    ADDP --> PICK
    PICK --> OUT["Store selected_specialist<br/>routing_scores<br/>routing_reason"]
```

The current specialist families are:

- `academic`
- `career`
- `general`

There is no longer a live graph branch that routes across many advisor nodes such as `profile_manager`, `web_researcher`, `academic_advisor`, or `evaluator`.

## 6. Specialist Execution Flow

```mermaid
flowchart TD
    S0["specialist_runner"] --> F{"Uploaded files present?"}
    F -- Yes --> D["Call doc_analyst first"]
    F -- No --> P["Skip doc pre-ingestion"]
    D --> P

    P --> P1["Reload full profile"]
    P1 --> P2["Build session_summary"]
    P2 --> P3["Load relevant semantic memories"]
    P3 --> P4["Run hybrid_search() for retrieved_documents"]
    P4 --> P5["Assemble short_context and long_context"]
    P5 --> P6["Bind shared tool schemas to LLM"]
    P6 --> P7["Run selected specialist prompt"]
    P7 --> TOOLS{"Tool calls returned?"}

    TOOLS -- Yes --> T1["Execute tool through canonical registry"]
    T1 --> T2["Append compact tool result to tool_call_log"]
    T2 --> P7

    TOOLS -- No --> OUT["Parse final payload<br/>store draft_answer and specialist_output"]
```

Important implementation details:

- the specialist gets compact profile/session context, not the entire raw database payload
- the specialist can call tools for graph, memory, document, and web access
- retrieved documents and semantic memories are loaded before tool use begins
- uploaded file processing happens inside this node, not as a separate graph branch

## 7. Validation And Response Flow

```mermaid
flowchart TD
    V0["light_validator"] --> V1["Read specialist_output or draft_answer"]
    V1 --> V2["Extract citations from successful tool_call_log items"]
    V2 --> V3{"Any successful tools?"}
    V3 -- Yes --> V4["confidence = 0.82"]
    V3 -- No --> V5{"stop_reason == stop?"}
    V5 -- Yes --> V6["confidence = 0.9"]
    V5 -- No --> V7["confidence = 0.62"]
    V4 --> V8["Set is_grounded and next_node=responder"]
    V6 --> V8
    V7 --> V8
    V8 --> R0["responder"]
    R0 --> R1{"Blocked?"}
    R1 -- Yes --> R2["Return block_reason"]
    R1 -- No --> R3["Return final_answer from draft_answer"]
```

## 8. Persistence After The Graph Finishes

After graph execution finishes inside `app/api/routes.py::chat()`:

1. progress messages are emitted as SSE `progress` events
2. the final answer is split into word-level SSE `token` events
3. `build_done_payload(...)` creates the terminal metadata payload
4. `persist_decision_record(...)` runs on a best-effort basis
5. a replay artifact is built and saved on a best-effort basis
6. the route emits a final SSE `done` event

Failures in decision-record or replay persistence are logged, but they do not fail the user-facing answer after the turn has already completed.

## 9. Long Context And Profile Memory

The profile/runtime bridge now centers on a shared long-context payload.

### What is included

The payload built by `app/services/long_context.py` includes:

- a manifest of graph entity types and document groups
- compact durable profile facts such as institution, program, semester, goals, and preferences
- editable `long_context_notes`

### Where it is used

- `specialist_runner` passes this payload into the selected specialist
- the replay artifact stores the payload so a turn can be inspected later
- the profile page shows a preview of the payload and lets the user edit `long_context_notes`

### Consolidation behavior

Consolidation still runs after:

- `POST /api/v1/profile/text`
- `POST /api/v1/documents`
- background consolidation scans

But the current implementation no longer exposes a separate profile-conflict API/UI flow. Instead, consolidation prefers the strongest supported fact and supersedes weaker conflicting candidates.

## 10. API Surface Relevant To Flow

### Chat runtime

- `POST /api/v1/chat`

### Direct ingestion

- `GET /api/v1/documents/check`
- `POST /api/v1/documents`
- `POST /api/v1/profile/text`

### Replay and evaluation

- `GET /api/v1/replays`
- `GET /api/v1/replays/{replay_id}`
- `GET /api/v1/replays/{replay_id}/evaluate`
- `GET /api/v1/replays/evaluate/recent`
- `GET /api/v1/eval/benchmarks`
- `GET /api/v1/eval/analytics`

## 11. Source Files To Read Next

For the current live implementation, start here:

- `app/api/routes.py`
- `app/services/runtime_session.py`
- `app/core/graph.py`
- `app/core/state.py`
- `app/agents/input_guard.py`
- `app/agents/orchestrator.py`
- `app/agents/specialist_runner.py`
- `app/agents/light_validator.py`
- `app/agents/responder.py`
- `app/services/consolidation.py`
- `app/services/long_context.py`
