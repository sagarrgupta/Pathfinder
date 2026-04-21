"""Small helpers for shaping chat-turn state into downstream-friendly shapes.

Two unrelated-but-cheap helpers live here:
- `build_recent_conversation_window` flattens the LangGraph message
  history into a simple `[{"role","content"}, ...]` list that tool
  prompts and specialists can reason about without importing
  `langchain_core`.
- `infer_method` walks every successful tool call in a turn (including
  the ingestion sub-steps nested inside `latest_ingestion_result`) and
  asks `summarize_tool_usage` to name the dominant retrieval strategy.
  The chat endpoint sticks that label into the `done` SSE payload so
  the UI can show e.g. "answered via hybrid search".
"""

from __future__ import annotations

from typing import Any

from app.tools.tools import summarize_tool_usage


def _message_role_and_content(message: Any) -> tuple[str, str]:
    """Pull `(role, content)` out of whichever message shape the graph stored.

    LangGraph state can carry either `langchain_core` message objects
    (with `.type`/`.role` + `.content`) or plain `(role, content)`
    tuples — we normalize both to the same pair so callers don't have
    to care which one landed in state.
    """
    if isinstance(message, tuple) and len(message) == 2:
        return str(message[0] or ""), str(message[1] or "").strip()
    if hasattr(message, "content"):
        role = str(getattr(message, "type", "") or getattr(message, "role", "") or "")
        content = str(getattr(message, "content", "") or "").strip()
        return role, content
    return "", ""


def build_recent_conversation_window(messages: list[Any], limit: int = 8) -> list[dict[str, str]]:
    """Last N turns of the conversation, normalized for prompts / tool context.

    Maps every non-user role down to `"assistant"` because tool prompts
    and specialist profiles only care about the two-way exchange — the
    internal node names ("orchestrator", "ingester", ...) would just
    confuse the LLM if surfaced.
    """
    recent_messages: list[dict[str, str]] = []
    for message in messages[-limit:]:
        role_name, content = _message_role_and_content(message)
        if not role_name:
            continue
        role = "user" if role_name in {"human", "user"} else "assistant"
        recent_messages.append({"role": role, "content": content})
    return recent_messages


def _successful_tool_names(state: dict[str, Any]) -> list[str]:
    """Every tool name that succeeded on this turn, including nested ingestion calls.

    The specialist's own tool calls live in `state["tool_call_log"]`,
    but doc ingestion and chat-query ingestion each keep their own
    separate tool call logs inside their result payloads. We flatten
    all three sources so the "method" inference sees the whole picture.
    """
    tool_call_log = list(state.get("tool_call_log", []) or [])
    latest_ingestion = dict(state.get("latest_ingestion_result", {}) or {})
    ingestion_documents = list(latest_ingestion.get("documents", []) or [])
    for item in ingestion_documents:
        if not isinstance(item, dict):
            continue
        ingestion_result = dict(item.get("ingestion_result") or {})
        tool_call_log.extend(list(ingestion_result.get("tool_call_log", []) or []))
    latest_query_ingestion = dict(state.get("latest_query_ingestion_result", {}) or {})
    tool_call_log.extend(list(latest_query_ingestion.get("tool_call_log", []) or []))
    return [
        str(item.get("tool", "") or "")
        for item in tool_call_log
        if isinstance(item, dict) and item.get("status") == "ok"
    ]


def infer_method(state: dict[str, Any]) -> str:
    """One-word label for how this turn arrived at its answer.

    Values come from `summarize_tool_usage` — things like `hybrid`,
    `vector`, `graph`, `web`, or the default `direct` when no tools
    were used. The UI displays this as a subtle attribution under the
    assistant message.
    """
    return summarize_tool_usage(_successful_tool_names(state)).get("method", "direct")
