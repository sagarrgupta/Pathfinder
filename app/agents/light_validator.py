"""Lightweight post-specialist validator."""

from __future__ import annotations

from typing import Any

from app.core.state import PathfinderState


def _citations_from_tool_log(tool_log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    citations = []
    for item in tool_log:
        if not isinstance(item, dict) or item.get("status") != "ok":
            continue
        summary = item.get("result_summary", {})
        if not isinstance(summary, dict):
            continue
        url = ""
        title = ""
        if isinstance(summary.get("result", {}), dict):
            payload = summary.get("result", {})
            url = str(payload.get("url", "") or "")
            title = str(payload.get("title", "") or "")
        url = url or str(summary.get("url", "") or "")
        title = title or str(summary.get("title", "") or "")
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
    return deduped[:8]


async def light_validator(state: PathfinderState) -> PathfinderState:
    """Validate specialist output shape without rewriting the answer."""
    output = state.get("specialist_output", {}) if isinstance(state.get("specialist_output", {}), dict) else {}
    message = str(output.get("message", "") or state.get("draft_answer", "") or "").strip()
    if not message:
        message = "I could not generate a response."

    tool_call_log = list(state.get("tool_call_log", []))
    citations = _citations_from_tool_log(tool_call_log)
    step_progress = list(state.get("step_progress", []))
    step_progress.append("Validated response structure and tool provenance")

    stop_reason = str(output.get("stop_reason", "") or "")
    if any(item.get("status") == "ok" for item in tool_call_log if isinstance(item, dict)):
        confidence = 0.82
    elif stop_reason == "stop":
        confidence = 0.9
    else:
        confidence = 0.62
    return {
        **state,
        "draft_answer": message,
        "final_answer": "",
        "specialist_output": {
            "message": message,
            "memory_patch": output.get("memory_patch"),
            "provenance": output.get("provenance", []),
            "stop_reason": stop_reason,
        },
        "citations": citations,
        "confidence_score": confidence,
        "is_grounded": bool(citations) or not tool_call_log,
        "stop_reason": stop_reason,
        "step_progress": step_progress,
        "next_node": "responder",
    }
