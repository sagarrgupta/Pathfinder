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

    # ── Orchestrator output ─────────────────────────────────────
    intent: str                               # Classified intent
    plan: list[str]                           # Ordered list of agent nodes to execute
    next_node: str                            # Next node to route to
    missing_info: list[str]                   # Info the system needs but doesn't have
    session_summary: dict[str, Any]           # Normalized summary of session/profile context
    workflow: str                             # General student workflow for this turn
    target_entity: dict[str, Any]             # Normalized target the user is asking about
    source_policy: dict[str, Any]             # Retrieval/extraction strategy for the current query
    task_graph: list[dict[str, Any]]          # Ordered dependency-aware task graph for the current turn
    working_memory: dict[str, Any]            # Shared reasoning substrate across nodes
    handoff_notes: list[dict[str, Any]]       # Explicit inter-node handoff contracts/notes
    source_audit: list[dict[str, Any]]        # Selected/rejected source audit trail
    dependency_status: dict[str, Any]         # Health snapshot for external dependencies
    blocked_reasons: list[str]                # Explicit blockers surfaced by planners/evaluator
    trace_summary: dict[str, Any]             # Compact execution trace for debugging/UX
    compacted_session: dict[str, Any]         # Long-term condensed advising state
    short_memory_policy: dict[str, Any]       # Explicit TTL/eviction policy for short-term session memory
    stop_reason: str                          # Why a turn stopped early or partially

    # ── Data gathered by nodes ──────────────────────────────────
    profile_data: dict[str, Any]              # Student profile from Neo4j KG
    retrieved_documents: list[dict[str, Any]] # Chunks from Neo4j vector search
    graph_results: list[dict[str, Any]]       # Structured results from graph queries
    web_results: list[dict[str, Any]]         # Results from web search
    semantic_memory: dict[str, Any]           # Retrieved candidate facts/memory items/evidence
    memory_pack: dict[str, Any]               # Compact retrieval pack for downstream reasoning
    latest_ingestion_result: dict[str, Any]   # Last in-turn memory ingestion summary for debugging/tracing
    conflicts: list[dict[str, Any]]           # Retrieved memory/profile conflicts for the current turn
    extracted_entities: list[dict[str, Any]]  # Entities extracted from documents
    evidence_records: list[dict[str, Any]]    # Typed evidence extracted from web/profile/doc sources
    decision_payload: dict[str, Any]          # Structured planner output used for final response

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
