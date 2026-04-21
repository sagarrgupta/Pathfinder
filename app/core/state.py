"""The shared "clipboard" that every node on the LangGraph flow reads and writes.

Pathfinder processes a chat turn as a sequence of small steps (input guard,
orchestrator, ingestion, specialist, validator, responder). Each step is a
plain async function that takes this dictionary in and returns an updated
copy. Because the shape is typed here in one place, any node can see what
fields exist, who fills them in, and who consumes them later.

The `messages` field uses LangGraph's `add_messages` reducer so chat history
accumulates across turns automatically instead of being overwritten.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


class UploadedFile(TypedDict, total=False):
    """One file attached to the current chat turn.

    Carried through the state until `doc_analyst` extracts text, chunks it,
    and persists it to Neo4j; after that the list is cleared so later turns
    do not reprocess the same upload.
    """
    filename: str
    content: bytes
    size: int
    content_type: str


class PathfinderState(TypedDict, total=False):
    """Everything one chat turn may produce, consume, or pass along.

    Fields are grouped by who fills them in. `total=False` means individual
    nodes only set the fields they care about; downstream nodes use
    `state.get(..., default)` to stay robust when an upstream node didn't
    run (for example, when the input guard blocked the turn early).
    """

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
    input_session_context: str                # Session context that was passed into this turn
    input_long_context: str                   # Long context that was passed into this turn
    session_context: str                      # Stored session-scoped summary carried across turns
    long_context: str                         # Stored student-scoped summary carried across turns
    student_schema: dict[str, Any]            # Canonical bounded student graph schema manifest
    latest_ingestion_result: dict[str, Any]   # Last document-ingestion summary for debugging/replays
    latest_query_ingestion_result: dict[str, Any]  # Last opportunistic chat-message ingestion summary
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
