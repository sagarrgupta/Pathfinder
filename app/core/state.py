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
    retrieval_mode: str                       # Active retrieval strategy for this turn
    compare_mode: bool                        # Whether this turn is a 3-way retrieval comparison

    # ── Orchestrator output ─────────────────────────────────────
    intent: str                               # Classified intent
    plan: list[str]                           # Ordered list of agent nodes to execute
    next_node: str                            # Next node to route to
    missing_info: list[str]                   # Info the system needs but doesn't have

    # ── Data gathered by nodes ──────────────────────────────────
    profile_data: dict[str, Any]              # Student profile from Neo4j KG
    retrieved_documents: list[dict[str, Any]] # Chunks from Neo4j vector search
    graph_results: list[dict[str, Any]]       # Structured results from graph queries
    web_results: list[dict[str, Any]]         # Results from web search
    extracted_entities: list[dict[str, Any]]  # Entities extracted from documents
    retrieval_stats: dict[str, Any]           # Stats for the selected retrieval mode
    retrieval_comparison: dict[str, Any]      # Optional side-by-side retrieval benchmark data

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
