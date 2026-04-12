# Graph Report - .  (2026-04-11)

## Corpus Check
- 105 files · ~92,633 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1231 nodes · 2678 edges · 77 communities detected
- Extraction: 67% EXTRACTED · 33% INFERRED · 0% AMBIGUOUS · INFERRED: 886 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Quality Scoring Helpers|Quality Scoring Helpers]]
- [[_COMMUNITY_Academic Advisor|Academic Advisor]]
- [[_COMMUNITY_Neo4j Graph Store|Neo4j Graph Store]]
- [[_COMMUNITY_API Schemas|API Schemas]]
- [[_COMMUNITY_Backend Agent Architecture|Backend Agent Architecture]]
- [[_COMMUNITY_Request Planning Runtime|Request Planning Runtime]]
- [[_COMMUNITY_Retrieval Pipeline|Retrieval Pipeline]]
- [[_COMMUNITY_Course Planning Agent|Course Planning Agent]]
- [[_COMMUNITY_Advisor Runtime Helpers|Advisor Runtime Helpers]]
- [[_COMMUNITY_API Routes|API Routes]]
- [[_COMMUNITY_Memory Ingestion|Memory Ingestion]]
- [[_COMMUNITY_Frontend API Client|Frontend API Client]]
- [[_COMMUNITY_LM Studio Adapter|LM Studio Adapter]]
- [[_COMMUNITY_Runtime Recovery|Runtime Recovery]]
- [[_COMMUNITY_Profile Manager Agent|Profile Manager Agent]]
- [[_COMMUNITY_Transcript Parsing|Transcript Parsing]]
- [[_COMMUNITY_ID Generators|ID Generators]]
- [[_COMMUNITY_PDF Extraction Adapter|PDF Extraction Adapter]]
- [[_COMMUNITY_Execution Registry|Execution Registry]]
- [[_COMMUNITY_Eligibility Reasoner|Eligibility Reasoner]]
- [[_COMMUNITY_Neo4j Vector Search|Neo4j Vector Search]]
- [[_COMMUNITY_Program Advisor|Program Advisor]]
- [[_COMMUNITY_Career Matcher|Career Matcher]]
- [[_COMMUNITY_Conflict Consolidation|Conflict Consolidation]]
- [[_COMMUNITY_Background Jobs|Background Jobs]]
- [[_COMMUNITY_Replay Store|Replay Store]]
- [[_COMMUNITY_Profile Page|Profile Page]]
- [[_COMMUNITY_Orchestrator Planning|Orchestrator Planning]]
- [[_COMMUNITY_Conflict Semantics|Conflict Semantics]]
- [[_COMMUNITY_Eval Analytics|Eval Analytics]]
- [[_COMMUNITY_App Context State|App Context State]]
- [[_COMMUNITY_JSON Extract Utils|JSON Extract Utils]]
- [[_COMMUNITY_Conflict Auto Resolve|Conflict Auto Resolve]]
- [[_COMMUNITY_URL Fetcher|URL Fetcher]]
- [[_COMMUNITY_Replay Evaluation|Replay Evaluation]]
- [[_COMMUNITY_Replay Page|Replay Page]]
- [[_COMMUNITY_Checkpointer Memory|Checkpointer Memory]]
- [[_COMMUNITY_DuckDuckGo Search|DuckDuckGo Search]]
- [[_COMMUNITY_Document Role Inference|Document Role Inference]]
- [[_COMMUNITY_Decision Memory|Decision Memory]]
- [[_COMMUNITY_Error Boundary|Error Boundary]]
- [[_COMMUNITY_FastAPI Main|FastAPI Main]]
- [[_COMMUNITY_Settings Page|Settings Page]]
- [[_COMMUNITY_Settings Config|Settings Config]]
- [[_COMMUNITY_Tavily Search|Tavily Search]]
- [[_COMMUNITY_Search Fallback Chain|Search Fallback Chain]]
- [[_COMMUNITY_Google CSE Search|Google CSE Search]]
- [[_COMMUNITY_Ollama Embeddings|Ollama Embeddings]]
- [[_COMMUNITY_Message List|Message List]]
- [[_COMMUNITY_Message Component|Message Component]]
- [[_COMMUNITY_Toast Provider|Toast Provider]]
- [[_COMMUNITY_Profile Conflicts Page|Profile Conflicts Page]]
- [[_COMMUNITY_Chat Page|Chat Page]]
- [[_COMMUNITY_Prompt Registry|Prompt Registry]]
- [[_COMMUNITY_App Shell|App Shell]]
- [[_COMMUNITY_Input Area|Input Area]]
- [[_COMMUNITY_Streaming Progress|Streaming Progress]]
- [[_COMMUNITY_App Sidebar|App Sidebar]]
- [[_COMMUNITY_UI Utils|UI Utils]]
- [[_COMMUNITY_Graphify Setup Rules|Graphify Setup Rules]]
- [[_COMMUNITY_App Package Init|App Package Init]]
- [[_COMMUNITY_Core Package Init|Core Package Init]]
- [[_COMMUNITY_Config Package Init|Config Package Init]]
- [[_COMMUNITY_Agents Package Init|Agents Package Init]]
- [[_COMMUNITY_Utils Package Init|Utils Package Init]]
- [[_COMMUNITY_Schemas Package Init|Schemas Package Init]]
- [[_COMMUNITY_Adapters Package Init|Adapters Package Init]]
- [[_COMMUNITY_Neo4j Adapter Init|Neo4j Adapter Init]]
- [[_COMMUNITY_Web Search Init|Web Search Init]]
- [[_COMMUNITY_LLM Adapter Init|LLM Adapter Init]]
- [[_COMMUNITY_Embeddings Package Init|Embeddings Package Init]]
- [[_COMMUNITY_PDF Adapter Init|PDF Adapter Init]]
- [[_COMMUNITY_API Package Init|API Package Init]]
- [[_COMMUNITY_Tailwind Config|Tailwind Config]]
- [[_COMMUNITY_Vite Config|Vite Config]]
- [[_COMMUNITY_PostCSS Config|PostCSS Config]]
- [[_COMMUNITY_Frontend Entry Point|Frontend Entry Point]]

## God Nodes (most connected - your core abstractions)
1. `PathfinderState` - 102 edges
2. `ProfileTextInput` - 36 edges
3. `ProfileUpdate` - 36 edges
4. `EntityUpdate` - 36 edges
5. `ProfileCreate` - 36 edges
6. `ConflictChoiceRequest` - 36 edges
7. `SettingsUpdate` - 36 edges
8. `SavedRecommendationCreate` - 36 edges
9. `SavedRecommendationOutcomeUpdate` - 36 edges
10. `ChatResponse` - 36 edges

## Surprising Connections (you probably didn't know these)
- `Web Search and External Tools` --references--> `search()`  [EXTRACTED]
  how-to/web-search-and-tools.md → app/adapters/web_search/brave.py
- `Web Search Provider Chain` --conceptually_related_to--> `search()`  [EXTRACTED]
  how-to/web-search-and-tools.md → app/adapters/web_search/brave.py
- `Node 5: Profile Manager.  Handles all Neo4j knowledge graph interactions:   - Lo` --uses--> `PathfinderState`  [INFERRED]
  app/agents/profile_manager.py → app/core/state.py
- `Load profile, search documents, and enrich state with personal data.` --uses--> `PathfinderState`  [INFERRED]
  app/agents/profile_manager.py → app/core/state.py
- `Process free-text input from the My Profile page.      Extracts entities and sto` --uses--> `PathfinderState`  [INFERRED]
  app/agents/profile_manager.py → app/core/state.py

## Hyperedges (group relationships)
- **Local Agent Stack** — fastapi_backend, langgraph_workflow, neo4j_graph_memory, lm_studio, ollama_embeddings, react_frontend [EXTRACTED 1.00]
- **Web Search Toolchain** — web_search_provider_chain, tavily, google_cse, brave_search, duckduckgo [EXTRACTED 1.00]

## Communities

### Community 0 - "Quality Scoring Helpers"
Cohesion: 0.02
Nodes (146): _academic_level_scores(), academic_source_relevance(), add_handoff_note(), add_working_memory_item(), analyze_query_focus(), AnswerSupportRef, append_unique_text(), _application_targeting_signals() (+138 more)

### Community 1 - "Academic Advisor"
Cohesion: 0.02
Nodes (133): academic_advisor(), _format_documents(), _format_profile(), _format_recent_messages(), _format_web_results(), _has_live_schedule_sources(), _has_verified_course_sources(), _is_course_recommendation_query() (+125 more)

### Community 2 - "Neo4j Graph Store"
Cohesion: 0.04
Nodes (95): apply_conflict_choice(), _build_temporal_profile(), _candidate_confirmation_state(), _candidate_promotion_score(), _canonical_entity_key(), close_driver(), create_entity(), create_student() (+87 more)

### Community 3 - "API Schemas"
Cohesion: 0.23
Nodes (82): BaseModel, ChatRequest, ChatResponse, Citation, ConflictChoiceRequest, DocumentUploadResponse, EntityUpdate, EvalAnalyticsResponse (+74 more)

### Community 4 - "Backend Agent Architecture"
Cohesion: 0.07
Nodes (53): Agent Orchestration Tools, API Surface, Backend Service and Agent Graph, Brave Search adapter., Search using Brave Search API., search(), Client and UI Options, Docker for Local Services (+45 more)

### Community 5 - "Request Planning Runtime"
Cohesion: 0.07
Nodes (40): _advisor_mode_plan(), build_request_plan(), _is_greeting(), _is_profile_update(), _looks_like_document_request(), _looks_like_url_analysis(), _prepend_unique(), Deterministic request planning for obvious control-plane flows. (+32 more)

### Community 6 - "Retrieval Pipeline"
Cohesion: 0.1
Nodes (45): build_memory_pack(), _build_official_retry_query(), _build_personal_context(), _build_retrieval_diagnostics(), build_retrieval_plan(), _build_retrieval_trace(), _cache_get(), _cache_key() (+37 more)

### Community 7 - "Course Planning Agent"
Cohesion: 0.1
Nodes (39): _allowed_course_prefixes(), _build_recommendation_paths(), _build_semester_plan_options(), _code_allowed_for_program(), _compile_academic_program_model(), _course_code_from_profile_entity(), _course_outline_for_operating_model(), _course_outline_for_strategy() (+31 more)

### Community 8 - "Advisor Runtime Helpers"
Cohesion: 0.09
Nodes (37): finalize_structured_advisor(), _normalize_decision_payload(), _normalize_item_list(), _normalize_source_refs(), _normalize_string_list(), prepare_structured_advisor(), Shared runtime helpers for structured advisor nodes.  This module centralizes th, Apply common finalization logic for structured advisor nodes. (+29 more)

### Community 9 - "API Routes"
Cohesion: 0.09
Nodes (35): add_profile_text(), background_status(), chat(), check_document_exists(), create_profile(), delete_all_data_everywhere(), delete_profile_entity(), delete_session() (+27 more)

### Community 10 - "Memory Ingestion"
Cohesion: 0.14
Nodes (32): CandidateFactRecord, _classify_fact_stability(), _clean_candidate_value(), _clean_student_property(), _evidence_kind(), _expand_core_values(), _extract_memory_candidates(), _fact_preference_score() (+24 more)

### Community 11 - "Frontend API Client"
Cohesion: 0.09
Nodes (15): addProfileText(), autoResolveProfileConflicts(), checkDocumentExists(), deleteProfileEntity(), deleteSession(), evaluateRecentReplays(), getEvalAnalytics(), getProfile() (+7 more)

### Community 12 - "LM Studio Adapter"
Cohesion: 0.11
Nodes (21): ChatOpenAI, get_json_llm(), get_text_llm(), get_vision_llm(), is_garbage_output(), LoggingChatOpenAI, LM Studio LLM adapter.  Provides singleton ChatOpenAI instances for text and vis, Build a readable summary of the LLM input messages. (+13 more)

### Community 13 - "Runtime Recovery"
Cohesion: 0.13
Nodes (19): Structured recovery recipes for common Pathfinder runtime failures., Structured recovery event for one automatic degradation or escalation., Recovery event for document extraction failures., Recovery event for files that produced no usable extracted text., Recovery event for chunking/embedding storage failures., Recovery event for entity extraction failures during document analysis., Recovery event when retrieval produces very thin evidence., Return explicit recovery events for dependency-gated workflows. (+11 more)

### Community 14 - "Profile Manager Agent"
Cohesion: 0.16
Nodes (17): _determine_next(), _fallback_student_updates(), _govern_source_policy_from_profile(), _looks_like_semistructured_profile_blob(), process_free_text(), profile_manager(), Node 5: Profile Manager.  Handles all Neo4j knowledge graph interactions:   - Lo, Process free-text input from the My Profile page.      Extracts entities and sto (+9 more)

### Community 15 - "Transcript Parsing"
Cohesion: 0.18
Nodes (17): build_transcript_state(), _course_status(), _extract_courses(), _extract_cumulative_gpa(), _extract_latest_academic_standing(), _extract_milestones(), _extract_personal_info(), _extract_term_gpa() (+9 more)

### Community 16 - "ID Generators"
Cohesion: 0.12
Nodes (15): generate_chunk_id(), generate_document_id(), generate_evidence_id(), generate_memory_id(), generate_replay_id(), generate_session_id(), generate_student_id(), ID generation utilities. (+7 more)

### Community 17 - "PDF Extraction Adapter"
Cohesion: 0.14
Nodes (15): _convert_heif_to_jpeg(), _extract_page_with_vision(), extract_text_from_docx(), extract_text_from_image(), extract_text_from_pdf(), extract_text_from_plaintext(), get_file_type(), Document text extraction adapter.  Supports multiple file types with an adaptive (+7 more)

### Community 18 - "Execution Registry"
Cohesion: 0.19
Nodes (15): _document_ingestors(), execute_document_ingestion(), execute_web_search(), ExecutionRegistry, get_active_retrieval_strategy(), get_active_text_model(), get_active_vision_model(), get_execution_registry() (+7 more)

### Community 19 - "Eligibility Reasoner"
Cohesion: 0.27
Nodes (14): _build_eligibility_paths(), _dedupe_sequence(), _dedupe_source_refs(), _eligibility_goals(), _eligibility_next_step_for_strategy(), _eligibility_outline_for_operating_model(), _eligibility_outline_for_strategy(), eligibility_reasoner() (+6 more)

### Community 20 - "Neo4j Vector Search"
Cohesion: 0.17
Nodes (14): RuntimeError, EmbeddingServiceError, ensure_vector_index(), hybrid_search(), Neo4j vector store adapter.  Stores document chunks with embeddings and supports, Semantic similarity search over Chunk nodes.      Parameters     ----------, Combine vector similarity with graph context.      Returns vector search results, Lightweight entity-aware relevance tags for downstream planners. (+6 more)

### Community 21 - "Program Advisor"
Cohesion: 0.27
Nodes (13): _build_program_paths(), _dedupe_sequence(), _dedupe_source_refs(), _heuristic_program_payload(), _llm_program_payload(), _merge_payloads(), program_advisor(), _program_goals() (+5 more)

### Community 22 - "Career Matcher"
Cohesion: 0.27
Nodes (13): _build_career_paths(), _career_goals(), career_matcher(), _career_next_step_for_strategy(), _career_outline_for_operating_model(), _career_outline_for_strategy(), _dedupe_sequence(), _dedupe_source_refs() (+5 more)

### Community 23 - "Conflict Consolidation"
Cohesion: 0.29
Nodes (12): auto_resolve_profile_conflicts(), _fetch_candidate_facts(), _freshness_score(), list_profile_conflicts(), maybe_consolidate_memory(), _parse_datetimeish(), _rank_candidate(), Event-driven and periodic memory consolidation hooks. (+4 more)

### Community 24 - "Background Jobs"
Cohesion: 0.19
Nodes (12): _background_loop(), BackgroundStatus, consolidation_loop(), get_background_status(), Lightweight background jobs for Pathfinder., Start periodic background consolidation loop if not running., Stop periodic background loop cleanly., Return current background job status for observability. (+4 more)

### Community 25 - "Replay Store"
Cohesion: 0.23
Nodes (11): _artifact_dir(), build_replay_artifact(), get_replay_artifact(), list_replay_artifacts(), Replay artifact persistence for completed Pathfinder turns., Load a single replay artifact by ID., Build a compact replay artifact from a completed chat turn., Persist a replay artifact to disk as JSON. (+3 more)

### Community 26 - "Profile Page"
Cohesion: 0.2
Nodes (3): DynamicEntityTab(), getEntityConfig(), ProfilePage()

### Community 27 - "Orchestrator Planning"
Cohesion: 0.29
Nodes (8): _deterministic_intent_for_workflow(), _ensure_academic_fact_plan(), _ensure_quality_course_plan(), _merge_ordered_plan(), orchestrator(), _plan_for_workflow(), Node 2: Orchestrator.  Classifies user intent, checks what data is available, an, Classify intent and create an execution plan.

### Community 28 - "Conflict Semantics"
Cohesion: 0.36
Nodes (10): are_semantic_duplicates(), _contains_phrase(), normalize_fact_value(), normalize_text(), _preference_axes(), Shared helpers for distinguishing true conflicts from compatible facts., Separate incompatible clusters from facts that can safely coexist., semantic_tokens() (+2 more)

### Community 29 - "Eval Analytics"
Cohesion: 0.29
Nodes (8): _benchmark_dir(), build_eval_analytics(), _group_summary(), list_benchmark_sets(), Benchmark metadata and replay analytics for continuous evaluation., Build grouped replay analytics for continuous evaluation., Load benchmark-set metadata from checked-in JSON files., _trend_summary()

### Community 30 - "App Context State"
Cohesion: 0.27
Nodes (5): applyTheme(), appReducer(), generateRuntimeStudentId(), getOrCreateRuntimeStudentId(), getSystemTheme()

### Community 31 - "JSON Extract Utils"
Cohesion: 0.33
Nodes (8): _balanced_slice(), parse_json_array(), parse_json_object(), _parse_json_payload(), Utilities for robustly extracting JSON payloads from model output., Parse a JSON object from raw model output., Parse a JSON array from raw model output., _try_loads()

### Community 32 - "Conflict Auto Resolve"
Cohesion: 0.31
Nodes (8): auto_resolve_profile_conflicts(), _build_options(), list_profile_conflicts(), Conservative conflict helpers for profile-memory resolution., Return unresolved profile conflicts in UI-friendly shape., Apply a user-provided conflict choice and refresh conflict view., Run conservative auto-resolution and return summary., resolve_conflict_choice()

### Community 33 - "URL Fetcher"
Cohesion: 0.29
Nodes (7): _extract_text(), extract_urls(), fetch_url_content(), Direct URL content fetcher.  When the user provides a specific URL, this module, Extract readable text from a BeautifulSoup element.      Preserves paragraph str, Extract all URLs from a text string., Fetch a URL and extract its text content.      Returns a dict with title, url, c

### Community 34 - "Replay Evaluation"
Cohesion: 0.32
Nodes (7): evaluate_recent_replays(), evaluate_replay_artifact(), evaluate_replay_by_id(), Lightweight replay artifact evaluation for regression checks., Score a replay artifact using lightweight completeness and grounding heuristics., Load and evaluate one replay artifact., Evaluate a batch of recent replay artifacts.

### Community 35 - "Replay Page"
Cohesion: 0.52
Nodes (6): formatPercent(), formatPriority(), formatTime(), getEvalBadgeClass(), ReplayPage(), useReplayQueryParam()

### Community 36 - "Checkpointer Memory"
Cohesion: 0.33
Nodes (5): get_checkpointer(), Persistent conversation memory via LangGraph SqliteSaver.  Provides the checkpoi, Return the singleton SQLite checkpointer., Close checkpointer connection and remove persisted chat storage., reset_checkpointer_storage()

### Community 37 - "DuckDuckGo Search"
Cohesion: 0.33
Nodes (5): DuckDuckGo search adapter (free, no API key needed).  Uses the `ddgs` package (f, Run the synchronous DDGS text search., Search using DuckDuckGo (last resort, always available)., search(), _sync_search()

### Community 38 - "Document Role Inference"
Cohesion: 0.47
Nodes (5): _collect_signals(), infer_document_role(), Document role inference helpers.  Infers the semantic role of an uploaded docume, Infer a semantic document role from filename and extracted text., _role_score()

### Community 39 - "Decision Memory"
Cohesion: 0.4
Nodes (5): build_decision_record(), persist_decision_record(), Decision-memory persistence and continuity helpers., Build a structured decision record from a completed turn., Persist a structured decision record for future related conversations.

### Community 40 - "Error Boundary"
Cohesion: 0.33
Nodes (1): ErrorBoundary

### Community 41 - "FastAPI Main"
Cohesion: 0.4
Nodes (3): lifespan(), Pathfinder FastAPI application entry point., Startup and shutdown tasks.

### Community 42 - "Settings Page"
Cohesion: 0.4
Nodes (0): 

### Community 43 - "Settings Config"
Cohesion: 0.5
Nodes (3): BaseSettings, Pathfinder application settings.  All configuration is loaded from environment v, Settings

### Community 44 - "Tavily Search"
Cohesion: 0.5
Nodes (3): Tavily AI search adapter., Search using Tavily AI Search API., search()

### Community 45 - "Search Fallback Chain"
Cohesion: 0.5
Nodes (3): Web search fallback chain.  Tries search providers in order: Tavily -> Google CS, Search the web using the fallback chain.      Tries each provider in order and a, search()

### Community 46 - "Google CSE Search"
Cohesion: 0.5
Nodes (3): Google Custom Search Engine adapter., Search using Google Custom Search Engine API., search()

### Community 47 - "Ollama Embeddings"
Cohesion: 0.5
Nodes (3): get_embeddings(), Ollama embeddings adapter.  Provides a singleton OllamaEmbeddings instance for g, Return the singleton embeddings model (mxbai-embed-large).

### Community 48 - "Message List"
Cohesion: 0.5
Nodes (0): 

### Community 49 - "Message Component"
Cohesion: 0.67
Nodes (2): formatPriority(), Message()

### Community 50 - "Toast Provider"
Cohesion: 0.67
Nodes (0): 

### Community 51 - "Profile Conflicts Page"
Cohesion: 0.67
Nodes (0): 

### Community 52 - "Chat Page"
Cohesion: 0.67
Nodes (0): 

### Community 53 - "Prompt Registry"
Cohesion: 1.0
Nodes (1): Central prompt registry for Pathfinder agents and services.  All system/instruct

### Community 54 - "App Shell"
Cohesion: 1.0
Nodes (0): 

### Community 55 - "Input Area"
Cohesion: 1.0
Nodes (0): 

### Community 56 - "Streaming Progress"
Cohesion: 1.0
Nodes (0): 

### Community 57 - "App Sidebar"
Cohesion: 1.0
Nodes (0): 

### Community 58 - "UI Utils"
Cohesion: 1.0
Nodes (0): 

### Community 59 - "Graphify Setup Rules"
Cohesion: 1.0
Nodes (2): Graphify Rules, graphifyy

### Community 60 - "App Package Init"
Cohesion: 1.0
Nodes (0): 

### Community 61 - "Core Package Init"
Cohesion: 1.0
Nodes (0): 

### Community 62 - "Config Package Init"
Cohesion: 1.0
Nodes (0): 

### Community 63 - "Agents Package Init"
Cohesion: 1.0
Nodes (0): 

### Community 64 - "Utils Package Init"
Cohesion: 1.0
Nodes (0): 

### Community 65 - "Schemas Package Init"
Cohesion: 1.0
Nodes (0): 

### Community 66 - "Adapters Package Init"
Cohesion: 1.0
Nodes (0): 

### Community 67 - "Neo4j Adapter Init"
Cohesion: 1.0
Nodes (0): 

### Community 68 - "Web Search Init"
Cohesion: 1.0
Nodes (0): 

### Community 69 - "LLM Adapter Init"
Cohesion: 1.0
Nodes (0): 

### Community 70 - "Embeddings Package Init"
Cohesion: 1.0
Nodes (0): 

### Community 71 - "PDF Adapter Init"
Cohesion: 1.0
Nodes (0): 

### Community 72 - "API Package Init"
Cohesion: 1.0
Nodes (0): 

### Community 73 - "Tailwind Config"
Cohesion: 1.0
Nodes (0): 

### Community 74 - "Vite Config"
Cohesion: 1.0
Nodes (0): 

### Community 75 - "PostCSS Config"
Cohesion: 1.0
Nodes (0): 

### Community 76 - "Frontend Entry Point"
Cohesion: 1.0
Nodes (0): 

## Knowledge Gaps
- **272 isolated node(s):** `Pathfinder FastAPI application entry point.`, `Startup and shutdown tasks.`, `Pathfinder MCP Server.  Exposes Pathfinder tools via the Model Context Protocol`, `List available Pathfinder tools.`, `Execute a Pathfinder tool.` (+267 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Prompt Registry`** (2 nodes): `prompts.py`, `Central prompt registry for Pathfinder agents and services.  All system/instruct`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `App Shell`** (2 nodes): `App()`, `App.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Input Area`** (2 nodes): `InputArea.jsx`, `InputArea()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Streaming Progress`** (2 nodes): `StreamingProgress.jsx`, `StreamingProgress()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `App Sidebar`** (2 nodes): `Sidebar.jsx`, `Sidebar()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `UI Utils`** (2 nodes): `utils.js`, `cn()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Graphify Setup Rules`** (2 nodes): `Graphify Rules`, `graphifyy`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `App Package Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Core Package Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Config Package Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Agents Package Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Utils Package Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Schemas Package Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Adapters Package Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Neo4j Adapter Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Web Search Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `LLM Adapter Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Embeddings Package Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `PDF Adapter Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `API Package Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Tailwind Config`** (1 nodes): `tailwind.config.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Vite Config`** (1 nodes): `vite.config.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `PostCSS Config`** (1 nodes): `postcss.config.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Frontend Entry Point`** (1 nodes): `main.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `PathfinderState` connect `Academic Advisor` to `Quality Scoring Helpers`, `Course Planning Agent`, `Advisor Runtime Helpers`, `Profile Manager Agent`, `Eligibility Reasoner`, `Program Advisor`, `Career Matcher`, `Orchestrator Planning`?**
  _High betweenness centrality (0.082) - this node is a cross-community bridge._
- **Why does `DecisionPayload` connect `Advisor Runtime Helpers` to `Quality Scoring Helpers`, `Course Planning Agent`, `Eligibility Reasoner`, `Program Advisor`, `Career Matcher`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **Why does `Node: Course Planner.  Builds a structured decision payload for course-planning` connect `Course Planning Agent` to `Advisor Runtime Helpers`, `Academic Advisor`?**
  _High betweenness centrality (0.015) - this node is a cross-community bridge._
- **Are the 99 inferred relationships involving `PathfinderState` (e.g. with `LangGraph StateGraph assembly.  Builds the Pathfinder multi-agent graph with con` and `After Input Guard: if blocked, go to responder; else orchestrator.`) actually correct?**
  _`PathfinderState` has 99 INFERRED edges - model-reasoned connections that need verification._
- **Are the 33 inferred relationships involving `ProfileTextInput` (e.g. with `Main chat endpoint with SSE streaming.` and `List local student profiles.`) actually correct?**
  _`ProfileTextInput` has 33 INFERRED edges - model-reasoned connections that need verification._
- **Are the 33 inferred relationships involving `ProfileUpdate` (e.g. with `Main chat endpoint with SSE streaming.` and `List local student profiles.`) actually correct?**
  _`ProfileUpdate` has 33 INFERRED edges - model-reasoned connections that need verification._
- **Are the 33 inferred relationships involving `EntityUpdate` (e.g. with `Main chat endpoint with SSE streaming.` and `List local student profiles.`) actually correct?**
  _`EntityUpdate` has 33 INFERRED edges - model-reasoned connections that need verification._