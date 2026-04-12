# Pathfinder Architecture Flow

This document explains what happens in Pathfinder from the moment a user sends a query until the final streamed answer is returned.

It is intentionally layered:
- Start with the end-to-end flow
- Then inspect the LangGraph runtime
- Then drill into the major subflows
- Use the file references to jump into implementation details

Key implementation entry points:
- API entry: `app/main.py`
- Route handler: `app/api/routes.py`
- Runtime assembly: `app/services/runtime_session.py`
- Graph assembly: `app/core/graph.py`
- Shared state: `app/core/state.py`

## 1. End-to-End Request-to-Response Flow

```mermaid
flowchart TD
    U["User sends chat query<br/>Optional: files, session_id, student_id, advisor_mode"] --> API["FastAPI app<br/>app/main.py"]
    API --> ROUTE["POST /api/v1/chat<br/>app/api/routes.py::chat()"]

    ROUTE --> SID["Resolve student_id<br/>Create session_id if missing"]
    SID --> REPLACE{"replace_filenames provided?"}
    REPLACE -- Yes --> DELDOC["Find matching uploaded docs<br/>Delete old document graph + chunks"]
    REPLACE -- No --> FILES["Continue"]
    DELDOC --> FILES["Validate and read uploads"]

    FILES --> RUNTIME["Build ChatRuntimeSession<br/>app/services/runtime_session.py"]
    RUNTIME --> HEALTH["Capture dependency snapshot<br/>neo4j / llm / embeddings / web_search"]
    HEALTH --> PLANHINT["Build deterministic RequestPlan"]
    PLANHINT --> POLICY["Evaluate runtime preflight policy"]
    POLICY --> STATE["Build initial PathfinderState"]

    STATE --> GRAPH["Compile LangGraph with SQLite checkpointer<br/>app/core/graph.py"]
    GRAPH --> STREAM["Run graph.astream(initial_state, config)"]

    STREAM --> GUARD["1. input_guard"]
    GUARD --> BLOCK{"Blocked?"}
    BLOCK -- Yes --> RESPBLOCK["responder returns block_reason"]
    BLOCK -- No --> ORCH["2. orchestrator"]

    ORCH --> EXEC["Execute planned node sequence<br/>0..N data/preparation nodes<br/>1 advisory node<br/>evaluator<br/>responder"]

    EXEC --> FINALSTATE["Accumulate final_state as each node emits updates"]
    FINALSTATE --> TOKENS["Split final_answer into words<br/>Stream SSE token events"]
    TOKENS --> DONEPAYLOAD["Build done payload<br/>confidence, citations, trace, recovery, runtime snapshot"]
    DONEPAYLOAD --> PERSIST1["Persist decision record"]
    PERSIST1 --> PERSIST2["Build + save replay artifact"]
    PERSIST2 --> SSE["Send SSE done event"]
    RESPBLOCK --> SSE
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

    subgraph Agents
        G["input_guard"]
        O["orchestrator"]
        D["doc_analyst"]
        P["profile_manager"]
        W["web_researcher"]
        F["fact_extractor"]
        A1["academic_advisor"]
        A2["course_planner"]
        A3["program_advisor"]
        A4["career_matcher"]
        A5["eligibility_reasoner"]
        A6["career_planner"]
        A7["interview_prep"]
        E["evaluator"]
        R["responder"]
    end

    subgraph Data_and_Tools
        NEO["Neo4j graph store"]
        VEC["Neo4j vector index"]
        LLM["LM Studio / LLM adapters"]
        EMB["Embedding service"]
        WEB["Web search + URL fetch"]
        SQLITE["SQLite checkpointer"]
        REPLAY["Replay / decision persistence"]
    end

    UI --> MAIN --> ROUTER --> SESSION --> GRAPH
    GRAPH --> SQLITE
    GRAPH --> G --> O
    O --> D
    O --> P
    O --> W
    O --> F
    O --> A1
    O --> A2
    O --> A3
    O --> A4
    O --> A5
    O --> A6
    O --> A7
    D --> NEO
    D --> VEC
    D --> EMB
    D --> LLM
    P --> NEO
    P --> VEC
    W --> WEB
    W --> LLM
    F --> LLM
    A1 --> LLM
    A2 --> LLM
    A3 --> LLM
    A4 --> LLM
    A5 --> LLM
    A6 --> LLM
    A7 --> LLM
    A1 --> E
    A2 --> E
    A3 --> E
    A4 --> E
    A5 --> E
    A6 --> E
    A7 --> E
    E --> R --> REPLAY
```

## 3. LangGraph Execution Flow

This is the runtime graph defined in `app/core/graph.py`.

```mermaid
flowchart TD
    START["Graph entry"] --> IG["input_guard"]
    IG -->|blocked| RESP["responder"]
    IG -->|passed| ORCH["orchestrator"]

    ORCH --> CLAR["clarifier"]
    ORCH --> DOC["doc_analyst"]
    ORCH --> PROF["profile_manager"]
    ORCH --> WEB["web_researcher"]
    ORCH --> FACT["fact_extractor"]
    ORCH --> COURSE["course_planner"]
    ORCH --> PROGRAM["program_advisor"]
    ORCH --> CAREERMATCH["career_matcher"]
    ORCH --> ELIG["eligibility_reasoner"]
    ORCH --> ACAD["academic_advisor"]
    ORCH --> CAREERPLAN["career_planner"]
    ORCH --> INTERVIEW["interview_prep"]
    ORCH --> EVAL["evaluator"]
    ORCH --> RESP

    CLAR --> RESP

    DOC --> PROF
    DOC --> WEB
    DOC --> FACT
    DOC --> COURSE
    DOC --> PROGRAM
    DOC --> CAREERMATCH
    DOC --> ELIG
    DOC --> ACAD
    DOC --> CAREERPLAN
    DOC --> INTERVIEW
    DOC --> EVAL
    DOC --> RESP

    PROF --> WEB
    PROF --> FACT
    PROF --> COURSE
    PROF --> PROGRAM
    PROF --> CAREERMATCH
    PROF --> ELIG
    PROF --> ACAD
    PROF --> CAREERPLAN
    PROF --> INTERVIEW
    PROF --> EVAL
    PROF --> RESP

    WEB --> FACT
    WEB --> COURSE
    WEB --> PROGRAM
    WEB --> CAREERMATCH
    WEB --> ELIG
    WEB --> ACAD
    WEB --> CAREERPLAN
    WEB --> INTERVIEW
    WEB --> EVAL
    WEB --> RESP

    FACT --> COURSE
    FACT --> PROGRAM
    FACT --> CAREERMATCH
    FACT --> ACAD
    FACT --> CAREERPLAN
    FACT --> INTERVIEW
    FACT --> EVAL
    FACT --> RESP

    COURSE --> EVAL
    PROGRAM --> EVAL
    CAREERMATCH --> EVAL
    ELIG --> EVAL
    ACAD --> EVAL
    CAREERPLAN --> EVAL
    INTERVIEW --> EVAL

    EVAL --> RESP --> END["END"]
```

## 4. What Lives in `PathfinderState`

Every node reads and writes a shared state object defined in `app/core/state.py`.

```mermaid
flowchart TD
    subgraph Input_State
        I1["query"]
        I2["files"]
        I3["session_id"]
        I4["student_id"]
        I5["advisor_mode"]
        I6["request_plan"]
        I7["runtime_policy"]
    end

    subgraph Planning_State
        P1["intent"]
        P2["plan"]
        P3["next_node"]
        P4["workflow"]
        P5["target_entity"]
        P6["source_policy"]
        P7["task_graph"]
        P8["working_memory"]
    end

    subgraph Evidence_State
        E1["profile_data"]
        E2["retrieved_documents"]
        E3["web_results"]
        E4["semantic_memory"]
        E5["memory_pack"]
        E6["evidence_pack"]
        E7["document_roles"]
        E8["transcript_states"]
        E9["evidence_records"]
        E10["tool_call_log"]
    end

    subgraph Output_State
        O1["draft_answer"]
        O2["confidence_score"]
        O3["is_grounded"]
        O4["citations"]
        O5["final_answer"]
        O6["step_progress"]
        O7["trace_summary"]
        O8["stop_reason"]
    end
```

## 5. Detailed Flow: API Route + Runtime Session Setup

```mermaid
flowchart TD
    A["/chat request enters app/api/routes.py::chat()"] --> B["Resolve / create student profile id"]
    B --> C["Create session id if missing"]
    C --> D["Normalize uploaded files list"]
    D --> E{"replace_filenames set?"}
    E -- Yes --> F["For each filename:<br/>find_document_by_filename()<br/>delete_document_cascade()"]
    E -- No --> G["Skip replacement"]
    F --> H["Read uploaded files into memory"]
    G --> H
    H --> I["Validate file size / metadata"]
    I --> J["get_compiled_graph()"]
    J --> K["build_chat_runtime_session()"]
    K --> L["get_dependency_status()"]
    L --> M["build_request_plan()"]
    M --> N["evaluate_runtime_preflight()"]
    N --> O["Create RuntimeSnapshot + initial PathfinderState"]
    O --> P["graph.astream(initial_state, config)"]
    P --> Q["For each emitted node update:<br/>merge into final_state<br/>stream step_progress as SSE progress events"]
    Q --> R["After graph completes:<br/>read final_answer from final_state"]
    R --> S["Stream token events word-by-word"]
    S --> T["build_done_payload()"]
    T --> U["persist_decision_record()"]
    U --> V["build_replay_artifact() + save_replay_artifact()"]
    V --> W["Emit SSE done event"]
```

## 6. Detailed Flow: Deterministic Request Planner

This happens before the graph starts and gives the orchestrator a strong hint.

```mermaid
flowchart TD
    Q["Incoming query + uploaded files + advisor_mode"] --> G{"Greeting only?"}
    G -- Yes --> G1["Set workflow_hint=general_guidance<br/>skip_llm_routing=True"]
    G -- No --> P{"Looks like direct profile update?"}
    P -- Yes --> P1["Set intent_hint=profile<br/>workflow_hint=student_state_update<br/>plan_hint=[profile_manager]"]
    P -- No --> F{"Files attached?"}
    P1 --> F

    F -- Yes --> F1["Prepend doc_analyst to plan_hint"]
    F -- No --> U{"URL present?"}
    F1 --> F2{"Document-like request?"}
    F2 -- Yes --> F3["workflow_hint=document_guidance"]
    F2 -- No --> U
    F3 --> U

    U -- Yes --> U1["Prepend web_researcher to plan_hint"]
    U -- No --> M{"advisor_mode != adaptive?"}
    U1 --> U2{"URL-analysis language?"}
    U2 -- Yes --> U3["workflow_hint=document_guidance"]
    U2 -- No --> M
    U3 --> M

    M -- Yes --> M1["Use advisor-mode-specific workflow + fixed plan"]
    M -- No --> OUT["Return RequestPlan"]
    M1 --> M2["Set skip_llm_routing=True"]
    M2 --> OUT
    G1 --> OUT
```

## 7. Detailed Flow: Input Guard

```mermaid
flowchart TD
    IN["input_guard"] --> A{"Query empty?"}
    A -- Yes --> B["Block: Please enter a question"]
    A -- No --> C{"Length > 4000?"}
    C -- Yes --> D["Block: message too long"]
    C -- No --> E{"Prompt injection pattern matched?"}
    E -- Yes --> F["Block: unusual / injection-like message"]
    E -- No --> G{"Topic guard enabled?"}
    G -- No --> PASS["Pass"]
    G -- Yes --> H{"Has URL or uploaded file?"}
    H -- Yes --> PASS
    H -- No --> I{"Contains academic / career topic terms?"}
    I -- Yes --> PASS
    I -- No --> J["Block: off-topic query"]
```

## 8. Detailed Flow: Orchestrator

The orchestrator is the main traffic controller.

```mermaid
flowchart TD
    O0["orchestrator"] --> O1["Read query, files, student_id, messages, request_plan, advisor_mode"]
    O1 --> O2["Load existing student profile from Neo4j"]
    O2 --> O3["Build context summary:<br/>profile status<br/>files<br/>recent conversation<br/>URLs"]
    O3 --> O4["Infer:<br/>session_summary<br/>query_focus<br/>target_entity<br/>workflow<br/>source_policy<br/>short_memory_policy<br/>task_graph"]
    O4 --> O5{"skip_llm_routing?"}

    O5 -- Yes --> O6["Use deterministic intent + plan from request_plan/workflow"]
    O5 -- No --> O7{"workflow == general_guidance?"}
    O7 -- Yes --> O8["Call structured LLM to classify intent / plan / missing_info"]
    O7 -- No --> O9["Use deterministic workflow-derived plan"]

    O6 --> O10["Merge request_plan hints into plan"]
    O8 --> O10
    O9 --> O10

    O10 --> O11["Guardrails:<br/>insert profile_manager for personal queries<br/>insert/remove web_researcher based on policy<br/>ensure web_researcher before advisory nodes<br/>ensure profile_manager before advisory nodes<br/>force web_researcher for URL queries"]
    O11 --> O12["Apply runtime plan policies"]
    O12 --> O13{"Dependency gate triggered?"}
    O13 -- Yes --> O14["Mark blocked_reasons + recovery_events<br/>set next_node=responder"]
    O13 -- No --> O15["Set intent / plan / workflow / next_node"]
```

## 9. Detailed Flow: Document Ingestion Branch

This branch runs when files are attached or the planner routes to `doc_analyst`.

```mermaid
flowchart TD
    D0["doc_analyst"] --> D1{"Any files in state?"}
    D1 -- No --> DEND["Return unchanged"]
    D1 -- Yes --> D2["For each uploaded file"]

    D2 --> D3["Detect file type"]
    D3 --> D4{"Supported type?<br/>pdf / image / docx / text"}
    D4 -- No --> DSKIP["Skip unsupported file"]
    D4 -- Yes --> D5["execute_document_ingestion()"]

    D5 --> D6{"Text extraction succeeded?"}
    D6 -- No --> DERR1["Add recovery event<br/>skip file"]
    D6 -- Yes --> D7["Build plain_text / markdown_text / page records"]

    D7 --> D8{"Extracted text empty?"}
    D8 -- Yes --> DERR2["Add empty-extraction recovery event"]
    D8 -- No --> D9["Infer document role"]

    D9 --> D10{"Role == transcript?"}
    D10 -- Yes --> D11["Build transcript_state from extracted content"]
    D10 -- No --> D12["Continue"]
    D11 --> D12

    D12 --> D13["Store Document node in Neo4j"]
    D13 --> D14{"Transcript?"}
    D14 -- Yes --> D15["Store transcript_state as Evidence"]
    D14 -- No --> D16["Continue"]
    D15 --> D16

    D16 --> D17{"Docling structured chunks available?"}
    D17 -- Yes --> D18["Use structured chunks"]
    D17 -- No --> D19["Split text with RecursiveCharacterTextSplitter"]
    D18 --> D20["Generate embeddings"]
    D19 --> D20

    D20 --> D21{"Embedding/storage succeeded?"}
    D21 -- No --> DERR3["Store recovery event for chunk retrieval failure"]
    D21 -- Yes --> D22["Store chunks in Neo4j vector index"]

    D22 --> D23["Call LLM for entity extraction"]
    DERR3 --> D23
    D23 --> D24{"Parsed entities?"}
    D24 -- Yes --> D25["store_extracted_entities()"]
    D24 -- No --> DERR4["Add entity extraction recovery event"]
    D25 --> D26["Append extracted_entities/document_roles/transcript_states to state"]
    DERR4 --> D26

    D26 --> D27["Determine next_node from plan"]
```

## 10. Detailed Flow: Profile + Memory Retrieval Branch

This is one of the most important branches because many downstream agents depend on it.

```mermaid
flowchart TD
    P0["profile_manager"] --> P1["ensure_student(student_id)"]
    P1 --> P2{"Current query looks like profile signal?"}
    P2 -- Yes --> P3["ingest_memory(source=chat_query)"]
    P2 -- No --> P4["Skip in-turn ingestion"]
    P3 --> P5["Track candidate facts / memory items / promoted entities / student updates"]
    P4 --> P6["Load full profile from Neo4j"]
    P5 --> P6

    P6 --> P7["hybrid_search() over stored chunks"]
    P7 --> P8["build_memory_pack()<br/>semantic memory + conflicts + saved recommendations + decision records"]
    P8 --> P9["Fallback: if hybrid_search empty, use documents from memory_pack"]
    P9 --> P10["Derive session_summary, query_focus, workflow, target_entity"]
    P10 --> P11["Derive student_strategy / operating_model / recommendation_outcome_profile / decision_continuity"]
    P11 --> P12["Build / govern source_policy"]
    P12 --> P13["Pick primary transcript_state"]
    P13 --> P14["Generate targeted_web_questions for unresolved gaps"]
    P14 --> P15["build_evidence_pack()"]
    P15 --> P16["Add handoff note into working_memory"]
    P16 --> P17["Choose next_node based on plan"]
```

## 11. Detailed Flow: Web Research Branch

```mermaid
flowchart TD
    W0["web_researcher"] --> W1["Read query, profile, session_summary, source_policy, targeted_web_questions"]
    W1 --> W2["Infer preferred_domains / target_program / target_level / target_institution"]
    W2 --> W3["Start task_graph items for primary/secondary/live source retrieval"]
    W3 --> W4["Extract explicit URLs from user query"]
    W4 --> W5{"Any URLs?"}

    W5 -- Yes --> W6["Fetch URL content directly"]
    W6 --> W7["Record fetch results in tool_call_log"]
    W7 --> W8["Audit source trust/fit/freshness in working_memory"]
    W5 -- No --> W9["Skip direct fetch"]
    W8 --> W10["Generate smart search queries"]
    W9 --> W10

    W10 --> W11["Merge targeted questions"]
    W11 --> W12["Expand queries with domains and source policy"]
    W12 --> W13["Limit query count by policy"]
    W13 --> W14["Run search fallback chain for each query"]
    W14 --> W15["Score and dedupe results"]
    W15 --> W16["Choose strongest candidates"]
    W16 --> W17["Fetch full content for best hits within budget"]
    W17 --> W18["Classify sources / compute evidence tiers / reject weak or non-matching sources when policy requires"]
    W18 --> W19["Return web_results + tool_call_log + updated working_memory + next_node"]
```

## 12. Detailed Flow: Advisory Node Layer

Exactly one or more preparation nodes may run, but the plan usually converges to one domain-specific advisory node before evaluation.

```mermaid
flowchart TD
    PREP["Prepared state:<br/>profile_data<br/>retrieved_documents<br/>web_results<br/>semantic_memory<br/>evidence_pack"] --> PICK{"Which advisor is in plan?"}
    PICK --> ACAD["academic_advisor"]
    PICK --> COURSE["course_planner"]
    PICK --> PROGRAM["program_advisor"]
    PICK --> CM["career_matcher"]
    PICK --> ELIG["eligibility_reasoner"]
    PICK --> CP["career_planner"]
    PICK --> IP["interview_prep"]

    ACAD --> DRAFT["Produce draft_answer"]
    COURSE --> DRAFT
    PROGRAM --> DRAFT
    CM --> DRAFT
    ELIG --> DRAFT
    CP --> DRAFT
    IP --> DRAFT
```

### 12.1 Example Detailed Subflow: `academic_advisor`

```mermaid
flowchart TD
    A0["academic_advisor"] --> A1["Read query + profile + web_results + retrieved_documents"]
    A1 --> A2["Format profile / recent messages / web context / document excerpts"]
    A2 --> A3{"Course recommendation query?"}
    A3 -- No --> A6["Build full academic advisor prompt"]
    A3 -- Yes --> A4{"Enough course history or verified course sources?"}
    A4 -- No --> A5["Return clarification-oriented draft_answer"]
    A4 -- Yes --> A6

    A6 --> A7["run_advisor_tool_loop()<br/>fallback to direct LLM generation on failure"]
    A7 --> A8["strip_repetition()"]
    A8 --> A9{"Garbage output?"}
    A9 -- Yes --> A10["Discard answer"]
    A9 -- No --> A11["Set draft_answer and next_node=evaluator"]
    A10 --> A11
    A5 --> A11
```

## 13. Detailed Flow: Evaluator

The evaluator is the quality gate between reasoning and user-visible output.

```mermaid
flowchart TD
    E0["evaluator"] --> E1["Read draft_answer + evidence_pack + tool_call_log + decision_payload"]
    E1 --> E2{"Draft exists?"}
    E2 -- No --> E3["Set confidence=0<br/>is_grounded=False<br/>next_node=responder"]
    E2 -- Yes --> E4["Compile source text from documents, web, evidence records"]
    E4 --> E5["Call structured evaluator LLM"]
    E5 --> E6["Parse evaluation JSON:<br/>is_grounded<br/>confidence_score<br/>issues<br/>profile_updates<br/>disclaimer"]
    E6 --> E7["Validate structured decision payload against source evidence"]
    E7 --> E8["Compute issue severity + rewrite threshold"]
    E8 --> E9{"Severe issues or low confidence?"}
    E9 -- Yes --> E10["Attempt grounded rewrite"]
    E9 -- No --> E11{"Mild factual issues?"}
    E11 -- Yes --> E12["Patch mild issues"]
    E11 -- No --> E13{"Need disclaimer?"}
    E13 -- Yes --> E14["Append disclaimer"]
    E13 -- No --> E15["Keep draft"]

    E10 --> E16["Persist passive profile updates if detected"]
    E12 --> E16
    E14 --> E16
    E15 --> E16
    E3 --> E17["Return to responder"]
    E16 --> E18["Update trace_summary, blocked_reasons, stop_reason"]
    E18 --> E17
```

## 14. Detailed Flow: Responder

The responder decides whether to pass through a ready answer, synthesize one, or format a structured plan.

```mermaid
flowchart TD
    R0["responder"] --> R1{"Blocked by input_guard?"}
    R1 -- Yes --> R2["Return block_reason as final_answer"]
    R1 -- No --> R3{"stop_reason == dependency_unavailable?"}
    R3 -- Yes --> R4["Return dependency guidance"]
    R3 -- No --> R5{"final_answer already present and no draft?"}
    R5 -- Yes --> R6["Keep final_answer"]
    R5 -- No --> R7{"intent == document and no draft?"}
    R7 -- Yes --> R8["Build document-processing summary from entities/documents/profile"]
    R7 -- No --> R9["Merge citations with decision payload"]

    R9 --> R10{"decision_payload exists and no draft?"}
    R10 -- Yes --> R11["Render decision payload into structured answer"]
    R10 -- No --> R12{"Deterministic workflow with structured recommendations?"}
    R12 -- Yes --> R13["Render structured final answer directly"]
    R12 -- No --> R14{"intent == greeting?"}
    R14 -- Yes --> R15["Generate personalized greeting"]
    R14 -- No --> R16{"Draft missing?"}
    R16 -- Yes --> R17["Generate contextual answer from profile + docs + web context"]
    R16 -- No --> R18["Format/polish draft with formatter prompt"]

    R11 --> R19["Set final_answer + citations"]
    R13 --> R19
    R15 --> R19
    R17 --> R19
    R18 --> R19
    R2 --> R20["Return AI message"]
    R4 --> R20
    R6 --> R20
    R8 --> R20
    R19 --> R20
```

## 15. Persistence and Post-Response Artifacts

```mermaid
flowchart TD
    F["Graph finished"] --> D1["runtime_session.build_done_payload()"]
    D1 --> D2["Include:<br/>confidence<br/>citations<br/>method<br/>quality_path<br/>trace_summary<br/>blocked_reasons<br/>dependency_status<br/>recovery_events<br/>runtime_policy<br/>retrieval diagnostics<br/>document roles<br/>transcript states"]
    D2 --> D3["persist_decision_record()"]
    D3 --> D4["build_replay_artifact()"]
    D4 --> D5["save_replay_artifact()"]
    D5 --> D6["Attach replay_id to done payload"]
    D6 --> D7["Emit final SSE done event"]
```

## 16. Startup and Background Flow

This is not part of a single query, but it affects runtime behavior.

```mermaid
flowchart TD
    APP["FastAPI lifespan startup"] --> S1["Ensure SQLite data directory exists"]
    S1 --> S2["init_schema() for Neo4j"]
    S2 --> S3["ensure_vector_index()"]
    S3 --> S4["start_background_jobs()"]
    S4 --> READY["Pathfinder ready"]

    READY --> BG["Background consolidation loop"]
    BG --> BG1["Memory consolidation / cleanup / observability"]

    SHUT["App shutdown"] --> X1["stop_background_jobs()"]
    X1 --> X2["close_driver()"]
```

## 17. The Simplest Mental Model

If you want one sentence per stage, Pathfinder behaves like this:

1. The API route normalizes the request, files, student identity, and runtime settings.
2. The runtime session captures dependency health and builds deterministic planning hints.
3. The LangGraph state machine starts with safety validation.
4. The orchestrator decides what sequence of nodes is needed for this specific request.
5. Preparation nodes gather evidence from documents, profile memory, and the web.
6. One advisory node generates the first meaningful answer draft.
7. The evaluator checks whether that draft is grounded and good enough.
8. The responder turns the validated draft or structured payload into the final user-facing answer.
9. The route streams the answer back and stores replay/decision artifacts for debugging and evaluation.

## 18. File Map for Deeper Reading

- `app/main.py`
  FastAPI lifecycle, startup, shutdown, CORS, router registration.
- `app/api/routes.py`
  `/chat` SSE endpoint, upload handling, done payload persistence.
- `app/services/runtime_session.py`
  dependency checks, request planning, runtime snapshot, initial state, done payload.
- `app/services/request_planner.py`
  deterministic pre-routing for greetings, files, URLs, advisor modes, profile updates.
- `app/core/graph.py`
  LangGraph node registration and conditional routing.
- `app/core/state.py`
  the shared `PathfinderState` contract between all agents.
- `app/agents/input_guard.py`
  empty/length/injection/topic filtering.
- `app/agents/orchestrator.py`
  intent classification, workflow selection, plan shaping, dependency gating.
- `app/agents/doc_analyst.py`
  extraction, chunking, embeddings, entity extraction, transcript state generation.
- `app/agents/profile_manager.py`
  KG load, hybrid search, memory pack construction, student strategy derivation.
- `app/agents/web_researcher.py`
  URL fetch, query generation, web search, ranking, filtering, provenance logging.
- `app/agents/academic_advisor.py`
  example advisory node for academic guidance and tool-assisted drafting.
- `app/agents/evaluator.py`
  groundedness scoring, rewrite logic, issue handling, passive profile learning.
- `app/agents/responder.py`
  final formatting, structured rendering, fallback answer synthesis.
