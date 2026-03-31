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
    interpreted_query: str                    # LLM-expanded helper version of the user request
    interpreted_goal: str                     # LLM-inferred user goal for this turn
    interpreted_constraints: list[str]        # LLM-inferred constraints or preferences for this turn
    interpreted_search_brief: str             # LLM-inferred search/research brief when helpful
    interpretation_notes: str                 # Short explanation of how the query was interpreted
    task_type: str                            # Question task type within domain
    reasoning_depth: str                      # light|standard|deep
    needs_web: bool                           # Whether fresh external information is required
    needs_documents: bool                     # Whether attached or stored docs should be prioritized
    needs_profile: bool                       # Whether profile memory should be used
    planner_trace: list[str]                  # Planner execution notes
    active_capabilities: list[str]            # Selected capability agent path
    answer_style: str                         # direct_specialist|composed

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
    web_search_hint: str                      # Planner-provided goal for web research
    extracted_entities: list[dict[str, Any]]  # Entities extracted from documents
    semantic_memory: dict[str, list[dict[str, Any]]]  # Candidate facts, evidence, memory items
    memory_pack: dict[str, Any]               # Retrieval output bundle
    conflicts: list[dict[str, Any]]           # Active conflicting memories
    conflict_nudges: list[dict[str, Any]]     # One-time user-facing conflict nudges
    saved_recommendations: list[dict[str, Any]]  # Prior saved plans/recommendations to revisit
    recommended_actions: list[str]            # Action plan steps
    retrieval_sources: list[str]              # Sources selected for this answer
    retrieval_summary: dict[str, Any]         # Counts and source mix for observability

    # ── Evaluation ──────────────────────────────────────────────
    draft_answer: str                         # Answer before evaluation
    confidence_score: float                   # 0.0 to 1.0
    is_grounded: bool                         # Whether answer is grounded in sources
    profile_updates: list[dict[str, Any]]     # Profile updates detected from conversation
    latest_ingestion_result: dict[str, Any]   # Most recent memory-ingestion output for current turn
    citations: list[dict[str, Any]]           # Sources for the answer

    # ── Output ──────────────────────────────────────────────────
    final_answer: str                         # Final formatted answer
    step_progress: list[str]                  # Progress messages for SSE streaming
    answer_rationale: list[str]               # Why this answer path/sources were chosen
    consolidation_summary: dict[str, Any]     # Memory consolidation output
    execution_trace: list[dict[str, Any]]     # Per-question structured execution trace

    # ── Guard ───────────────────────────────────────────────────
    is_blocked: bool                          # Whether input was blocked by guard
    block_reason: str                         # Why input was blocked
    topic_guard_enabled: bool                 # Whether topic filtering is active
