# Graph Report - .  (2026-04-12)

## Corpus Check
- 81 files · ~66,302 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1006 nodes · 2199 edges · 72 communities detected
- Extraction: 61% EXTRACTED · 39% INFERRED · 0% AMBIGUOUS · INFERRED: 848 edges (avg confidence: 0.5)
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

## God Nodes (most connected - your core abstractions)
1. `ProfileTextInput` - 41 edges
2. `ProfileUpdate` - 41 edges
3. `EntityUpdate` - 41 edges
4. `ProfileCreate` - 41 edges
5. `SettingsUpdate` - 41 edges
6. `SavedRecommendationCreate` - 41 edges
7. `SavedRecommendationOutcomeUpdate` - 41 edges
8. `ChatResponse` - 41 edges
9. `DocumentUploadResponse` - 41 edges
10. `ProfileResponse` - 41 edges

## Surprising Connections (you probably didn't know these)
- `Deterministic specialist selector for the simplified Pathfinder flow.` --uses--> `PathfinderState`  [INFERRED]
  app/agents/orchestrator.py → app/core/state.py
- `Score the request against the 3 specialist prompt families.` --uses--> `PathfinderState`  [INFERRED]
  app/agents/orchestrator.py → app/core/state.py
- `Pathfinder MCP server backed by the canonical tool registry.` --uses--> `ToolContext`  [INFERRED]
  app/mcp_server.py → app/tools/registry.py
- `Expose the canonical registry as MCP tools.` --uses--> `ToolContext`  [INFERRED]
  app/mcp_server.py → app/tools/registry.py
- `Dispatch one tool through the shared registry.` --uses--> `ToolContext`  [INFERRED]
  app/mcp_server.py → app/tools/registry.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.02
Nodes (147): _academic_level_scores(), academic_source_relevance(), add_handoff_note(), add_working_memory_item(), analyze_query_focus(), AnswerSupportRef, append_unique_text(), _application_targeting_signals() (+139 more)

### Community 1 - "Community 1"
Cohesion: 0.03
Nodes (86): build_graph(), get_compiled_graph(), LangGraph assembly for the simplified MCP-first Pathfinder flow., After input guard, either stop with responder or continue to orchestration., The orchestrator either dispatches to the specialist or short-circuits., The specialist usually goes through validation before response rendering., The validator can only forward to the responder., Build the simplified Pathfinder graph. (+78 more)

### Community 2 - "Community 2"
Cohesion: 0.22
Nodes (89): BaseModel, ChatRequest, ChatResponse, Citation, DocumentUploadResponse, EntityUpdate, EvalAnalyticsResponse, EvalBenchmarkInfo (+81 more)

### Community 3 - "Community 3"
Cohesion: 0.04
Nodes (77): apply_conflict_choice(), close_driver(), create_entity(), create_student(), delete_document_cascade(), delete_entity(), delete_entity_for_student(), ensure_student() (+69 more)

### Community 4 - "Community 4"
Cohesion: 0.08
Nodes (45): _determine_next(), doc_analyst(), _page_for_chunk(), Node 4: Doc Analyst.  Processes uploaded documents through the adaptive pipeline, Find which page a chunk came from (best effort)., Document processing is now a leaf pre-ingestion step., Process uploaded files: extract, chunk, embed, store., aembed_documents() (+37 more)

### Community 5 - "Community 5"
Cohesion: 0.09
Nodes (40): add_profile_text(), background_status(), chat(), check_document_exists(), create_profile(), delete_all_data_everywhere(), delete_profile_entity(), delete_session() (+32 more)

### Community 6 - "Community 6"
Cohesion: 0.08
Nodes (33): ChatOpenAI, _build_llm(), get_text_llm(), get_vision_llm(), is_garbage_output(), _log_error(), _log_request(), _log_response() (+25 more)

### Community 7 - "Community 7"
Cohesion: 0.14
Nodes (32): CandidateFactRecord, _classify_fact_stability(), _clean_candidate_value(), _clean_student_property(), _evidence_kind(), _expand_core_values(), _extract_memory_candidates(), _fact_preference_score() (+24 more)

### Community 8 - "Community 8"
Cohesion: 0.1
Nodes (12): addProfileText(), checkDocumentExists(), deleteProfileEntity(), deleteSession(), evaluateRecentReplays(), getEvalAnalytics(), getProfile(), getProfileGraph() (+4 more)

### Community 9 - "Community 9"
Cohesion: 0.13
Nodes (19): Structured recovery recipes for common Pathfinder runtime failures., Structured recovery event for one automatic degradation or escalation., Recovery event for document extraction failures., Recovery event for files that produced no usable extracted text., Recovery event for chunking/embedding storage failures., Recovery event for entity extraction failures during document analysis., Recovery event when retrieval produces very thin evidence., Return explicit recovery events for dependency-gated workflows. (+11 more)

### Community 10 - "Community 10"
Cohesion: 0.13
Nodes (16): build_chat_runtime_session(), ChatRuntimeSession, DependencySnapshot, determine_method(), get_dependency_status(), Runtime session helpers for chat execution.  This module centralizes per-request, Build graph config for this turn., Build the final SSE payload for a completed turn. (+8 more)

### Community 11 - "Community 11"
Cohesion: 0.12
Nodes (10): metadata_fields(), metadata_json(), Shared utility helpers for the Neo4j graph store., Validate dynamic Cypher identifiers used for labels/relationships., Extract and sanitize a projected map field from one Neo4j record., Convert Neo4j-specific types to Python-native types recursively., Return the canonical metadata payload for graph writes., record_map() (+2 more)

### Community 12 - "Community 12"
Cohesion: 0.16
Nodes (17): _convert_heif_to_jpeg(), _extract_page_with_vision(), extract_text_from_docx(), extract_text_from_image(), extract_text_from_pdf(), extract_text_from_plaintext(), _extract_text_with_vision(), get_file_type() (+9 more)

### Community 13 - "Community 13"
Cohesion: 0.18
Nodes (17): build_transcript_state(), _course_status(), _extract_courses(), _extract_cumulative_gpa(), _extract_latest_academic_standing(), _extract_milestones(), _extract_personal_info(), _extract_term_gpa() (+9 more)

### Community 14 - "Community 14"
Cohesion: 0.21
Nodes (14): build_candidate_fact_ledger(), build_full_profile_payload(), build_temporal_profile(), candidate_confirmation_state(), canonical_entity_key(), dedupe_entities(), expand_compound_entity_values(), parse_datetimeish() (+6 more)

### Community 15 - "Community 15"
Cohesion: 0.12
Nodes (15): generate_chunk_id(), generate_document_id(), generate_evidence_id(), generate_memory_id(), generate_replay_id(), generate_session_id(), generate_student_id(), ID generation utilities. (+7 more)

### Community 16 - "Community 16"
Cohesion: 0.17
Nodes (15): _artifact_dir(), build_replay_artifact(), delete_all_replay_artifacts(), delete_replay_artifacts_for_student(), get_replay_artifact(), list_replay_artifacts(), Replay artifact persistence for completed Pathfinder turns., Load a single replay artifact by ID. (+7 more)

### Community 17 - "Community 17"
Cohesion: 0.19
Nodes (15): _document_ingestors(), execute_document_ingestion(), execute_web_search(), ExecutionRegistry, get_active_retrieval_strategy(), get_active_text_model(), get_active_vision_model(), get_execution_registry() (+7 more)

### Community 18 - "Community 18"
Cohesion: 0.17
Nodes (14): _background_loop(), BackgroundStatus, consolidation_loop(), get_background_status(), _is_neo4j_auth_error(), Lightweight background jobs for Pathfinder., Return current background job status for observability., Backward-compatible loop entry used by existing startup wiring. (+6 more)

### Community 19 - "Community 19"
Cohesion: 0.19
Nodes (4): DynamicEntityTab(), getEntityConfig(), ProfilePage(), validateLongContextSummary()

### Community 20 - "Community 20"
Cohesion: 0.36
Nodes (10): are_semantic_duplicates(), _contains_phrase(), normalize_fact_value(), normalize_text(), _preference_axes(), Shared helpers for distinguishing true conflicts from compatible facts., Separate incompatible clusters from facts that can safely coexist., semantic_tokens() (+2 more)

### Community 21 - "Community 21"
Cohesion: 0.29
Nodes (8): _benchmark_dir(), build_eval_analytics(), _group_summary(), list_benchmark_sets(), Benchmark metadata and replay analytics for continuous evaluation., Build grouped replay analytics for continuous evaluation., Load benchmark-set metadata from checked-in JSON files., _trend_summary()

### Community 22 - "Community 22"
Cohesion: 0.36
Nodes (9): build_long_context_payload(), _default_summary(), _manifest(), normalize_long_context_summary(), Shared builders for the long-context payload passed to specialists., Build the durable long-context payload shared across runtime and UI., Validate and normalize the editable long-context summary format., _small_facts() (+1 more)

### Community 23 - "Community 23"
Cohesion: 0.27
Nodes (5): applyTheme(), appReducer(), generateRuntimeStudentId(), getOrCreateRuntimeStudentId(), getSystemTheme()

### Community 24 - "Community 24"
Cohesion: 0.33
Nodes (8): _balanced_slice(), parse_json_array(), parse_json_object(), _parse_json_payload(), Utilities for robustly extracting JSON payloads from model output., Parse a JSON object from raw model output., Parse a JSON array from raw model output., _try_loads()

### Community 25 - "Community 25"
Cohesion: 0.39
Nodes (8): _fetch_candidate_facts(), _freshness_score(), maybe_consolidate_memory(), _parse_datetimeish(), _rank_candidate(), Event-driven and periodic memory consolidation hooks., Run a bounded consolidation pass over candidate facts and memories., _update_statuses()

### Community 26 - "Community 26"
Cohesion: 0.39
Nodes (7): _durable_context(), _is_light_conversation(), _keyword_overlap(), orchestrator(), _profile_signals(), Deterministic specialist selector for the simplified Pathfinder flow., Score the request against the 3 specialist prompt families.

### Community 27 - "Community 27"
Cohesion: 0.29
Nodes (7): _extract_text(), extract_urls(), fetch_url_content(), Direct URL content fetcher.  When the user provides a specific URL, this module, Extract readable text from a BeautifulSoup element.      Preserves paragraph str, Extract all URLs from a text string., Fetch a URL and extract its text content.      Returns a dict with title, url, c

### Community 28 - "Community 28"
Cohesion: 0.32
Nodes (7): evaluate_recent_replays(), evaluate_replay_artifact(), evaluate_replay_by_id(), Lightweight replay artifact evaluation for regression checks., Load and evaluate one replay artifact., Score a replay artifact using lightweight specialist-turn heuristics., Evaluate a batch of recent replay artifacts.

### Community 29 - "Community 29"
Cohesion: 0.43
Nodes (5): build_search_result(), clamp_max_results(), dedupe_results(), normalize_url(), Shared helpers for web search adapters.

### Community 30 - "Community 30"
Cohesion: 0.33
Nodes (5): get_checkpointer(), Persistent conversation memory via LangGraph SqliteSaver.  Provides the checkpoi, Return the singleton SQLite checkpointer., Close checkpointer connection and remove persisted chat storage., reset_checkpointer_storage()

### Community 31 - "Community 31"
Cohesion: 0.33
Nodes (5): DuckDuckGo search adapter (free, no API key needed).  Uses the `ddgs` package (f, Run the synchronous DDGS text search., Search using DuckDuckGo (last resort, always available)., search(), _sync_search()

### Community 32 - "Community 32"
Cohesion: 0.47
Nodes (5): _collect_signals(), infer_document_role(), Document role inference helpers.  Infers the semantic role of an uploaded docume, Infer a semantic document role from filename and extracted text., _role_score()

### Community 33 - "Community 33"
Cohesion: 0.4
Nodes (5): build_decision_record(), persist_decision_record(), Decision-memory persistence and continuity helpers., Build a compact specialist-turn memory record from a completed turn., Persist a structured decision record for future related conversations.

### Community 34 - "Community 34"
Cohesion: 0.4
Nodes (5): _fallback_student_updates(), process_free_text(), Focused free-text profile ingestion helpers used by the API., Process free-text profile input from the My Profile page., Best-effort extraction of core student fields when full ingestion fails.

### Community 35 - "Community 35"
Cohesion: 0.47
Nodes (3): confidenceTone(), formatPriority(), Message()

### Community 36 - "Community 36"
Cohesion: 0.33
Nodes (1): ErrorBoundary

### Community 37 - "Community 37"
Cohesion: 0.53
Nodes (4): formatLabel(), formatTime(), ReplayPage(), useReplayQueryParam()

### Community 38 - "Community 38"
Cohesion: 0.4
Nodes (3): lifespan(), Pathfinder FastAPI application entry point., Startup and shutdown tasks.

### Community 39 - "Community 39"
Cohesion: 0.4
Nodes (0): 

### Community 40 - "Community 40"
Cohesion: 0.5
Nodes (3): BaseSettings, Pathfinder application settings.  All configuration is loaded from environment v, Settings

### Community 41 - "Community 41"
Cohesion: 0.5
Nodes (3): Tavily AI search adapter., Search using Tavily AI Search API., search()

### Community 42 - "Community 42"
Cohesion: 0.5
Nodes (3): Brave Search adapter., Search using Brave Search API., search()

### Community 43 - "Community 43"
Cohesion: 0.5
Nodes (3): Web search fallback chain.  Tries search providers in order: Tavily -> Google CS, Search the web using the fallback chain.      Tries each provider in order and a, search()

### Community 44 - "Community 44"
Cohesion: 0.5
Nodes (3): Google Custom Search Engine adapter., Search using Google Custom Search Engine API., search()

### Community 45 - "Community 45"
Cohesion: 0.5
Nodes (0): 

### Community 46 - "Community 46"
Cohesion: 0.67
Nodes (0): 

### Community 47 - "Community 47"
Cohesion: 0.67
Nodes (0): 

### Community 48 - "Community 48"
Cohesion: 1.0
Nodes (1): Shared tool registry package for Pathfinder.

### Community 49 - "Community 49"
Cohesion: 1.0
Nodes (1): Active prompt registry for the simplified Pathfinder flow.

### Community 50 - "Community 50"
Cohesion: 1.0
Nodes (0): 

### Community 51 - "Community 51"
Cohesion: 1.0
Nodes (0): 

### Community 52 - "Community 52"
Cohesion: 1.0
Nodes (0): 

### Community 53 - "Community 53"
Cohesion: 1.0
Nodes (0): 

### Community 54 - "Community 54"
Cohesion: 1.0
Nodes (0): 

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

## Knowledge Gaps
- **281 isolated node(s):** `Pathfinder FastAPI application entry point.`, `Startup and shutdown tasks.`, `Shared tool registry package for Pathfinder.`, `Persistent conversation memory via LangGraph SqliteSaver.  Provides the checkpoi`, `Return the singleton SQLite checkpointer.` (+276 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 48`** (2 nodes): `__init__.py`, `Shared tool registry package for Pathfinder.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 49`** (2 nodes): `prompts.py`, `Active prompt registry for the simplified Pathfinder flow.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 50`** (2 nodes): `App()`, `App.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 51`** (2 nodes): `InputArea.jsx`, `InputArea()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 52`** (2 nodes): `StreamingProgress.jsx`, `StreamingProgress()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 53`** (2 nodes): `Sidebar.jsx`, `Sidebar()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 54`** (2 nodes): `utils.js`, `cn()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 55`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 56`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 57`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 58`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 59`** (1 nodes): `__init__.py`
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
- **Thin community `Community 68`** (1 nodes): `tailwind.config.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 69`** (1 nodes): `vite.config.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 70`** (1 nodes): `postcss.config.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 71`** (1 nodes): `main.jsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `PathfinderState` connect `Community 1` to `Community 0`, `Community 26`, `Community 4`?**
  _High betweenness centrality (0.065) - this node is a cross-community bridge._
- **Are the 38 inferred relationships involving `ProfileTextInput` (e.g. with `Normalize a raw student record into the API response shape.` and `Normalize a stored memory record into a saved recommendation response.`) actually correct?**
  _`ProfileTextInput` has 38 INFERRED edges - model-reasoned connections that need verification._
- **Are the 38 inferred relationships involving `ProfileUpdate` (e.g. with `Normalize a raw student record into the API response shape.` and `Normalize a stored memory record into a saved recommendation response.`) actually correct?**
  _`ProfileUpdate` has 38 INFERRED edges - model-reasoned connections that need verification._
- **Are the 38 inferred relationships involving `EntityUpdate` (e.g. with `Normalize a raw student record into the API response shape.` and `Normalize a stored memory record into a saved recommendation response.`) actually correct?**
  _`EntityUpdate` has 38 INFERRED edges - model-reasoned connections that need verification._
- **Are the 38 inferred relationships involving `ProfileCreate` (e.g. with `Normalize a raw student record into the API response shape.` and `Normalize a stored memory record into a saved recommendation response.`) actually correct?**
  _`ProfileCreate` has 38 INFERRED edges - model-reasoned connections that need verification._
- **Are the 38 inferred relationships involving `SettingsUpdate` (e.g. with `Normalize a raw student record into the API response shape.` and `Normalize a stored memory record into a saved recommendation response.`) actually correct?**
  _`SettingsUpdate` has 38 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Pathfinder FastAPI application entry point.`, `Startup and shutdown tasks.`, `Shared tool registry package for Pathfinder.` to the rest of the system?**
  _281 weakly-connected nodes found - possible documentation gaps or missing edges._