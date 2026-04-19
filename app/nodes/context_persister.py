"""saves session and long context into the graph."""

from __future__ import annotations

import logging

from app.adapters.neo4j.graphDB import GraphDB
from app.core.state import PathfinderState
from app.tools.graph_tools import get_driver as get_graph_driver
from app.utils.progress import add_progress

log = logging.getLogger("pathfinder.agents.context_persister")


async def context_persister(state: PathfinderState) -> PathfinderState:
    """saves next session context and optional next long context before response rendering."""
    output = state.get("specialist_output", {}) if isinstance(state.get("specialist_output", {}), dict) else {}
    # `specialist_runner._normalize_specialist_payload` already guarantees a
    # non-empty `next_session_context` (it falls back to the previous one and
    # logs there). This second fallback is purely defensive in case the
    # specialist normalization is ever bypassed.
    next_session_context = str(
        output.get("next_session_context", "") or state.get("session_context", "") or ""
    ).strip()
    next_long_context = output.get("next_long_context")

    step_progress = list(state.get("step_progress", []))
    updated_state = {
        **state,
        "session_context": next_session_context,
        "long_context": str(state.get("long_context", "") or ""),
    }

    if next_long_context not in (None, "", [], {}):
        try:
            long_context_text = str(next_long_context).strip()
            graph_db = GraphDB(await get_graph_driver())
            await graph_db.update_student(
                student_id=str(state.get("student_id", "") or ""),
                updates={"long_context": long_context_text},
            )
            updated_state["long_context"] = long_context_text
        except Exception as exc:
            log.warning("Failed to persist long context for student=%s: %s", state.get("student_id", ""), exc)

    add_progress(
        step_progress,
        stage="Saving helpful context",
        message="Keeping useful details ready for future questions.",
    )
    updated_state["step_progress"] = step_progress
    return updated_state
