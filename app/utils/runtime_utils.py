"""Runtime helpers for conversation context and replay summaries."""

from __future__ import annotations

from typing import Any

from app.tools.tools import summarize_tool_usage


def _message_role_and_content(message: Any) -> tuple[str, str]:
    """Extract a normalized role/content pair from a stored message value."""
    if isinstance(message, tuple) and len(message) == 2:
        return str(message[0] or ""), str(message[1] or "").strip()
    if hasattr(message, "content"):
        role = str(getattr(message, "type", "") or getattr(message, "role", "") or "")
        content = str(getattr(message, "content", "") or "").strip()
        return role, content
    return "", ""


def build_recent_conversation_window(messages: list[Any], limit: int = 8) -> list[dict[str, str]]:
    """Normalize recent turns into a role/content list for tools and prompts."""
    recent_messages: list[dict[str, str]] = []
    for message in messages[-limit:]:
        role_name, content = _message_role_and_content(message)
        if not role_name:
            continue
        role = "user" if role_name in {"human", "user"} else "assistant"
        recent_messages.append({"role": role, "content": content})
    return recent_messages


def _successful_tool_names(state: dict[str, Any]) -> list[str]:
    """Return successful tool names from the turn, including ingestion sub-steps."""
    tool_call_log = list(state.get("tool_call_log", []) or [])
    latest_ingestion = dict(state.get("latest_ingestion_result", {}) or {})
    ingestion_documents = list(latest_ingestion.get("documents", []) or [])
    for item in ingestion_documents:
        if not isinstance(item, dict):
            continue
        ingestion_result = dict(item.get("ingestion_result") or {})
        tool_call_log.extend(list(ingestion_result.get("tool_call_log", []) or []))
    return [
        str(item.get("tool", "") or "")
        for item in tool_call_log
        if isinstance(item, dict) and item.get("status") == "ok"
    ]


def infer_method(state: dict[str, Any]) -> str:
    """Return the high-level retrieval method used for this turn."""
    return summarize_tool_usage(_successful_tool_names(state)).get("method", "direct")
