"""Thin responder for the simplified Pathfinder flow."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from app.core.state import PathfinderState


async def responder(state: PathfinderState) -> PathfinderState:
    """Render the final answer"""
    step_progress = list(state.get("step_progress", []))

    prior_messages = list(state.get("messages", []) or [])

    if state.get("is_blocked"):
        block_reason = str(state.get("block_reason", "") or "Your request was blocked.")
        return {
            **state,
            "final_answer": block_reason,
            "messages": [*prior_messages, AIMessage(content=block_reason)],
            "step_progress": step_progress,
        }

    specialist_output = state.get("specialist_output", {}) if isinstance(state.get("specialist_output", {}), dict) else {}
    final_answer = str(state.get("final_answer", "") or specialist_output.get("message", "") or "").strip()
    if not final_answer:
        final_answer = "I could not generate a response."

    step_progress.append("Response ready!")
    return {
        **state,
        "final_answer": final_answer,
        "messages": [*prior_messages, AIMessage(content=final_answer)],
        "step_progress": step_progress,
    }
