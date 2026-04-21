# Pathfinder — Query Flow

This document traces what happens from the moment a user submits a query in the React UI until the streamed response is fully rendered. The flow covers the happy path, the blocked-query path, and the document upload sub-path.

---

## System at a Glance

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  React / Vite Frontend  (Vite dev server, port 5173)                            │
│                                                                                 │
│  ChatPage ──► InputArea ──POST /api/v1/chat──────────────────────────────────▶  │
│          ◄── SSE stream ── progress events ── token chunks ── done event ◄──    │
└─────────────────────────────────────────────────────────────────────────────────┘
                                     │
                    ┌────────────────▼─────────────────────┐
                    │  FastAPI  (Uvicorn, port 8001)        │
                    │  /api/v1/chat  →  event_stream()      │
                    └────────────────┬─────────────────────┘
                                     │
                    ┌────────────────▼─────────────────────┐
                    │  LangGraph  StateGraph                │
                    │                                       │
                    │  1. input_guard                       │
                    │  2. orchestrator                      │
                    │  3. query_ingestor                    │
                    │  4. specialist_runner  ◄── Doc Analyst│
                    │  5. response_validator                │
                    │  6. context_persister                 │
                    │  7. responder                         │
                    └────────────────┬─────────────────────┘
                                     │
          ┌──────────────────────────┼──────────────────────────┐
          │                          │                           │
   ┌──────▼──────┐          ┌────────▼───────┐        ┌─────────▼──────┐
   │  LM Studio  │          │     Neo4j      │        │    SQLite      │
   │  (port 1234)│          │  (port 7687)   │        │  Checkpointer  │
   │  Text LLM   │          │  Graph + Vector│        │  Chat history  │
   └─────────────┘          └────────────────┘        └────────────────┘
          │
   ┌──────▼──────┐
   │   Ollama    │
   │  (port 11434│
   │  Embeddings │
   └─────────────┘
```

---

## Phase 1 · HTTP Request (React → FastAPI)

**Endpoint:** `POST /api/v1/chat`  
**Content-Type:** `multipart/form-data`

The frontend sends the following fields:

| Field | Description |
|---|---|
| `query` | The user's text message (max 4,000 chars enforced later) |
| `session_id` | UUID identifying this conversation thread; auto-generated on first turn |
| `student_id` | Identifies which student's graph to operate on |
| `files` | Zero or more uploaded files (PDF, DOCX, PNG, JPG, HEIF — max 10 MB each) |
| `replace_filenames` | Comma-separated filenames to overwrite if they already exist in the graph |
| `reasoning` | LLM reasoning effort: `low`, `medium`, or `high` |

The API immediately returns a **Server-Sent Events (SSE) response** (`text/event-stream`) so the UI can display progress in real time while the backend works. The actual answer is not buffered and sent at the end — it is streamed as the last part of the SSE sequence.

---

## Phase 2 · FastAPI Setup (Before the Graph Runs)

Before handing control to LangGraph, the API layer performs several setup steps:

1. **Resolve student ID** — If a `student_id` was provided, it ensures the student node exists in Neo4j (creating it if needed). If none was provided, a new student ID is generated and the node is created.

2. **Handle document replacement** — If `replace_filenames` contains any filenames, the API looks up the existing document nodes for those filenames in Neo4j and deletes them (along with their chunks) before re-ingestion. This keeps the graph clean when a document is re-uploaded.

3. **Read uploaded files** — Each uploaded file is validated (extension check against the allowed list, size check against the 10 MB limit) and its raw bytes are read into memory as a `dict` with `{filename, content, size, content_type}`.

4. **Compile the LangGraph workflow** — The seven-node `StateGraph` is compiled with the SQLite checkpointer. The compiled graph is cached after the first run so it is not rebuilt on every request. The SQLite database lives at `data/pathfinder.db` (or a configured path) outside the OneDrive sync folder to avoid file-locking issues.

5. **Build initial state** — An initial `PathfinderState` dictionary is constructed with the query, files, IDs, reasoning level, and an empty `step_progress` list.

6. **Set LangGraph thread ID** — The `thread_id` passed to LangGraph is `"{student_id}:{session_id}"`. This is what the SQLite checkpointer uses to load and save conversation history, giving each student/session pair its own persistent message thread.

---

## Phase 3 · LangGraph Workflow (Seven Nodes)

LangGraph calls each node in sequence. Each node receives the full `PathfinderState`, makes changes, and returns an updated state. After each node completes, the API checks for new entries in `step_progress` and immediately emits a **progress SSE event** to the browser.

### PathfinderState — the shared data bag

Every node reads and writes this typed dictionary:

| Field group | Key fields |
|---|---|
| Input | `query`, `files`, `session_id`, `student_id`, `reasoning` |
| Guard | `is_blocked`, `block_reason`, `topic_guard_enabled` |
| Orchestrator output | `selected_specialist`, `routing_scores`, `routing_reason` |
| Query ingestor output | `latest_query_ingestion_result` (chat-message ingestion summary, graph updates, schema after) |
| Retrieved data | `session_context`, `long_context`, `student_schema`, `tool_call_log` |
| Specialist output | `specialist_output` (message, stop_reason, next contexts), `latest_ingestion_result` (document ingestion summary, when files attached) |
| Evaluated output | `citations`, `final_answer` |
| Progress | `step_progress` (list of stage/message dicts emitted as SSE) |
| LangGraph-managed | `messages` (full conversation history, accumulated across turns) |

---

### Node 1 — Input Guard

**File:** `app/nodes/input_guard.py`  
**Purpose:** Protect the system before doing any expensive LLM or database work.

The guard runs three sequential checks. If any check fails, it sets `is_blocked = True` and `block_reason` with a user-facing message, then exits early. The conditional edge in the workflow routes a blocked state directly to *Responder*, bypassing all other nodes.

| Check | What it looks for |
|---|---|
| Empty query | `query` is blank after stripping whitespace |
| Query too long | `len(query) > 4000` characters |
| Injection patterns | 9 regex patterns for SQL/Cypher injection (e.g. `UNION SELECT`, `DROP TABLE`, `OR 1=1`, `--` comments) |

The topic guard check (via `topic_guard_enabled` in state, defaulting to `True`) controls whether the injection patterns are applied. This can be toggled via the `/api/v1/settings` endpoint.

**On pass:** sets `is_blocked = False`, emits a progress event ("Checking your question"), and passes to Orchestrator.

---

### Node 2 — Orchestrator

**File:** `app/nodes/orchestrator.py`  
**Purpose:** Use the LLM as a lightweight classifier to route the query to the most relevant specialist.

#### Step-by-step:

1. **Fetch brief student profile** — Queries Neo4j for the student node and extracts the first four non-empty fields as a context hint (e.g. `"Profile: name=Sagar, program=CS, semester=3"`).

2. **Build a routing prompt** — Constructs a prompt listing the three specialist descriptions:
   - `academic` — degree records, grades, deadlines, enrollment, graduation requirements
   - `career` — job search, resume, skill assessment, professional development
   - `general` — profile questions, uploaded documents, greetings, cross-domain requests

3. **Call the LLM** — Sends the prompt to LM Studio (`get_text_llm("none")` — reasoning disabled for speed). The LLM returns a JSON object: `{"academic": 7, "career": 2, "general": 1}`.

4. **Parse scores** — The JSON is parsed with the project's robust `parse_json_object()` utility (handles malformed JSON, extra text, etc.). Scores are cast to `float`.

5. **Select specialist** — The highest-scoring specialist wins. Ties break toward `general`. If no specialist scores above 0 and the query matches a simple conversational pattern (hello, thanks, bye), `general` is selected.

6. **Emit progress** — Adds a progress entry: `"Choosing the best approach → Focusing on {specialist_label} for this question."` and returns the updated state with `selected_specialist`, `routing_scores`, and `routing_reason`.

**Fallback:** If the LLM call fails for any reason, the orchestrator falls back to `{"academic": 0, "career": 0, "general": 5.0}` — always routing to the general specialist without crashing the turn.

---

### Node 3 — Query Ingestor

**File:** `app/nodes/query_ingestor.py` (delegates to `app/utils/query_ingest.py`)  
**Purpose:** Opportunistically extend the student's knowledge graph with durable, novel information the student just disclosed in their chat message — *before* the specialist reads the graph to answer.

This node mirrors the document-ingestion loop but works on a single chat message rather than a file. It is intentionally biased toward NOT writing: the default outcome of any turn is no writes, and writes happen only when the message clearly carries useful info that is not already in the graph.

#### Step-by-step

1. **Skip-fast guards** — If `is_blocked` is True, or `student_id` / `query` is empty, the node returns immediately without doing any LLM work.

2. **Load the current schema** — `GraphDB.get_student_schema()` returns the canonical sections, entity types, relationship vocabulary, and counts so the agent can dedup against existing structure before writing.

3. **Build the prompt** — `QUERY_INGESTION_AGENT_SYSTEM_PROMPT` plus the user-prompt template, populated with the schema and the trimmed chat message (≤ 8 000 chars).

4. **Run the agentic loop** — Same shape as document ingestion, with the chat-ingester tool subset bound to the LLM via `get_agent_tool_schemas("query_ingestor")`. Up to 30 tool calls per round, up to 100 rounds, terminated by the model's final JSON.

5. **Decision system the agent must apply** (in order; stop on the first failure):
   - **Source test** — the message must be the student disclosing something about themselves, not asking a question or speaking hypothetically.
   - **Durability test** — the information must remain meaningful beyond this turn (transient mood / "what I want right now" fails).
   - **Specificity test** — concrete enough to encode as graph structure.
   - **Novelty test** — not already represented; the agent uses lookup tools to verify before writing.

6. **Persist the run** — Whether or not anything was written, the node records `latest_query_ingestion_result` with `model_summary` (`summary`, `saved_items`, `stop_reason ∈ {ingested, already_present, no_useful_info}`), `tool_call_log`, `graph_updates`, and `graph_schema_after`.

7. **Emit progress** — `"Saving helpful context → Looking for any new student details to remember."`

#### Tool surface (excludes vs the full registry)

The chat ingester is a graph-only writer — it has no document, so it cannot write chunks or attach grounding edges. It also cannot answer the user. Excluded from its view:

- All web tools (`search_web`, `fetch_url`, `find_official_sources`)
- `respond` (the specialist's terminal tool)
- All chunk write tools (`upsert_chunk`, `upsert_chunk_metadata`, `batch_upsert_chunks`)
- All grounding tools (`link_entity_to_chunk`, `link_entity_to_document`)
- All destructive / admin tools (`delete_chunk`, `delete_document_chunks`, `create_vector_index`, `vector_health_check`)
- Broad chunk retrieval (`get_chunks_for_student`)

Everything else — schema introspection, typed lookups, `hybrid_search` for dedup, and graph-write tools (`upsert_section`, `upsert_graph_node`, `upsert_graph_relation`, `upsert_entity_field`, `upsert_nested_field`, `update_student`) — is available.

#### Failure handling

If the agent loop raises, the failure is logged as a `processing_issues` entry with `type=query_ingestion_failed` and `status=degraded`. The workflow continues to the specialist, which still answers using the graph as it exists.

---

### Node 4 — Specialist Runner

**File:** `app/nodes/specialist_runner.py`  
**Purpose:** Gather information using tools and produce the answer. This is the most complex node and where the majority of the turn's compute time is spent.

#### 4a. Document ingestion (if files were uploaded)

If files are attached, the **Doc Analyst** sub-step runs before the main reasoning loop. See [Phase 3 · Doc Analyst Sub-Step](#doc-analyst-sub-step) below for the full breakdown.

#### 4b. Context assembly

Before the LLM loop begins, the runner assembles the context the specialist will see:

| Context piece | Source |
|---|---|
| `student_schema` | Neo4j — full graph manifest: sections, entity types, relationship vocabulary, counts |
| `student` profile | Neo4j — root student node properties |
| `session_context` | State — short text summary of what this session has been about so far |
| `long_context` | Neo4j — stored on the student node; durable summary that persists across sessions |
| `recent_messages` | State — the last 10 conversation turns (HumanMessage / AIMessage pairs) |

All of this is serialized to JSON and included in the HumanMessage sent to the LLM.

#### 4c. LLM binding and tool context

- The LLM is instantiated with the `reasoning` level from state (controls LM Studio's extended-thinking parameter).
- The **specialist's** subset of the tool registry is bound to the LLM via `llm.bind_tools(get_agent_tool_schemas("specialist"))`. The specialist is **read-only** against the graph: it has lookup, traversal, vector, web, and `respond` tools, but every graph- and chunk-write tool is excluded (those belong to the document and query ingesters that already ran). See [Per-agent tool surfaces](#per-agent-tool-surfaces) below.
- A `ToolContext` object is created holding the `student_id`, `session_id`, and a snapshot of the working state. Every tool handler receives this context so it knows which student's graph to operate on.

#### 4d. The agentic tool-use loop (up to 12 iterations)

```
messages = [SystemMessage(specialist_prompt), HumanMessage(query + context)]

for _ in range(12):
    ai_msg = await llm.ainvoke(messages)   # call LM Studio

    if ai_msg has tool_calls:
        for each tool_call (max 6 per round):
            result = await execute_tool(tool_name, args, tool_context)

            # Append compact result as ToolMessage for LLM to read
            messages.append(ToolMessage(...))

            # Log full result for replay artifact
            tool_call_log.append({call_id, tool, input, status, output, result_summary})

            if tool_name == "respond":
                # LLM signals it is done → capture final payload
                final_payload = result
                break  (with possible web-retry check)

        # If "respond" was not called in this round, loop again

    else:
        # LLM returned plain text instead of a tool call
        # Parse it as JSON; fall back to treating it as the message text
        final_payload = parse response text
        break
```

**Specialist system prompts** differ in focus:
- **Academic** — prioritize accuracy, verify against graph data and document chunks before answering, prefer official sources for institutional rules
- **Career** — prioritize actionable advice, connect to actual profile data to highlight real strengths/gaps, use web search to ground market claims
- **General** — flexible generalist; answer simple turns without tool calls, synthesize across domains for cross-cutting questions

All three specialists share the same base instruction set, including the tool escalation order (see below) and the required `respond` tool output format.

#### 4e. Tool escalation order (what the LLM is instructed to do)

1. Check the context blocks already in the prompt — if the answer is there, use it directly.
2. Use **graph lookup tools** for typed queries against the student's knowledge graph.
3. Use **`hybrid_search`** for semantic evidence retrieval over document chunks.
4. If local sources are insufficient, use **`search_web`** to find live/external information.
5. After a web search, use **`fetch_url`** to read the full content of the most promising result page.
6. If the first search doesn't yield the answer, try a **second `search_web`** with a rephrased query.
7. Call **`respond`** to deliver the final answer only after tool use is complete.

#### 4f. Tool catalog (full registry)

The catalog below lists every tool the system implements. Which tools a given LLM call actually sees is decided per-agent by `app/tools/tools.py::get_agent_tool_schemas(agent)` — see [Per-agent tool surfaces](#per-agent-tool-surfaces).

**Graph tools** (read/write Neo4j knowledge graph):

| Tool | Purpose |
|---|---|
| `get_student_schema` | Returns canonical sections, entity types, relationship vocabulary, and counts for this student's graph |
| `typed_node_lookup` | Returns entities of a specific type, with optional field filters |
| `typed_relation_lookup` | Returns entities connected via a specific relationship type |
| `fetch_relation_detail` | Fetches one specific relationship by type and target field value |
| `list_relationship_types` | Returns all relationship type names + counts present in the graph |
| `list_entity_types` | Returns all entity type names + counts |
| `get_section_entities` | Returns all entities under one section |
| `get_entity_by_identity` | Looks up one entity by its stable identity fields |
| `bfs_neighbors` | Traverses the graph outward from a node, level by level |
| `upsert_section` | Creates or updates a section (grouping container) |
| `upsert_graph_node` | Creates or updates one entity node in the graph |
| `upsert_graph_relation` | Creates or updates a typed edge between two entities |
| `upsert_entity_field` | Attaches a structured Field node to an entity (for complex sub-detail) |
| `upsert_nested_field` | Attaches a child Field to a parent Field (for deeper nesting) |
| `list_entity_fields` | Returns Field nodes attached to an entity |
| `link_entity_to_chunk` | Creates `(:Entity)-[:MENTIONED_IN]->(:Chunk)` provenance link |
| `link_entity_to_document` | Creates `(:Entity)-[:DERIVED_FROM]->(:Document)` provenance link |
| `get_chunk_entities` | Returns entities linked to a specific chunk |
| `update_student` | Updates root student node properties (name, summaries, preferences) |

**Vector tools** (read/write Neo4j vector index):

| Tool | Purpose |
|---|---|
| `hybrid_search` | Semantic similarity search over document chunks, enriched with graph entity context; returns chunks + related entities |
| `get_chunk` | Fetches one chunk by ID |
| `get_chunks_for_document` | Returns all chunks for a document |
| `get_chunks_for_student` | Returns all chunks across all documents for the student |
| `get_chunk_neighbors` | Returns a chunk with its immediate document context |
| `get_document_search_context` | Returns chunk summaries for a document in retrieval-friendly shape |
| `upsert_chunk` | Writes one chunk with auto-generated embedding |
| `batch_upsert_chunks` | Writes many chunks in one call (used during ingestion) |
| `delete_chunk` / `delete_document_chunks` | Chunk cleanup tools |

**Web tools** (external information):

| Tool | Purpose |
|---|---|
| `search_web` | Runs through a provider fallback chain: Tavily → Google CSE → Brave → DuckDuckGo (free, no key needed). Returns up to 10 results. |
| `fetch_url` | Fetches one URL and extracts readable text content (strips HTML, preserves structure) |
| `find_official_sources` | Like `search_web` but filters results to `.edu`, `.gov`, `.ac.`, and `official`/`catalog` domains |

**Utility tools:**

| Tool | Purpose |
|---|---|
| `respond` | The terminal tool — the LLM calls this with `{message, stop_reason, next_session_context, next_long_context}` to signal it is done |

#### 4g. Web-search safety net

After the LLM calls `respond`, the runner checks whether the answer says it couldn't find information despite not having fully exhausted web search. If both conditions are true (answer contains phrases like "couldn't find" / "not available", and fewer than 2 `search_web` or 2 `fetch_url` calls were made), the runner injects a nudge message and allows one additional loop iteration with a directive to rephrase the search and fetch a new URL. This retry is used at most once per turn.

#### Per-agent tool surfaces

The full tool registry is shared, but each LLM call sees only the subset appropriate for its role. Exclusions are declared in `app/tools/tools.py` and applied uniformly via `get_agent_tool_schemas(agent)` and `execute_agent_tool(agent, …)`.

| Agent | Role | Excluded tools | Why |
|---|---|---|---|
| `document_ingestor` | Build graph + grounding from a freshly-stored document | web tools, `respond`, all chunk-write tools, broad chunk fetch, admin/destructive tools | Chunks were already written by Doc Analyst; the agent's job is to read text and extend the graph |
| `query_ingestor` | Extend graph from a chat message (no document) | web tools, `respond`, all chunk-write tools, all grounding tools, broad chunk fetch, admin/destructive tools | No document or chunk exists for a chat message, so chunk-writing and chunk-grounding are out of scope |
| `specialist` | Read graph + web, then answer | every graph-write tool (`upsert_*`, `update_student`, `link_entity_to_*`), every chunk-write tool, admin/destructive tools | Ingestion already ran in earlier nodes; the specialist must remain read-only so it can't double-write or violate dedup |

---

### Doc Analyst Sub-Step

**File:** `app/nodes/doc_analyst.py`  
**Triggered by:** Files being present in state when Specialist Runner begins.

This sub-step runs as a synchronous call from within `specialist_runner` (not as a separate LangGraph node). It processes each uploaded file through a five-stage pipeline:

#### Stage 1 — Text Extraction

The extraction method depends on file type:

| File type | Extractor |
|---|---|
| PDF | PyMuPDF — page-by-page text extraction; falls back to vision LLM if a page has no selectable text (scanned page) |
| DOCX | `python-docx` — paragraph-level extraction |
| PNG / JPG / HEIF | Vision LLM (LM Studio) — `get_vision_llm()` describes the image content as text |

Each page is returned as `{page_number, text}`. All pages are joined into `full_text` with `\n\n` separators.

#### Stage 2 — Text Chunking

`RecursiveCharacterTextSplitter` splits `full_text` into overlapping chunks:
- Chunk size: **700 tokens** (configurable via `CHUNK_SIZE`)
- Chunk overlap: **120 tokens** (configurable via `CHUNK_OVERLAP`)
- Separators tried in order: `\n\n`, `\n`, `. `, ` `, `""` (character-level fallback)

A page locator function is built so each chunk can be mapped back to its source page number.

#### Stage 3 — Embedding

Chunk texts are sent in a batch to **Ollama** (`mxbai-embed-large`, 1024-dimensional vectors). Each chunk gets an embedding vector.

#### Stage 4 — Vector Storage

Chunks + embeddings are written to the Neo4j vector index (`chunk_embeddings`) via `VectorDB.batch_upsert_chunks()`. Each chunk node in Neo4j stores: `chunk_id`, `text`, `embedding`, `chunk_index`, `page_number`, and a link to its parent `Document` node.

A `Document` node for this file is also created in Neo4j and linked to the `Student` node at this step.

#### Stage 5 — LLM-Guided Graph Ingestion

The most important step: the document content is handed to a separate LLM call (`DOCUMENT_INGESTION_AGENT_SYSTEM_PROMPT`) that reads the full text, inspects the existing graph schema, and uses a subset of the graph/vector tool catalog to build out the student's knowledge graph.

The ingestion agent's mental model for graph structure:

```
Student
  └─ Section  (a named conceptual area, e.g. "Courses", "Work Experience")
       └─ Entity  (a distinct concept, e.g. a Course node with type "Course")
            ├─ properties  (direct scalar attributes: grade, credits, semester, GPA)
            └─ Field  (structured sub-detail for complex nested content)
                 └─ nested Field  (deeper structure within a field)

Evidence provenance:
  Entity ──MENTIONED_IN──▶ Chunk    (precise, chunk-level grounding)
  Entity ──DERIVED_FROM──▶ Document (broad, document-level grounding)

Relationships between entities:
  Entity ──<dynamic type>──▶ Entity  (semantic edges defined by the ingestion agent)
```

The ingestion agent is strongly instructed to:
- Batch multiple tool calls per round (5–10 parallel calls are expected)
- Exhaust the document before stopping (count items, verify extraction completeness)
- Create relationships between entities, not just flat node lists
- Ground every important entity back to a chunk via `link_entity_to_chunk`
- Reuse existing sections and entities rather than creating duplicates

After all tool calls finish, the agent returns a JSON summary (`{summary, key_takeaways, saved_items, stop_reason}`) which is stored in `latest_ingestion_result` in state.

#### Error handling

Each stage is wrapped in `try/except`. Failures are recorded as structured `processing_issues` entries with a type (`extraction_failed`, `embedding_failed`, `ingestion_failed`) and forwarded to the done event. A failed stage does not crash the turn — the specialist runner continues with whatever context was successfully prepared.

---

### Node 5 — Response Validator

**File:** `app/nodes/response_validator.py`  
**Purpose:** Validate the specialist's output and extract citations.

1. **Message validation** — If `specialist_output.message` is empty or missing, substitutes `"I could not generate a response."` rather than crashing.

2. **Citation extraction** — Scans through the full `tool_call_log`. For each tool call that succeeded (`status == "ok"`) and whose result summary contains a `title` or `url` field, a citation entry is added. Duplicates are removed. At most 8 citations are kept. These citations typically come from `search_web` and `fetch_url` results.

3. **State updates** — Writes `final_answer`, normalizes `specialist_output`, sets `citations`, and sets `stop_reason`.

4. Emits a progress event: `"Preparing your answer → Final checks on the response and sources."`

---

### Node 6 — Context Persister

**File:** `app/nodes/context_persister.py`  
**Purpose:** Write context updates back to the graph so they are available in future turns.

1. **Session context** — The specialist's `next_session_context` (a short summary of what this session is about) is written into state. It will be loaded by the next turn's Specialist Runner from the SQLite checkpointer via LangGraph's conversation history, or from state if within the same streaming call.

2. **Long-term context** — If the specialist produced a `next_long_context` (a durable summary of student facts like name, program, preferences, goals), it is written to the Neo4j `Student` node's `long_context` property via `GraphDB.update_student()`. This persists across sessions and is loaded at the start of every future specialist run.

3. Emits a progress event: `"Saving helpful context → Keeping useful details ready for future questions."`

---

### Node 7 — Responder

**File:** `app/nodes/responder.py`  
**Purpose:** Package the final answer and close the turn.

- If `is_blocked` is True, the `block_reason` is used as the final answer.
- Otherwise, `specialist_output.message` becomes `final_answer`.
- Appends an `AIMessage(content=final_answer)` to the `messages` list — this is what LangGraph persists to SQLite so the answer appears in conversation history on future turns.
- Emits the final progress event: `"Answer ready → Sharing the final response now."`

---

## Phase 4 · SSE Stream Delivery

After `graph.astream()` completes, the API sends three categories of SSE events in sequence:

### 1. Progress events (emitted throughout the run)

```
event: progress
data: {"stage": "Checking your question", "message": "Making sure everything looks good before I begin."}
```

Each node emits one or more of these as it runs. The UI renders them as status indicators above the final answer.

### 2. Token events (streamed final answer)

```
event: token
data: {"content": "Based on your transcript, you have completed..."}
```

The `final_answer` string is split into 120-character chunks (`_TOKEN_CHUNK_SIZE`) and emitted as a sequence of token events. The UI appends these chunks to progressively render the response as it arrives.

### 3. Done event (metadata + replay ID)

```
event: done
data: {
  "session_id": "...",
  "student_id": "...",
  "selected_specialist": "academic",
  "routing_scores": {"academic": 8, "career": 1, "general": 2},
  "routing_reason": "Selected academic via llm routing (score 8.0).",
  "citations": [{"title": "...", "url": "...", "tool": "search_web"}],
  "tool_call_log": [...],
  "specialist_output": {"message": "...", "stop_reason": "answered", ...},
  "session_context": "...",
  "long_context": "...",
  "document_ingestion": {...},
  "query_ingestion": {"summary": "...", "saved_items": [...], "stop_reason": "ingested|already_present|no_useful_info", "graph_updates": {...}, "graph_schema_after": {...}, "tool_call_log": [...]},
  "dependency_status": {"neo4j": "connected", "llm": "connected", ...},
  "runtime_snapshot": {"selected_text_model": "google/gemma-4-26b-a4b", ...},
  "replay_id": "rpl_..."
}
```

Just before sending the done event, the API saves a **replay artifact** — a complete JSON snapshot of the turn — to `data/replays/` on disk. The frontend receives the `replay_id` so the user can look up the turn later via `/api/v1/replays/{replay_id}`.

---

## Blocked Query Path

```
User query
    │
    ▼
FastAPI: resolve student, read files, build initial state
    │
    ▼
Node 1 — Input Guard: detects block condition
    │  (is_blocked = True, block_reason = "...")
    │
    │  Conditional edge: is_blocked → skip to responder
    ▼
Node 7 — Responder: final_answer = block_reason
    │
    ▼
SSE: progress event(s) + token events (block message) + done event
```

No LLM routing, no specialist, no tool calls. The turn completes in milliseconds.

---

## Document Upload Path (standalone `/api/v1/documents`)

The `/api/v1/documents` endpoint (separate from chat) lets files be uploaded outside a conversation turn. It runs the same `doc_analyst()` function directly — no LangGraph workflow, no LLM routing or specialist. The endpoint returns a `DocumentUploadResponse` with `{document_id, filename, entities_extracted, chunks_stored}` synchronously.

---

## Key Configuration Values

All settings are loaded from the `.env` file (or environment variables):

| Setting | Default | Purpose |
|---|---|---|
| `LLM_BASE_URL` | `http://localhost:1234/v1` | LM Studio OpenAI-compatible endpoint |
| `LLM_MODEL` | `google/gemma-4-26b-a4b` | Text LLM used for routing, specialist, and ingestion |
| `VISION_MODEL` | `google/gemma-4-26b-a4b` | Vision LLM for image/scanned-page extraction |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama embedding service |
| `EMBEDDING_MODEL` | `mxbai-embed-large` | Embedding model name |
| `EMBEDDING_DIMENSIONS` | `1024` | Must match actual model output dimensions |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j Bolt connection |
| `SQLITE_DB_PATH` | `data/pathfinder.db` | LangGraph conversation checkpointer |
| `CHUNK_SIZE` | `700` | Chars per text chunk during ingestion |
| `CHUNK_OVERLAP` | `120` | Overlap between consecutive chunks |
| `TOP_K` | `6` | Default number of chunks returned by vector search |
| `TOPIC_GUARD_ENABLED` | `True` | Whether injection pattern checks run |
| `MAX_FILE_SIZE_MB` | `10` | File upload size limit |
| `ALLOWED_FILE_TYPES` | `.pdf .png .jpg .jpeg .heif .heic .docx` | Accepted upload extensions |

---

## Neo4j Graph Schema (Key Node/Edge Types)

```
(:Student)
  ─[:HAS_SECTION]──▶ (:Section)
                        ─[:HAS_ENTITY]──▶ (:Entity:<DynamicType>)
                                            ─[:HAS_FIELD]──▶ (:Field)
                                                               ─[:HAS_FIELD]──▶ (:Field)
                                            ─[:MENTIONED_IN]──▶ (:Chunk)
                                            ─[:DERIVED_FROM]──▶ (:Document)
                                            ─[:<dynamic>]──▶ (:Entity:<DynamicType>)

(:Student) ─[:HAS_DOCUMENT]──▶ (:Document) ─[:HAS_CHUNK]──▶ (:Chunk)
(:Chunk) has a 1024-dimensional embedding vector stored on the node
         and is indexed by the Neo4j vector index "chunk_embeddings"
```

The `hybrid_search` tool combines vector similarity on `Chunk` nodes with graph traversal back to related `Entity` nodes, giving the LLM both raw text excerpts and structured graph context in a single query result.
