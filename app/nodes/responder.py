"""Last stop in the flow — packages the answer for the client.

Every other node has already done the heavy lifting (guarding, routing,
ingesting, answering, validating, saving context). By the time we get
here, the final text already exists somewhere in the state; this node's
only job is to pick the right string, append it to the chat history as
an AIMessage, and emit the "done" progress line.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from app.core.state import PathfinderState
from app.utils.progress import add_progress


async def responder(state: PathfinderState) -> PathfinderState:
    """Finalize the chat history and return the text the UI will show."""
    step_progress = list(state.get("step_progress", []))
    prior_messages = list(state.get("messages", []) or [])

    # Blocked turns bypass everything else — show the guard's reason instead
    # of pretending to answer.
    if state.get("is_blocked"):
        block_reason = str(state.get("block_reason", "") or "Your request was blocked.")
        return {
            **state,
            "final_answer": block_reason,
            "messages": [*prior_messages, AIMessage(content=block_reason)],
            "step_progress": step_progress,
        }

    # Prefer the validator's cleaned `final_answer`; fall back to the raw
    # specialist message if for some reason the validator didn't run.
    specialist_output = state.get("specialist_output", {}) if isinstance(state.get("specialist_output", {}), dict) else {}
    final_answer = str(state.get("final_answer", "") or specialist_output.get("message", "") or "").strip()
    if not final_answer:
        final_answer = "I could not generate a response."

    add_progress(
        step_progress,
        stage="Answer ready",
        message="Sharing the final response now.",
    )
    return {
        **state,
        "final_answer": final_answer,
        # Append the assistant turn so the next message sees full history.
        "messages": [*prior_messages, AIMessage(content=final_answer)],
        "step_progress": step_progress,
    }
