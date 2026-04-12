"""Shared state schema for the LangGraph StateGraph.

All agent nodes read from and write to this typed dictionary.
LangGraph manages message accumulation via the ``add_messages`` reducer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph.message import add_messages


class UploadedFile(TypedDict, total=False):
    """Metadata for a file uploaded in the current turn."""
    filename: str
    content: bytes
    size: int
    content_type: str


class PathfinderState(TypedDict, total=False):
    """Shared state flowing through the LangGraph StateGraph."""

    # ── Input ───────────────────────────────────────────────────
    messages: Annotated[list, add_messages]  # Conversation history (LangGraph managed)
    query: str                                # Current user query
    files: list[UploadedFile]                 # Files uploaded in this turn
    session_id: str                           # Chat session ID
    student_id: str                           # Student identifier
    is_global_upload: bool                    # Whether uploaded docs go to global profile
    advisor_mode: str                         # User-selected focused advisor mode
    request_plan: dict[str, Any]              # Deterministic request-planning hints for this turn
    runtime_policy: dict[str, Any]            # Explicit runtime policy decisions for this turn
    runtime_snapshot: dict[str, Any]          # Runtime capability snapshot for this turn

    # ── Orchestrator output ─────────────────────────────────────
    intent: str                               # Classified intent
    plan: list[str]                           # Ordered list of agent nodes to execute
    next_node: str                            # Next node to route to
    missing_info: list[str]                   # Info the system needs but doesn't have
    session_summary: dict[str, Any]           # Normalized summary of session/profile context
    workflow: str                             # General student workflow for this turn
    student_strategy: dict[str, Any]          # What the student is optimizing for right now
    student_operating_model: dict[str, Any]   # How the student tends to make tradeoffs
    recommendation_outcome_profile: dict[str, Any]  # How the student tends to respond to past recommendations
    decision_continuity: dict[str, Any]       # Whether this turn continues a prior decision plan
    target_entity: dict[str, Any]             # Normalized target the user is asking about
    source_policy: dict[str, Any]             # Retrieval/extraction strategy for the current query
    task_graph: list[dict[str, Any]]          # Ordered dependency-aware task graph for the current turn
    working_memory: dict[str, Any]            # Shared reasoning substrate across nodes
    dependency_status: dict[str, Any]         # Health snapshot for external dependencies
    recovery_events: list[dict[str, Any]]     # Structured recovery/degradation events for this turn
    blocked_reasons: list[str]                # Explicit blockers surfaced by planners/evaluator
    trace_summary: dict[str, Any]             # Compact execution trace for debugging/UX
    compacted_session: dict[str, Any]         # Long-term condensed advising state
    session_memory: dict[str, Any]            # Session-scoped transcript/carry-forward memory
    short_memory_policy: dict[str, Any]       # Explicit TTL/eviction policy for short-term session memory
    stop_reason: str                          # Why a turn stopped early or partially

    # ── Data gathered by nodes ──────────────────────────────────
    profile_data: dict[str, Any]              # Student profile from Neo4j KG
    retrieved_documents: list[dict[str, Any]] # Chunks from Neo4j vector search
    web_results: list[dict[str, Any]]         # Results from web search
    semantic_memory: dict[str, Any]           # Retrieved candidate facts/memory items/evidence
    memory_pack: dict[str, Any]               # Compact retrieval pack for downstream reasoning
    evidence_pack: dict[str, Any]             # Normalized evidence envelope for downstream reasoning
    latest_ingestion_result: dict[str, Any]   # Last in-turn memory ingestion summary for debugging/tracing
    conflicts: list[dict[str, Any]]           # Retrieved memory/profile conflicts for the current turn
    extracted_entities: list[dict[str, Any]]  # Entities extracted from documents
    document_roles: list[dict[str, Any]]      # Inferred semantic roles for uploaded documents
    transcript_states: list[dict[str, Any]]   # Structured transcript state derived from uploaded transcripts
    targeted_web_questions: list[str]         # Gap-driven follow-up questions for web research
    evidence_records: list[dict[str, Any]]    # Typed evidence extracted from web/profile/doc sources
    decision_payload: dict[str, Any]          # Structured planner output used for final response
    tool_call_log: list[dict[str, Any]]       # Provenance log of tool calls/results used this turn
    mcp_tool_calls: list[dict[str, Any]]      # MCP tool call trace for the current turn

    # ── Evaluation ──────────────────────────────────────────────
    draft_answer: str                         # Answer before evaluation
    confidence_score: float                   # 0.0 to 1.0
    is_grounded: bool                         # Whether answer is grounded in sources
    profile_updates: list[dict[str, Any]]     # Profile updates detected from conversation
    citations: list[dict[str, Any]]           # Sources for the answer

    # ── Output ──────────────────────────────────────────────────
    final_answer: str                         # Final formatted answer
    step_progress: list[str]                  # Progress messages for SSE streaming

    # ── Guard ───────────────────────────────────────────────────
    is_blocked: bool                          # Whether input was blocked by guard
    block_reason: str                         # Why input was blocked
    topic_guard_enabled: bool                 # Whether topic filtering is active
