"""Utility MCP tools."""

from __future__ import annotations

from typing import Any

from app.core.memory import build_recent_conversation_window, build_session_summary
from app.services.long_context import get_profile_entity_groups
from app.tools.tools import ToolContext, ToolSpec
from app.utils import coerce_bounded_int

JSON_VALUE_SCHEMA: dict[str, Any] = {
    "anyOf": [
        {"type": "string"},
        {"type": "number"},
        {"type": "integer"},
        {"type": "boolean"},
        {"type": "null"},
        {"type": "array"},
        {"type": "object"},
    ]
}


def _context_state(context: ToolContext) -> dict[str, Any]:
    return dict(context.state or {})


async def _get_recent_conversation_window(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    state = _context_state(context)
    limit = coerce_bounded_int(arguments.get("limit", 8), default=8, maximum=20)
    messages = list(state.get("messages", []))
    return {"recent_messages": build_recent_conversation_window(messages, limit=limit)}


async def _get_session_summary(_: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    state = _context_state(context)
    summary = dict(state.get("session_summary", {}) or {})
    if not summary:
        profile = dict(state.get("profile_data", {}) or {})
        summary = build_session_summary(
            profile,
            list(state.get("messages", [])),
            str(state.get("query", "") or ""),
        )
    return {"session_summary": summary}


async def _list_context_categories(_: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    state = _context_state(context)
    profile = dict(state.get("profile_data", {}) or {})
    all_entities = get_profile_entity_groups(profile)
    return {
        "categories": {
            "graph_entity_types": sorted(all_entities.keys()),
            "documents_available": len(all_entities.get("Document", [])),
            "session_context_available": bool(state),
        }
    }


async def _respond(arguments: dict[str, Any], _context: ToolContext) -> dict[str, Any]:
    return {
        "message": str(arguments.get("message", "") or ""),
        "memory_patch": arguments.get("memory_patch"),
        "provenance": arguments.get("provenance"),
        "stop_reason": str(arguments.get("stop_reason", "") or ""),
    }


def get_utility_tool_specs() -> list[ToolSpec]:
    """Return session/context utility tool definitions."""
    return [
        ToolSpec(
            name="get_recent_conversation_window",
            description="Return the most recent conversation turns available in the current session context. Use this when the model needs to refresh local conversational history before answering or planning the next tool call.",
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                        "description": "Maximum number of recent turns to return.",
                    }
                },
                "additionalProperties": False,
            },
            handler=_get_recent_conversation_window,
        ),
        ToolSpec(
            name="get_session_summary",
            description="Return the compact session summary currently available for this chat. Use this when you need the distilled view of the active conversation instead of re-reading every message.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            handler=_get_session_summary,
        ),
        ToolSpec(
            name="list_context_categories",
            description="List which categories of context are currently available in runtime state, including graph entity types, document presence, and whether session context exists. Use this as a lightweight planning tool before fetching more detailed context.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            handler=_list_context_categories,
        ),
        ToolSpec(
            name="respond",
            description="Return the final response payload to the caller. Use this only when tool use is complete and you are ready to provide the answer, optional memory patch, provenance summary, and stop reason.",
            input_schema={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The full final response message for the user.",
                    },
                    "memory_patch": {
                        **JSON_VALUE_SCHEMA,
                        "description": "Optional durable memory update object, or null if no memory update is needed.",
                    },
                    "provenance": {
                        **JSON_VALUE_SCHEMA,
                        "description": "Optional brief provenance summary describing key tools or sources used.",
                    },
                    "stop_reason": {
                        "type": "string",
                        "description": "Optional explanation for why the tool loop stopped, such as answered or need_more_info.",
                    },
                },
                "required": ["message"],
                "additionalProperties": False,
            },
            handler=_respond,
        ),
    ]
