"""Quietly learns from whatever the student says, turn after turn.

After the orchestrator picks a specialist but before the specialist runs,
this node takes a second pass at the user's message and extracts any
durable facts worth remembering — name, major, goals, preferences, etc.
Those facts get written into the student's knowledge graph so the next
specialist call (and every future turn) sees them automatically.

Why run it here? If we waited until after the answer, the specialist
would be reading stale graph data. Running before specialist_runner means
a student can say "I'm switching to CS" mid-conversation and the answer
already reflects it.

Unlike document ingestion, we only write graph structure — no text chunks
or embeddings — because a chat message has no document to attach them to.
"""

from __future__ import annotations

import logging

from app.core.state import PathfinderState
from app.utils.query_ingest import ingest_query

log = logging.getLogger("pathfinder.nodes.query_ingestor")

async def query_ingestor(state: PathfinderState) -> PathfinderState:
    """Harvest durable facts from the user's current message into the graph.

    This is best-effort: if it fails, we record a processing issue and let
    the specialist answer using whatever is already in the graph. We never
    block the turn on ingestion errors.
    """
    step_progress = list(state.get("step_progress", []))
    processing_issues = list(state.get("processing_issues", []))

    # Nothing to learn from a blocked turn — bail early.
    if state.get("is_blocked"):
        return {**state, "step_progress": step_progress}

    student_id = str(state.get("student_id", "") or "")
    session_id = str(state.get("session_id", "") or "")
    query = str(state.get("query", "") or "").strip()
    if not student_id or not query:
        return {**state, "step_progress": step_progress}

    try:
        # Delegate the tool-calling ingestion loop to the shared helper.
        applied = await ingest_query(
            student_id=student_id,
            session_id=session_id or None,
            query=query,
            step_progress=step_progress,
        )
        # Fold the helper's output into a stable shape for replay storage.
        ingestion_result = {
            "tool_call_log": list(applied.get("tool_call_log", []) or []),
            "model_summary": dict(applied.get("model_summary") or {}),
            "graph_updates": dict(applied.get("graph_updates") or {}),
            "graph_schema_after": dict(applied.get("graph_schema_after") or {}),
        }
        log.info(
            "Query ingestor: stop_reason=%s saved_items=%d for student=%s",
            ingestion_result["model_summary"].get("stop_reason", ""),
            len(ingestion_result["model_summary"].get("saved_items") or []),
            student_id,
        )
    except Exception as exc:
        # Record the failure but keep going — the answer still matters.
        log.warning("Query ingestion failed for student=%s: %s", student_id, exc)
        processing_issues.append(
            {
                "type": "query_ingestion_failed",
                "status": "degraded",
                "reason": "Opportunistic chat-message ingestion failed; the specialist will still answer using the existing graph.",
                "error": str(exc),
            }
        )
        return {
            **state,
            "processing_issues": processing_issues,
            "step_progress": step_progress,
        }

    return {
        **state,
        "latest_query_ingestion_result": ingestion_result,
        "processing_issues": processing_issues,
        "step_progress": step_progress,
    }
