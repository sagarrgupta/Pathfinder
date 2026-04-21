"""Saves rolling context so future turns remember this one.

Pathfinder has two running summaries:
- `session_context`: short summary of the current chat; lives in the
  LangGraph checkpointer state and resets when the session ends.
- `long_context`: durable student-scoped notes that survive across
  sessions; stored as a property on the Student node in Neo4j.

The specialist proposes updates via its `respond` tool output. This node
commits those proposals: session context always goes to state, long
context goes to the graph only when the specialist actually supplied a
new value (so we don't overwrite past notes with nothing).

Runs right after `response_validator` and right before `responder`, so the
user sees the final answer quickly even if the graph write is slow.
"""

from __future__ import annotations

import logging

from app.adapters.neo4j.graphDB import GraphDB
from app.core.state import PathfinderState
from app.tools.graph_tools import get_driver as get_graph_driver
from app.utils.progress import add_progress

log = logging.getLogger("pathfinder.agents.context_persister")


async def context_persister(state: PathfinderState) -> PathfinderState:
    """Persist the specialist's proposed context updates before rendering."""
    output = state.get("specialist_output", {}) if isinstance(state.get("specialist_output", {}), dict) else {}
    # Specialist normalization already guarantees a non-empty
    # `next_session_context`; the `or state.get(...)` path is defensive for
    # unit tests that construct state manually.
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

    # Only touch Neo4j when the specialist actually produced new durable
    # notes — otherwise we leave the stored long_context alone.
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
            # A failed write must not block the answer; we just log it and
            # continue with the previous stored value.
            log.warning("Failed to persist long context for student=%s: %s", state.get("student_id", ""), exc)

    add_progress(
        step_progress,
        stage="Updating session memory",
        message="Saving the conversation context for future turns.",
    )
    updated_state["step_progress"] = step_progress
    return updated_state
