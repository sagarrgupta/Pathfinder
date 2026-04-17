"""Shared state schema for the LangGraph StateGraph.

All agent nodes read from and write to this typed dictionary.
LangGraph manages message accumulation via the ``add_messages`` reducer.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

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
    reasoning: str                            # User-selected reasoning effort for local LLM calls
    request_plan: dict[str, Any]              # Deterministic request-planning hints for this turn

    # ── Orchestrator output ─────────────────────────────────────
    selected_specialist: str                  # Single specialist selected for this turn
    routing_scores: dict[str, float]          # Raw specialist routing scores
    routing_reason: str                       # Human-readable routing explanation
    next_node: str                            # Next node to route to
    session_summary: dict[str, Any]           # Normalized summary of session/student context
    recovery_events: list[dict[str, Any]]     # Structured recovery/degradation events for this turn
    stop_reason: str                          # Why a turn stopped early or partially

    # ── Data gathered by nodes ──────────────────────────────────
    profile_data: dict[str, Any]              # Current student graph snapshot from Neo4j
    retrieved_documents: list[dict[str, Any]] # Retrieved chunk evidence from vector/graph search
    latest_ingestion_result: dict[str, Any]   # Last document-ingestion summary for debugging/replays
    tool_call_log: list[dict[str, Any]]       # Provenance log of tool calls/results used this turn
    specialist_output: dict[str, Any]         # Structured result from the selected specialist
    long_context_payload: dict[str, Any]      # Durable long-context payload passed to the specialist

    # ── Evaluation ──────────────────────────────────────────────
    draft_answer: str                         # Answer before evaluation
    confidence_score: float                   # 0.0 to 1.0
    citations: list[dict[str, Any]]           # Sources for the answer

    # ── Output ──────────────────────────────────────────────────
    final_answer: str                         # Final formatted answer
    step_progress: list[str]                  # Progress messages for SSE streaming

    # ── Guard ───────────────────────────────────────────────────
    is_blocked: bool                          # Whether input was blocked by guard
    block_reason: str                         # Why input was blocked
    topic_guard_enabled: bool                 # Whether topic filtering is active
