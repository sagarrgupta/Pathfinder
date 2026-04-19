"""Opportunistic chat-message ingestion node.

Runs after `orchestrator` and before `specialist_runner`, so any durable
facts the student reveals in the current message are already persisted by
the time the specialist reads the graph to answer. Mirrors the document
ingestion loop and tool-call discipline. Unlike document ingestion there
is no chunk write or document/chunk grounding — chat turns have no
document to attach to, so only graph structure (sections, entities,
fields, relations) is written.
"""

from __future__ import annotations

import logging

from app.core.state import PathfinderState
from app.utils.progress import add_progress
from app.utils.query_ingest import ingest_query

log = logging.getLogger("pathfinder.nodes.query_ingestor")


async def query_ingestor(state: PathfinderState) -> PathfinderState:
    """Opportunistically ingest durable info from the user's chat message into the graph."""
    step_progress = list(state.get("step_progress", []))
    processing_issues = list(state.get("processing_issues", []))

    if state.get("is_blocked"):
        return {**state, "step_progress": step_progress}

    student_id = str(state.get("student_id", "") or "")
    session_id = str(state.get("session_id", "") or "")
    query = str(state.get("query", "") or "").strip()
    if not student_id or not query:
        return {**state, "step_progress": step_progress}

    add_progress(
        step_progress,
        stage="Saving helpful context",
        message="Looking for any new student details to remember.",
    )

    try:
        applied = await ingest_query(
            student_id=student_id,
            session_id=session_id or None,
            query=query,
        )
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
