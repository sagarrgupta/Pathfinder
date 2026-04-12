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
    reasoning: str                            # User-selected reasoning effort for local LLM calls
    request_plan: dict[str, Any]              # Deterministic request-planning hints for this turn

    # ── Orchestrator output ─────────────────────────────────────
    selected_specialist: str                  # Single specialist selected for this turn
    routing_scores: dict[str, float]          # Raw specialist routing scores
    routing_reason: str                       # Human-readable routing explanation
    next_node: str                            # Next node to route to
    session_summary: dict[str, Any]           # Normalized summary of session/profile context
    dependency_status: dict[str, Any]         # Health snapshot for external dependencies
    recovery_events: list[dict[str, Any]]     # Structured recovery/degradation events for this turn
    stop_reason: str                          # Why a turn stopped early or partially
    durable_profile_facts: dict[str, Any]     # Small durable fact snapshot exposed up front

    # ── Data gathered by nodes ──────────────────────────────────
    profile_data: dict[str, Any]              # Student profile from Neo4j KG
    retrieved_documents: list[dict[str, Any]] # Chunks from Neo4j vector search
    web_results: list[dict[str, Any]]         # Results from web search
    semantic_memory: dict[str, Any]           # Retrieved candidate facts/memory items/evidence
    latest_ingestion_result: dict[str, Any]   # Last in-turn memory ingestion summary for debugging/tracing
    extracted_entities: list[dict[str, Any]]  # Entities extracted from documents
    document_roles: list[dict[str, Any]]      # Inferred semantic roles for uploaded documents
    transcript_states: list[dict[str, Any]]   # Structured transcript state derived from uploaded transcripts
    tool_call_log: list[dict[str, Any]]       # Provenance log of tool calls/results used this turn
    specialist_output: dict[str, Any]         # Structured result from the selected specialist
    long_context_payload: dict[str, Any]      # Durable long-context payload passed to the specialist

    # ── Evaluation ──────────────────────────────────────────────
    draft_answer: str                         # Answer before evaluation
    confidence_score: float                   # 0.0 to 1.0
    is_grounded: bool                         # Whether answer is grounded in sources
    citations: list[dict[str, Any]]           # Sources for the answer

    # ── Output ──────────────────────────────────────────────────
    final_answer: str                         # Final formatted answer
    step_progress: list[str]                  # Progress messages for SSE streaming

    # ── Guard ───────────────────────────────────────────────────
    is_blocked: bool                          # Whether input was blocked by guard
    block_reason: str                         # Why input was blocked
    topic_guard_enabled: bool                 # Whether topic filtering is active
