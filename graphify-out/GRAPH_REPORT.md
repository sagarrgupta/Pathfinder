# Graph Report - .  (2026-04-12)

## Corpus Check
- 95 files · ~98,179 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1279 nodes · 2882 edges · 77 communities detected
- Extraction: 63% EXTRACTED · 37% INFERRED · 0% AMBIGUOUS · INFERRED: 1072 edges (avg confidence: 0.5)
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
2. `ProfileTextInput` - 44 edges
3. `ProfileUpdate` - 44 edges
4. `EntityUpdate` - 44 edges
5. `ProfileCreate` - 44 edges
6. `ConflictChoiceRequest` - 44 edges
7. `SettingsUpdate` - 44 edges
8. `SavedRecommendationCreate` - 44 edges
9. `SavedRecommendationOutcomeUpdate` - 44 edges
10. `ChatResponse` - 44 edges

## Surprising Connections (you probably didn't know these)
- `Node 2: Orchestrator.  Classifies user intent, checks what data is available, an` --uses--> `PathfinderState`  [INFERRED]
  app/agents/orchestrator.py → app/core/state.py
- `Classify intent and create an execution plan.` --uses--> `PathfinderState`  [INFERRED]
  app/agents/orchestrator.py → app/core/state.py
- `LangGraph StateGraph assembly.  Builds the Pathfinder multi-agent graph with con` --uses--> `PathfinderState`  [INFERRED]
  app/core/graph.py → app/core/state.py
- `After Input Guard: if blocked, go to responder; else orchestrator.` --uses--> `PathfinderState`  [INFERRED]
  app/core/graph.py → app/core/state.py
- `After Orchestrator: route to the first node in the plan.` --uses--> `PathfinderState`  [INFERRED]
  app/core/graph.py → app/core/state.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.02
Nodes (146): academic_advisor(), _format_documents(), _format_profile(), _format_recent_messages(), _format_web_results(), _has_live_schedule_sources(), _has_verified_course_sources(), _is_course_recommendation_query() (+138 more)

### Community 1 - "Community 1"
Cohesion: 0.02
Nodes (146): _academic_level_scores(), academic_source_relevance(), add_handoff_note(), add_working_memory_item(), analyze_query_focus(), AnswerSupportRef, append_unique_text(), _application_targeting_signals() (+138 more)

### Community 2 - "Community 2"
Cohesion: 0.11
Nodes (137): BaseModel, ChatRequest, ChatResponse, Citation, ConflictChoiceRequest, DocumentUploadResponse, EntityUpdate, EvalAnalyticsResponse (+129 more)

### Community 3 - "Community 3"
Cohesion: 0.04
Nodes (77): apply_conflict_choice(), close_driver(), create_entity(), create_student(), delete_document_cascade(), delete_entity(), delete_entity_for_student(), ensure_student() (+69 more)

### Community 4 - "Community 4"
Cohesion: 0.07
Nodes (50): finalize_structured_advisor(), _normalize_decision_payload(), _normalize_item_list(), _normalize_source_refs(), _normalize_string_list(), prepare_structured_advisor(), Shared runtime helpers for structured advisor nodes.  This module centralizes th, Apply common finalization logic for structured advisor nodes. (+42 more)

### Community 5 - "Community 5"
Cohesion: 0.07
Nodes (40): _advisor_mode_plan(), build_request_plan(), _is_greeting(), _is_profile_update(), _looks_like_document_request(), _looks_like_url_analysis(), _prepend_unique(), Deterministic request planning for obvious control-plane flows. (+32 more)

### Community 6 - "Community 6"
Cohesion: 0.08
Nodes (45): _determine_next(), doc_analyst(), _page_for_chunk(), Node 4: Doc Analyst.  Processes uploaded documents through the adaptive pipeline, Find which page a chunk came from (best effort)., Determine next node after document processing., Process uploaded files: extract, chunk, embed, store., aembed_documents() (+37 more)

### Community 7 - "Community 7"
Cohesion: 0.1
Nodes (45): build_memory_pack(), _build_official_retry_query(), _build_personal_context(), _build_retrieval_diagnostics(), build_retrieval_plan(), _build_retrieval_trace(), _cache_get(), _cache_key() (+37 more)

### Community 8 - "Community 8"
Cohesion: 0.1
Nodes (39): _allowed_course_prefixes(), _build_recommendation_paths(), _build_semester_plan_options(), _code_allowed_for_program(), _compile_academic_program_model(), _course_code_from_profile_entity(), _course_outline_for_operating_model(), _course_outline_for_strategy() (+31 more)

### Community 9 - "Community 9"
Cohesion: 0.07
Nodes (37): ChatOpenAI, _build_llm(), get_structured_llm(), get_text_llm(), get_vision_llm(), is_garbage_output(), _log_error(), _log_request() (+29 more)

### Community 10 - "Community 10"
Cohesion: 0.14
Nodes (32): CandidateFactRecord, _classify_fact_stability(), _clean_candidate_value(), _clean_student_property(), _evidence_kind(), _expand_core_values(), _extract_memory_candidates(), _fact_preference_score() (+24 more)

### Community 11 - "Community 11"
Cohesion: 0.09
Nodes (15): addProfileText(), autoResolveProfileConflicts(), checkDocumentExists(), deleteProfileEntity(), deleteSession(), evaluateRecentReplays(), getEvalAnalytics(), getProfile() (+7 more)

### Community 12 - "Community 12"
Cohesion: 0.13
Nodes (19): Structured recovery recipes for common Pathfinder runtime failures., Structured recovery event for one automatic degradation or escalation., Recovery event for document extraction failures., Recovery event for files that produced no usable extracted text., Recovery event for chunking/embedding storage failures., Recovery event for entity extraction failures during document analysis., Recovery event when retrieval produces very thin evidence., Return explicit recovery events for dependency-gated workflows. (+11 more)

### Community 13 - "Community 13"
Cohesion: 0.12
Nodes (10): metadata_fields(), metadata_json(), Shared utility helpers for the Neo4j graph store., Validate dynamic Cypher identifiers used for labels/relationships., Extract and sanitize a projected map field from one Neo4j record., Convert Neo4j-specific types to Python-native types recursively., Return the canonical metadata payload for graph writes., record_map() (+2 more)

### Community 14 - "Community 14"
Cohesion: 0.16
Nodes (17): _convert_heif_to_jpeg(), _extract_page_with_vision(), extract_text_from_docx(), extract_text_from_image(), extract_text_from_pdf(), extract_text_from_plaintext(), _extract_text_with_vision(), get_file_type() (+9 more)

### Community 15 - "Community 15"
Cohesion: 0.18
Nodes (17): build_transcript_state(), _course_status(), _extract_courses(), _extract_cumulative_gpa(), _extract_latest_academic_standing(), _extract_milestones(), _extract_personal_info(), _extract_term_gpa() (+9 more)

### Community 16 - "Community 16"
Cohesion: 0.21
Nodes (14): build_candidate_fact_ledger(), build_full_profile_payload(), build_temporal_profile(), candidate_confirmation_state(), canonical_entity_key(), dedupe_entities(), expand_compound_entity_values(), parse_datetimeish() (+6 more)

### Community 17 - "Community 17"
Cohesion: 0.12
Nodes (15): generate_chunk_id(), generate_document_id(), generate_evidence_id(), generate_memory_id(), generate_replay_id(), generate_session_id(), generate_student_id(), ID generation utilities. (+7 more)

### Community 18 - "Community 18"
Cohesion: 0.19
Nodes (15): _document_ingestors(), execute_document_ingestion(), execute_web_search(), ExecutionRegistry, get_active_retrieval_strategy(), get_active_text_model(), get_active_vision_model(), get_execution_registry() (+7 more)

### Community 19 - "Community 19"
Cohesion: 0.27
Nodes (14): _build_eligibility_paths(), _dedupe_sequence(), _dedupe_source_refs(), _eligibility_goals(), _eligibility_next_step_for_strategy(), _eligibility_outline_for_operating_model(), _eligibility_outline_for_strategy(), eligibility_reasoner() (+6 more)

### Community 20 - "Community 20"
Cohesion: 0.17
Nodes (14): _background_loop(), BackgroundStatus, consolidation_loop(), get_background_status(), _is_neo4j_auth_error(), Lightweight background jobs for Pathfinder., Return current background job status for observability., Backward-compatible loop entry used by existing startup wiring. (+6 more)

### Community 21 - "Community 21"
Cohesion: 0.27
Nodes (13): _build_career_paths(), _career_goals(), career_matcher(), _career_next_step_for_strategy(), _career_outline_for_operating_model(), _career_outline_for_strategy(), _dedupe_sequence(), _dedupe_source_refs() (+5 more)

### Community 22 - "Community 22"
Cohesion: 0.29
Nodes (12): auto_resolve_profile_conflicts(), _fetch_candidate_facts(), _freshness_score(), list_profile_conflicts(), maybe_consolidate_memory(), _parse_datetimeish(), _rank_candidate(), Event-driven and periodic memory consolidation hooks. (+4 more)

### Community 23 - "Community 23"
Cohesion: 0.23
Nodes (11): _artifact_dir(), build_replay_artifact(), get_replay_artifact(), list_replay_artifacts(), Replay artifact persistence for completed Pathfinder turns., Load a single replay artifact by ID., Build a compact replay artifact from a completed chat turn., Persist a replay artifact to disk as JSON. (+3 more)

### Community 24 - "Community 24"
Cohesion: 0.2
Nodes (3): DynamicEntityTab(), getEntityConfig(), ProfilePage()

### Community 25 - "Community 25"
Cohesion: 0.29
Nodes (8): _deterministic_intent_for_workflow(), _ensure_academic_fact_plan(), _ensure_quality_course_plan(), _merge_ordered_plan(), orchestrator(), _plan_for_workflow(), Node 2: Orchestrator.  Classifies user intent, checks what data is available, an, Classify intent and create an execution plan.

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
Nodes (7): call_tool(), list_tools(), Pathfinder MCP Server.  Exposes Pathfinder tools via the Model Context Protocol, Run the MCP server over stdio., List available Pathfinder tools., Execute a Pathfinder tool., run_mcp_server()

### Community 32 - "Community 32"
Cohesion: 0.29
Nodes (7): _extract_text(), extract_urls(), fetch_url_content(), Direct URL content fetcher.  When the user provides a specific URL, this module, Extract readable text from a BeautifulSoup element.      Preserves paragraph str, Extract all URLs from a text string., Fetch a URL and extract its text content.      Returns a dict with title, url, c

### Community 33 - "Community 33"
Cohesion: 0.32
Nodes (7): evaluate_recent_replays(), evaluate_replay_artifact(), evaluate_replay_by_id(), Lightweight replay artifact evaluation for regression checks., Score a replay artifact using lightweight completeness and grounding heuristics., Load and evaluate one replay artifact., Evaluate a batch of recent replay artifacts.

### Community 34 - "Community 34"
Cohesion: 0.43
Nodes (5): build_search_result(), clamp_max_results(), dedupe_results(), normalize_url(), Shared helpers for web search adapters.

### Community 35 - "Community 35"
Cohesion: 0.52
Nodes (6): formatPercent(), formatPriority(), formatTime(), getEvalBadgeClass(), ReplayPage(), useReplayQueryParam()

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
Nodes (3): get_structured_output_schema(), Structured-output schemas for LLM nodes that return machine-consumed JSON., Return a JSON schema for the given node, if one is registered.

### Community 43 - "Community 43"
Cohesion: 0.4
Nodes (0): 

### Community 44 - "Community 44"
Cohesion: 0.5
Nodes (3): BaseSettings, Pathfinder application settings.  All configuration is loaded from environment v, Settings

### Community 45 - "Community 45"
Cohesion: 0.5
Nodes (3): Tavily AI search adapter., Search using Tavily AI Search API., search()

### Community 46 - "Community 46"
Cohesion: 0.5
Nodes (3): Brave Search adapter., Search using Brave Search API., search()

### Community 47 - "Community 47"
Cohesion: 0.5
Nodes (3): Web search fallback chain.  Tries search providers in order: Tavily -> Google CS, Search the web using the fallback chain.      Tries each provider in order and a, search()

### Community 48 - "Community 48"
Cohesion: 0.5
Nodes (3): Google Custom Search Engine adapter., Search using Google Custom Search Engine API., search()

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
- **291 isolated node(s):** `Pathfinder FastAPI application entry point.`, `Startup and shutdown tasks.`, `Pathfinder MCP Server.  Exposes Pathfinder tools via the Model Context Protocol`, `List available Pathfinder tools.`, `Execute a Pathfinder tool.` (+286 more)
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

- **Why does `PathfinderState` connect `Community 0` to `Community 1`, `Community 4`, `Community 6`, `Community 8`, `Community 19`, `Community 21`, `Community 25`?**
  _High betweenness centrality (0.099) - this node is a cross-community bridge._
- **Why does `DecisionPayload` connect `Community 4` to `Community 8`, `Community 1`, `Community 19`, `Community 21`?**
  _High betweenness centrality (0.039) - this node is a cross-community bridge._
- **Are the 100 inferred relationships involving `PathfinderState` (e.g. with `LangGraph StateGraph assembly.  Builds the Pathfinder multi-agent graph with con` and `After Input Guard: if blocked, go to responder; else orchestrator.`) actually correct?**
  _`PathfinderState` has 100 INFERRED edges - model-reasoned connections that need verification._
- **Are the 41 inferred relationships involving `ProfileTextInput` (e.g. with `Normalize a raw student record into the API response shape.` and `Normalize a stored memory record into a saved recommendation response.`) actually correct?**
  _`ProfileTextInput` has 41 INFERRED edges - model-reasoned connections that need verification._
- **Are the 41 inferred relationships involving `ProfileUpdate` (e.g. with `Normalize a raw student record into the API response shape.` and `Normalize a stored memory record into a saved recommendation response.`) actually correct?**
  _`ProfileUpdate` has 41 INFERRED edges - model-reasoned connections that need verification._
- **Are the 41 inferred relationships involving `EntityUpdate` (e.g. with `Normalize a raw student record into the API response shape.` and `Normalize a stored memory record into a saved recommendation response.`) actually correct?**
  _`EntityUpdate` has 41 INFERRED edges - model-reasoned connections that need verification._
- **Are the 41 inferred relationships involving `ProfileCreate` (e.g. with `Normalize a raw student record into the API response shape.` and `Normalize a stored memory record into a saved recommendation response.`) actually correct?**
  _`ProfileCreate` has 41 INFERRED edges - model-reasoned connections that need verification._