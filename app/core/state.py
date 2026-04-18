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

    # ── Orchestrator output ─────────────────────────────────────
    selected_specialist: str                  # Single specialist selected for this turn
    routing_scores: dict[str, float]          # Raw specialist routing scores
    routing_reason: str                       # Human-readable routing explanation
    processing_issues: list[dict[str, Any]]   # Structured degraded-processing events for this turn
    stop_reason: str                          # Why a turn stopped early or partially

    # ── Data gathered by nodes ──────────────────────────────────
    session_context: str                      # Stored session-scoped summary carried across turns
    long_context: str                         # Stored student-scoped summary carried across turns
    student_schema: dict[str, Any]            # Canonical bounded student graph schema manifest
    latest_ingestion_result: dict[str, Any]   # Last document-ingestion summary for debugging/replays
    tool_call_log: list[dict[str, Any]]       # Provenance log of tool calls/results used this turn
    specialist_output: dict[str, Any]         # Structured result from the selected specialist

    # ── Evaluation ──────────────────────────────────────────────
    citations: list[dict[str, Any]]           # Sources for the answer

    # ── Output ──────────────────────────────────────────────────
    final_answer: str                         # Final formatted answer
    step_progress: list[str]                  # Progress messages for SSE streaming

    # ── Guard ───────────────────────────────────────────────────
    is_blocked: bool                          # Whether input was blocked by guard
    block_reason: str                         # Why input was blocked
    topic_guard_enabled: bool                 # Whether topic filtering is active
