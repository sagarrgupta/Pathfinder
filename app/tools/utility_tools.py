"""Utility MCP tools."""

from __future__ import annotations

from typing import Any

from app.tools.tools import ToolContext, ToolSpec, bounded_text


async def _respond(arguments: dict[str, Any], _context: ToolContext) -> dict[str, Any]:
    return {
        "message": str(arguments.get("message", "") or ""),
        "stop_reason": str(arguments.get("stop_reason", "") or ""),
        "next_session_context": str(arguments.get("next_session_context", "") or ""),
        "next_long_context": arguments.get("next_long_context"),
    }


def _compact_respond(_: dict[str, Any], result: dict[str, Any], __: ToolContext) -> dict[str, Any]:
    next_long_context = result.get("next_long_context")
    return {
        "message_preview": bounded_text(result.get("message"), limit=240),
        "stop_reason": str(result.get("stop_reason", "") or ""),
        "next_session_context_preview": bounded_text(result.get("next_session_context"), limit=180),
        "has_next_long_context": next_long_context not in (None, "", [], {}),
    }


def get_utility_tool_specs() -> list[ToolSpec]:
    """Return session/context utility tool definitions."""
    return [
        ToolSpec(
            name="respond",
            description="Return the final response payload to the caller. Use this only when tool use is complete and you are ready to provide the answer, the next session context, the optional next long context, and stop reason.",
            input_schema={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The full final response message for the user.",
                    },
                    "stop_reason": {
                        "type": "string",
                        "description": "Optional explanation for why the tool loop stopped, such as answered or need_more_info.",
                    },
                    "next_session_context": {
                        "type": "string",
                        "description": "Required full replacement summary for this chat session going into the next turn.",
                    },
                    "next_long_context": {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Optional full replacement long context for the student. Return null when the existing long context should remain unchanged.",
                    },
                },
                "required": ["message", "next_session_context"],
                "additionalProperties": False,
            },
            handler=_respond,
            compact_handler=_compact_respond,
        ),
    ]
