"""Polishes the specialist's output before it reaches the user.

After `specialist_runner` finishes its tool-calling loop, this node:
- guarantees a non-empty answer string (fallback if the model returned nothing),
- builds a deduplicated list of citations from web-search / fetch tool calls,
- re-exports the canonical `specialist_output` shape for downstream nodes.

It is intentionally lightweight — no extra LLM calls — so it cannot
introduce new failure modes; think of it as a janitor, not a second pass.
"""

from __future__ import annotations

from typing import Any

from app.core.state import PathfinderState
from app.utils.progress import add_progress


def _citations_from_tool_log(tool_log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pick source URLs/titles out of successful web tool calls.

    The tool transcript is already compact, so we just scan for items that
    expose a `url` or `title`. Duplicates (same title+url) are dropped so
    the UI doesn't show the same reference three times.
    """
    citations = []
    for item in tool_log:
        if not isinstance(item, dict) or item.get("status") != "ok":
            continue
        summary = item.get("result_summary", {})
        if not isinstance(summary, dict):
            continue
        compact = dict(summary.get("summary") or summary)
        url = str(compact.get("url", "") or "")
        title = str(compact.get("title", "") or "")
        if url or title:
            citations.append({"title": title, "url": url, "tool": item.get("tool", "")})
    deduped = []
    seen = set()
    for citation in citations:
        key = (citation.get("title", ""), citation.get("url", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(citation)
    # Cap at 8 — more than that and the UI gets noisy.
    return deduped[:8]


async def response_validator(state: PathfinderState) -> PathfinderState:
    """Clean up the specialist output and attach citations."""
    output = state.get("specialist_output", {}) if isinstance(state.get("specialist_output", {}), dict) else {}
    message = str(output.get("message", "") or "").strip()
    if not message:
        message = "I could not generate a response."

    tool_call_log = list(state.get("tool_call_log", []))
    citations = _citations_from_tool_log(tool_call_log)
    step_progress = list(state.get("step_progress", []))
    add_progress(
        step_progress,
        stage="Preparing your answer",
        message="Final checks on the response and sources.",
    )

    stop_reason = str(output.get("stop_reason", "") or "")
    return {
        **state,
        "final_answer": message,
        "specialist_output": {
            "message": message,
            "stop_reason": stop_reason,
            "next_session_context": str(output.get("next_session_context", "") or state.get("session_context", "") or ""),
            "next_long_context": output.get("next_long_context"),
        },
        "citations": citations,
        "stop_reason": stop_reason,
        "step_progress": step_progress,
    }
