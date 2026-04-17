"""Persistent conversation memory via LangGraph SqliteSaver.

Provides the checkpointer used by LangGraph to persist conversation
history across server restarts.
"""

from __future__ import annotations

import os
from typing import Any
from typing import Optional

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.config.settings import settings
from app.services.long_context import get_profile_entity_groups, get_profile_student

_checkpointer: Optional[AsyncSqliteSaver] = None

_SUMMARY_EXCLUDE_KEYS = {
    "id",
    "created_at",
    "updated_at",
    "long_context_summary",
    "long_context_notes",
    "completeness",
}
_NON_EVIDENCE_TOOLS = {
    "get_recent_conversation_window",
    "get_session_summary",
    "list_context_categories",
    "respond",
}
_WEB_TOOL_TOKENS = {"web", "url", "official"}
_DOCUMENT_TOOL_TOKENS = {
    "chunk",
    "chunks",
    "document",
    "documents",
    "vector",
    "similarity",
    "hybrid",
}
_GRAPH_TOOL_TOKENS = {
    "student",
    "section",
    "entity",
    "entities",
    "graph",
    "node",
    "nodes",
    "relation",
    "relations",
    "field",
    "fields",
    "schema",
    "neighbor",
    "neighbors",
    "bfs",
}


async def get_checkpointer() -> AsyncSqliteSaver:
    """Return the singleton SQLite checkpointer."""
    global _checkpointer
    if _checkpointer is None:
        # Ensure the data directory exists
        db_dir = os.path.dirname(settings.SQLITE_DB_PATH)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        conn = await aiosqlite.connect(settings.SQLITE_DB_PATH)
        _checkpointer = AsyncSqliteSaver(conn)
        await _checkpointer.setup()
    return _checkpointer


async def reset_checkpointer_storage() -> None:
    """Close checkpointer connection and remove persisted chat storage."""
    global _checkpointer
    if _checkpointer is not None:
        try:
            conn = getattr(_checkpointer, "conn", None)
            if conn is not None:
                await conn.close()
        except Exception:
            pass
        _checkpointer = None

    for suffix in ("", "-wal", "-shm"):
        path = f"{settings.SQLITE_DB_PATH}{suffix}"
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

def _summary_root_properties(profile: dict[str, Any]) -> dict[str, Any]:
    root = get_profile_student(profile)
    summary: dict[str, Any] = {}
    for key, value in root.items():
        if key in _SUMMARY_EXCLUDE_KEYS:
            continue
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        summary[str(key)] = value
    return summary


def _summary_sections(profile: dict[str, Any]) -> list[str]:
    sections = profile.get("sections", []) if isinstance(profile.get("sections"), list) else []
    values: list[str] = []
    for item in sections:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("key") or "").strip()
        if label and label not in values:
            values.append(label)
    return values


def _summary_entity_types(profile: dict[str, Any]) -> dict[str, int]:
    groups = get_profile_entity_groups(profile)
    return {
        str(label): len(items)
        for label, items in groups.items()
        if label not in {"Document", "Chunk"} and isinstance(items, list) and items
    }


def _summary_documents(profile: dict[str, Any]) -> dict[str, Any]:
    groups = get_profile_entity_groups(profile)
    documents = groups.get("Document", []) if isinstance(groups.get("Document"), list) else []
    file_groups: dict[str, int] = {}
    for item in documents:
        if not isinstance(item, dict):
            continue
        file_type = str(item.get("file_type") or "unknown")
        file_groups[file_type] = file_groups.get(file_type, 0) + 1
    return {"count": len(documents), "groups": file_groups}


def _message_role_and_content(message: Any) -> tuple[str, str]:
    if isinstance(message, tuple) and len(message) == 2:
        return str(message[0] or ""), str(message[1] or "").strip()
    if hasattr(message, "content"):
        role = str(getattr(message, "type", "") or getattr(message, "role", "") or "")
        content = str(getattr(message, "content", "") or "").strip()
        return role, content
    return "", ""


def _recent_messages(messages: list[Any], *, roles: set[str], limit: int = 6) -> list[str]:
    values: list[str] = []
    for msg in messages[-12:]:
        role, content = _message_role_and_content(msg)
        if role not in roles or not content or content in values:
            continue
        values.append(content)
    return values[-limit:]


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


def build_session_summary(profile: dict[str, Any], messages: list[Any], query: str) -> dict[str, Any]:
    """Build a graph-driven session summary without hardcoded profile schemas."""
    normalized_profile = dict(profile) if isinstance(profile, dict) else {}
    root_properties = _summary_root_properties(normalized_profile)
    section_labels = _summary_sections(normalized_profile)
    entity_types = _summary_entity_types(normalized_profile)
    documents = _summary_documents(normalized_profile)
    recent_user_messages = _recent_messages(list(messages), roles={"human", "user"})
    recent_assistant_messages = _recent_messages(list(messages), roles={"ai", "assistant"})

    summary = {
        "root_properties": {
            "known": bool(root_properties),
            "value": root_properties,
        },
        "sections": {
            "known": bool(section_labels),
            "value": section_labels,
        },
        "entity_types": {
            "known": bool(entity_types),
            "value": entity_types,
        },
        "documents": {
            "known": bool(documents["count"]),
            "value": documents,
        },
        "recent_user_context": {
            "known": bool(query or recent_user_messages),
            "value": [text for text in [str(query or "").strip(), *recent_user_messages] if text][:6],
        },
        "recent_decisions": recent_assistant_messages[-5:],
        "assumptions": [
            "Session summary is generated from current student graph properties and recent conversation context.",
        ],
    }

    return summary


def _tool_category(tool_name: str) -> str:
    normalized = str(tool_name or "").strip().lower()
    if not normalized or normalized in _NON_EVIDENCE_TOOLS:
        return ""

    tokens = {part for part in normalized.split("_") if part}
    if tokens & _WEB_TOOL_TOKENS:
        return "web"
    if tokens & _DOCUMENT_TOOL_TOKENS:
        return "docs"
    if tokens & _GRAPH_TOOL_TOKENS:
        return "graph"
    return ""


def infer_quality_path(state: dict[str, Any]) -> str:
    """Return a compact label that describes the evidence path used."""
    tool_call_log = list(state.get("tool_call_log", []) or [])
    successful_tools = [
        str(item.get("tool", "") or "")
        for item in tool_call_log
        if isinstance(item, dict) and item.get("status") == "ok"
    ]
    if not successful_tools:
        return "direct"

    path: list[str] = []
    seen: set[str] = set()
    for name in successful_tools:
        category = _tool_category(name)
        if category and category not in seen:
            seen.add(category)
            path.append(category)
    if state.get("confidence_score") is not None:
        path.append("validated")
    return "+".join(path) if path else "direct"
