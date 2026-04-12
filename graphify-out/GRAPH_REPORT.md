# Graph Report - .  (2026-04-11)

## Corpus Check
- 94 files · ~95,034 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1252 nodes · 2723 edges · 77 communities detected
- Extraction: 67% EXTRACTED · 33% INFERRED · 0% AMBIGUOUS · INFERRED: 896 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 74|Community 74]]
- [[_COMMUNITY_Community 75|Community 75]]
- [[_COMMUNITY_Community 76|Community 76]]

## God Nodes (most connected - your core abstractions)
1. `PathfinderState` - 103 edges
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
- `LangGraph StateGraph assembly.  Builds the Pathfinder multi-agent graph with con` --uses--> `PathfinderState`  [INFERRED]
  app/core/graph.py → app/core/state.py
- `After Input Guard: if blocked, go to responder; else orchestrator.` --uses--> `PathfinderState`  [INFERRED]
  app/core/graph.py → app/core/state.py
- `After Orchestrator: route to the first node in the plan.` --uses--> `PathfinderState`  [INFERRED]
  app/core/graph.py → app/core/state.py
- `Generic routing: follow the next_node set by the previous agent.` --uses--> `PathfinderState`  [INFERRED]
  app/core/graph.py → app/core/state.py
- `Build and return the Pathfinder StateGraph (uncompiled).` --uses--> `PathfinderState`  [INFERRED]
  app/core/graph.py → app/core/state.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.02
Nodes (146): _academic_level_scores(), academic_source_relevance(), add_handoff_note(), add_working_memory_item(), analyze_query_focus(), AnswerSupportRef, append_unique_text(), _application_targeting_signals() (+138 more)

### Community 1 - "Community 1"
Cohesion: 0.02
Nodes (137): academic_advisor(), _format_documents(), _format_profile(), _format_recent_messages(), _format_web_results(), _has_live_schedule_sources(), _has_verified_course_sources(), _is_course_recommendation_query() (+129 more)

### Community 2 - "Community 2"
Cohesion: 0.04
Nodes (95): apply_conflict_choice(), _build_temporal_profile(), _candidate_confirmation_state(), _candidate_promotion_score(), _canonical_entity_key(), close_driver(), create_entity(), create_student() (+87 more)

### Community 3 - "Community 3"
Cohesion: 0.23
Nodes (82): BaseModel, ChatRequest, ChatResponse, Citation, ConflictChoiceRequest, DocumentUploadResponse, EntityUpdate, EvalAnalyticsResponse (+74 more)

### Community 4 - "Community 4"
Cohesion: 0.07
Nodes (50): finalize_structured_advisor(), _normalize_decision_payload(), _normalize_item_list(), _normalize_source_refs(), _normalize_string_list(), prepare_structured_advisor(), Shared runtime helpers for structured advisor nodes.  This module centralizes th, Apply common finalization logic for structured advisor nodes. (+42 more)

### Community 5 - "Community 5"
Cohesion: 0.07
Nodes (40): _advisor_mode_plan(), build_request_plan(), _is_greeting(), _is_profile_update(), _looks_like_document_request(), _looks_like_url_analysis(), _prepend_unique(), Deterministic request planning for obvious control-plane flows. (+32 more)

### Community 6 - "Community 6"
Cohesion: 0.1
Nodes (45): build_memory_pack(), _build_official_retry_query(), _build_personal_context(), _build_retrieval_diagnostics(), build_retrieval_plan(), _build_retrieval_trace(), _cache_get(), _cache_key() (+37 more)

### Community 7 - "Community 7"
Cohesion: 0.11
Nodes (45): _document_citations_from_state(), error_envelope(), execute_pathfinder_tool(), _handle_analyze_document_text(), _handle_fetch_url(), _handle_get_career_alignment_context(), _handle_get_course_history(), _handle_get_dependency_status() (+37 more)

### Community 8 - "Community 8"
Cohesion: 0.1
Nodes (39): _allowed_course_prefixes(), _build_recommendation_paths(), _build_semester_plan_options(), _code_allowed_for_program(), _compile_academic_program_model(), _course_code_from_profile_entity(), _course_outline_for_operating_model(), _course_outline_for_strategy() (+31 more)

### Community 9 - "Community 9"
Cohesion: 0.08
Nodes (31): InternalMCPClient, Internal Pathfinder MCP client used by the in-app orchestration runtime., Lightweight adapter over the canonical Pathfinder MCP tool registry., Build tool execution context., Return all registered tool descriptors., Execute one tool and return the canonical envelope., Return OpenAI-style schemas for tool calling., _build_mcp_system_prompt() (+23 more)

### Community 10 - "Community 10"
Cohesion: 0.09
Nodes (35): add_profile_text(), background_status(), chat(), check_document_exists(), create_profile(), delete_all_data_everywhere(), delete_profile_entity(), delete_session() (+27 more)

### Community 11 - "Community 11"
Cohesion: 0.14
Nodes (32): CandidateFactRecord, _classify_fact_stability(), _clean_candidate_value(), _clean_student_property(), _evidence_kind(), _expand_core_values(), _extract_memory_candidates(), _fact_preference_score() (+24 more)

### Community 12 - "Community 12"
Cohesion: 0.09
Nodes (15): addProfileText(), autoResolveProfileConflicts(), checkDocumentExists(), deleteProfileEntity(), deleteSession(), evaluateRecentReplays(), getEvalAnalytics(), getProfile() (+7 more)

### Community 13 - "Community 13"
Cohesion: 0.11
Nodes (21): ChatOpenAI, get_json_llm(), get_text_llm(), get_vision_llm(), is_garbage_output(), LoggingChatOpenAI, LM Studio LLM adapter.  Provides singleton ChatOpenAI instances for text and vis, Build a readable summary of the LLM input messages. (+13 more)

### Community 14 - "Community 14"
Cohesion: 0.13
Nodes (19): Structured recovery recipes for common Pathfinder runtime failures., Structured recovery event for one automatic degradation or escalation., Recovery event for document extraction failures., Recovery event for files that produced no usable extracted text., Recovery event for chunking/embedding storage failures., Recovery event for entity extraction failures during document analysis., Recovery event when retrieval produces very thin evidence., Return explicit recovery events for dependency-gated workflows. (+11 more)

### Community 15 - "Community 15"
Cohesion: 0.18
Nodes (17): build_transcript_state(), _course_status(), _extract_courses(), _extract_cumulative_gpa(), _extract_latest_academic_standing(), _extract_milestones(), _extract_personal_info(), _extract_term_gpa() (+9 more)

### Community 16 - "Community 16"
Cohesion: 0.12
Nodes (15): generate_chunk_id(), generate_document_id(), generate_evidence_id(), generate_memory_id(), generate_replay_id(), generate_session_id(), generate_student_id(), ID generation utilities. (+7 more)

### Community 17 - "Community 17"
Cohesion: 0.14
Nodes (15): _convert_heif_to_jpeg(), _extract_page_with_vision(), extract_text_from_docx(), extract_text_from_image(), extract_text_from_pdf(), extract_text_from_plaintext(), get_file_type(), Document text extraction adapter.  Supports multiple file types with an adaptive (+7 more)

### Community 18 - "Community 18"
Cohesion: 0.19
Nodes (15): _document_ingestors(), execute_document_ingestion(), execute_web_search(), ExecutionRegistry, get_active_retrieval_strategy(), get_active_text_model(), get_active_vision_model(), get_execution_registry() (+7 more)

### Community 19 - "Community 19"
Cohesion: 0.27
Nodes (14): _build_eligibility_paths(), _dedupe_sequence(), _dedupe_source_refs(), _eligibility_goals(), _eligibility_next_step_for_strategy(), _eligibility_outline_for_operating_model(), _eligibility_outline_for_strategy(), eligibility_reasoner() (+6 more)

### Community 20 - "Community 20"
Cohesion: 0.17
Nodes (14): RuntimeError, EmbeddingServiceError, ensure_vector_index(), hybrid_search(), Neo4j vector store adapter.  Stores document chunks with embeddings and supports, Semantic similarity search over Chunk nodes.      Parameters     ----------, Combine vector similarity with graph context.      Returns vector search results, Lightweight entity-aware relevance tags for downstream planners. (+6 more)

### Community 21 - "Community 21"
Cohesion: 0.27
Nodes (13): _build_career_paths(), _career_goals(), career_matcher(), _career_next_step_for_strategy(), _career_outline_for_operating_model(), _career_outline_for_strategy(), _dedupe_sequence(), _dedupe_source_refs() (+5 more)

### Community 22 - "Community 22"
Cohesion: 0.29
Nodes (12): auto_resolve_profile_conflicts(), _fetch_candidate_facts(), _freshness_score(), list_profile_conflicts(), maybe_consolidate_memory(), _parse_datetimeish(), _rank_candidate(), Event-driven and periodic memory consolidation hooks. (+4 more)

### Community 23 - "Community 23"
Cohesion: 0.19
Nodes (12): _background_loop(), BackgroundStatus, consolidation_loop(), get_background_status(), Lightweight background jobs for Pathfinder., Start periodic background consolidation loop if not running., Stop periodic background loop cleanly., Return current background job status for observability. (+4 more)

### Community 24 - "Community 24"
Cohesion: 0.23
Nodes (11): _artifact_dir(), build_replay_artifact(), get_replay_artifact(), list_replay_artifacts(), Replay artifact persistence for completed Pathfinder turns., Load a single replay artifact by ID., Build a compact replay artifact from a completed chat turn., Persist a replay artifact to disk as JSON. (+3 more)

### Community 25 - "Community 25"
Cohesion: 0.2
Nodes (3): DynamicEntityTab(), getEntityConfig(), ProfilePage()

### Community 26 - "Community 26"
Cohesion: 0.36
Nodes (10): are_semantic_duplicates(), _contains_phrase(), normalize_fact_value(), normalize_text(), _preference_axes(), Shared helpers for distinguishing true conflicts from compatible facts., Separate incompatible clusters from facts that can safely coexist., semantic_tokens() (+2 more)

### Community 27 - "Community 27"
Cohesion: 0.29
Nodes (8): _benchmark_dir(), build_eval_analytics(), _group_summary(), list_benchmark_sets(), Benchmark metadata and replay analytics for continuous evaluation., Build grouped replay analytics for continuous evaluation., Load benchmark-set metadata from checked-in JSON files., _trend_summary()

### Community 28 - "Community 28"
Cohesion: 0.27
Nodes (5): applyTheme(), appReducer(), generateRuntimeStudentId(), getOrCreateRuntimeStudentId(), getSystemTheme()

### Community 29 - "Community 29"
Cohesion: 0.33
Nodes (8): _balanced_slice(), parse_json_array(), parse_json_object(), _parse_json_payload(), Utilities for robustly extracting JSON payloads from model output., Parse a JSON object from raw model output., Parse a JSON array from raw model output., _try_loads()

### Community 30 - "Community 30"
Cohesion: 0.31
Nodes (8): auto_resolve_profile_conflicts(), _build_options(), list_profile_conflicts(), Conservative conflict helpers for profile-memory resolution., Return unresolved profile conflicts in UI-friendly shape., Apply a user-provided conflict choice and refresh conflict view., Run conservative auto-resolution and return summary., resolve_conflict_choice()

### Community 31 - "Community 31"
Cohesion: 0.25
Nodes (7): call_tool(), list_tools(), Pathfinder MCP server backed by the canonical internal tool registry., List available Pathfinder tools., Execute a Pathfinder tool and return the canonical JSON envelope., Run the MCP server over stdio., run_mcp_server()

### Community 32 - "Community 32"
Cohesion: 0.29
Nodes (7): _extract_text(), extract_urls(), fetch_url_content(), Direct URL content fetcher.  When the user provides a specific URL, this module, Extract readable text from a BeautifulSoup element.      Preserves paragraph str, Extract all URLs from a text string., Fetch a URL and extract its text content.      Returns a dict with title, url, c

### Community 33 - "Community 33"
Cohesion: 0.32
Nodes (7): evaluate_recent_replays(), evaluate_replay_artifact(), evaluate_replay_by_id(), Lightweight replay artifact evaluation for regression checks., Score a replay artifact using lightweight completeness and grounding heuristics., Load and evaluate one replay artifact., Evaluate a batch of recent replay artifacts.

### Community 34 - "Community 34"
Cohesion: 0.52
Nodes (6): formatPercent(), formatPriority(), formatTime(), getEvalBadgeClass(), ReplayPage(), useReplayQueryParam()

### Community 35 - "Community 35"
Cohesion: 0.29
Nodes (0): 

### Community 36 - "Community 36"
Cohesion: 0.33
Nodes (5): get_checkpointer(), Persistent conversation memory via LangGraph SqliteSaver.  Provides the checkpoi, Return the singleton SQLite checkpointer., Close checkpointer connection and remove persisted chat storage., reset_checkpointer_storage()

### Community 37 - "Community 37"
Cohesion: 0.33
Nodes (5): DuckDuckGo search adapter (free, no API key needed).  Uses the `ddgs` package (f, Run the synchronous DDGS text search., Search using DuckDuckGo (last resort, always available)., search(), _sync_search()

### Community 38 - "Community 38"
Cohesion: 0.47
Nodes (5): _collect_signals(), infer_document_role(), Document role inference helpers.  Infers the semantic role of an uploaded docume, Infer a semantic document role from filename and extracted text., _role_score()

### Community 39 - "Community 39"
Cohesion: 0.4
Nodes (5): build_decision_record(), persist_decision_record(), Decision-memory persistence and continuity helpers., Build a structured decision record from a completed turn., Persist a structured decision record for future related conversations.

### Community 40 - "Community 40"
Cohesion: 0.33
Nodes (1): ErrorBoundary

### Community 41 - "Community 41"
Cohesion: 0.4
Nodes (3): lifespan(), Pathfinder FastAPI application entry point., Startup and shutdown tasks.

### Community 42 - "Community 42"
Cohesion: 0.4
Nodes (0): 

### Community 43 - "Community 43"
Cohesion: 0.5
Nodes (3): BaseSettings, Pathfinder application settings.  All configuration is loaded from environment v, Settings

### Community 44 - "Community 44"
Cohesion: 0.5
Nodes (3): Tavily AI search adapter., Search using Tavily AI Search API., search()

### Community 45 - "Community 45"
Cohesion: 0.5
Nodes (3): Brave Search adapter., Search using Brave Search API., search()

### Community 46 - "Community 46"
Cohesion: 0.5
Nodes (3): Web search fallback chain.  Tries search providers in order: Tavily -> Google CS, Search the web using the fallback chain.      Tries each provider in order and a, search()

### Community 47 - "Community 47"
Cohesion: 0.5
Nodes (3): Google Custom Search Engine adapter., Search using Google Custom Search Engine API., search()

### Community 48 - "Community 48"
Cohesion: 0.5
Nodes (3): get_embeddings(), Ollama embeddings adapter.  Provides a singleton OllamaEmbeddings instance for g, Return the singleton embeddings model (mxbai-embed-large).

### Community 49 - "Community 49"
Cohesion: 0.5
Nodes (0): 

### Community 50 - "Community 50"
Cohesion: 0.67
Nodes (2): formatPriority(), Message()

### Community 51 - "Community 51"
Cohesion: 0.67
Nodes (0): 

### Community 52 - "Community 52"
Cohesion: 0.67
Nodes (0): 

### Community 53 - "Community 53"
Cohesion: 0.67
Nodes (0): 

### Community 54 - "Community 54"
Cohesion: 1.0
Nodes (1): Central prompt registry for Pathfinder agents and services.  All system/instruct

### Community 55 - "Community 55"
Cohesion: 1.0
Nodes (0): 

### Community 56 - "Community 56"
Cohesion: 1.0
Nodes (0): 

### Community 57 - "Community 57"
Cohesion: 1.0
Nodes (0): 

### Community 58 - "Community 58"
Cohesion: 1.0
Nodes (0): 

### Community 59 - "Community 59"
Cohesion: 1.0
Nodes (0): 

### Community 60 - "Community 60"
Cohesion: 1.0
Nodes (0): 

### Community 61 - "Community 61"
Cohesion: 1.0
Nodes (0): 

### Community 62 - "Community 62"
Cohesion: 1.0
Nodes (0): 

### Community 63 - "Community 63"
Cohesion: 1.0
Nodes (0): 

### Community 64 - "Community 64"
Cohesion: 1.0
Nodes (0): 

### Community 65 - "Community 65"
Cohesion: 1.0
Nodes (0): 

### Community 66 - "Community 66"
Cohesion: 1.0
Nodes (0): 

### Community 67 - "Community 67"
Cohesion: 1.0
Nodes (0): 

### Community 68 - "Community 68"
Cohesion: 1.0
Nodes (0): 

### Community 69 - "Community 69"
Cohesion: 1.0
Nodes (0): 

### Community 70 - "Community 70"
Cohesion: 1.0
Nodes (0): 

### Community 71 - "Community 71"
Cohesion: 1.0
Nodes (0): 

### Community 72 - "Community 72"
Cohesion: 1.0
Nodes (0): 

### Community 73 - "Community 73"
Cohesion: 1.0
Nodes (0): 

### Community 74 - "Community 74"
Cohesion: 1.0
Nodes (0): 

### Community 75 - "Community 75"
Cohesion: 1.0
Nodes (0): 

### Community 76 - "Community 76"
Cohesion: 1.0
Nodes (0): 

## Knowledge Gaps
- **284 isolated node(s):** `Pathfinder FastAPI application entry point.`, `Startup and shutdown tasks.`, `Pathfinder MCP server backed by the canonical internal tool registry.`, `List available Pathfinder tools.`, `Execute a Pathfinder tool and return the canonical JSON envelope.` (+279 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 54`** (2 nodes): `prompts.py`, `Central prompt registry for Pathfinder agents and services.  All system/instruct`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 55`** (2 nodes): `App()`, `App.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 56`** (2 nodes): `InputArea.jsx`, `InputArea()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 57`** (2 nodes): `StreamingProgress.jsx`, `StreamingProgress()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 58`** (2 nodes): `Sidebar.jsx`, `Sidebar()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 59`** (2 nodes): `utils.js`, `cn()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 60`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 61`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 62`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 63`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 64`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 65`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 66`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 67`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 68`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 69`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 70`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 71`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 72`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 73`** (1 nodes): `tailwind.config.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 74`** (1 nodes): `vite.config.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 75`** (1 nodes): `postcss.config.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 76`** (1 nodes): `main.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `PathfinderState` connect `Community 1` to `Community 0`, `Community 4`, `Community 8`, `Community 9`, `Community 19`, `Community 21`?**
  _High betweenness centrality (0.086) - this node is a cross-community bridge._
- **Why does `DecisionPayload` connect `Community 4` to `Community 0`, `Community 8`, `Community 19`, `Community 21`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **Why does `Node: Course Planner.  Builds a structured decision payload for course-planning` connect `Community 8` to `Community 1`, `Community 4`?**
  _High betweenness centrality (0.015) - this node is a cross-community bridge._
- **Are the 100 inferred relationships involving `PathfinderState` (e.g. with `LangGraph StateGraph assembly.  Builds the Pathfinder multi-agent graph with con` and `After Input Guard: if blocked, go to responder; else orchestrator.`) actually correct?**
  _`PathfinderState` has 100 INFERRED edges - model-reasoned connections that need verification._
- **Are the 33 inferred relationships involving `ProfileTextInput` (e.g. with `Main chat endpoint with SSE streaming.` and `List local student profiles.`) actually correct?**
  _`ProfileTextInput` has 33 INFERRED edges - model-reasoned connections that need verification._
- **Are the 33 inferred relationships involving `ProfileUpdate` (e.g. with `Main chat endpoint with SSE streaming.` and `List local student profiles.`) actually correct?**
  _`ProfileUpdate` has 33 INFERRED edges - model-reasoned connections that need verification._
- **Are the 33 inferred relationships involving `EntityUpdate` (e.g. with `Main chat endpoint with SSE streaming.` and `List local student profiles.`) actually correct?**
  _`EntityUpdate` has 33 INFERRED edges - model-reasoned connections that need verification._