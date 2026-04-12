"""Thin responder for the simplified Pathfinder flow."""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage

from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.responder")


async def responder(state: PathfinderState) -> PathfinderState:
    """Render the final answer with minimal changes."""
    step_progress = list(state.get("step_progress", []))

    if state.get("is_blocked"):
        block_reason = str(state.get("block_reason", "") or "Your request was blocked.")
        return {
            **state,
            "final_answer": block_reason,
            "messages": [AIMessage(content=block_reason)],
            "step_progress": step_progress,
        }

    final_answer = str(state.get("final_answer", "") or state.get("draft_answer", "") or "").strip()
    if not final_answer:
        final_answer = "I could not generate a response."

    step_progress.append("Response ready!")
    return {
        **state,
        "final_answer": final_answer,
        "messages": [AIMessage(content=final_answer)],
        "step_progress": step_progress,
    }
