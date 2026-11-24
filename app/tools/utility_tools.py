"""The `respond` tool — the only way an agent finishes a turn.

Every specialist / ingestion loop ends when the LLM calls `respond` with
its final payload. The runners watch for this call and break out of
their tool loop as soon as it succeeds, so without `respond` a turn
would just keep looping until it hit the safety cap.

The payload carries four fields:
- `message`              : text shown to the user
- `stop_reason`          : short tag like "answered" or "need_more_info"
- `next_session_context` : rolling summary saved for the next turn
- `next_long_context`    : durable notes written to the student node
                           (null = leave the stored value alone)
"""

from __future__ import annotations

from typing import Any

from app.tools.tools import ToolContext, ToolSpec, bounded_text


async def _respond(arguments: dict[str, Any], _context: ToolContext) -> dict[str, Any]:
    """Echo the payload straight back; runners use this as "turn complete" signal."""
    return {
        "message": str(arguments.get("message", "") or ""),
        "stop_reason": str(arguments.get("stop_reason", "") or ""),
        "next_session_context": str(arguments.get("next_session_context", "") or ""),
        "next_long_context": arguments.get("next_long_context"),
    }


def _compact_respond(_: dict[str, Any], result: dict[str, Any], __: ToolContext) -> dict[str, Any]:
    """Shrink the final payload for the transcript so we don't echo full answer twice."""
    next_long_context = result.get("next_long_context")
    return {
        "message_preview": bounded_text(result.get("message"), limit=240),
        "stop_reason": str(result.get("stop_reason", "") or ""),
        "next_session_context_preview": bounded_text(result.get("next_session_context"), limit=180),
        "has_next_long_context": next_long_context not in (None, "", [], {}),
    }


def get_utility_tool_specs() -> list[ToolSpec]:
    """Register the `respond` tool with the shared registry."""
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
                        "description": "Full replacement durable context for the consumer, including explicit measurements with units, fit/style preferences, and confirmed owned garments. Merge new durable facts and corrections with existing facts; return null when nothing durable changed. Keep one-time shopping budgets and occasions in session context. Suggested products are not owned garments. Graph ingestion stores structured facts separately.",
                    },
                },
                "required": ["message", "next_session_context"],
                "additionalProperties": False,
            },
            handler=_respond,
            compact_handler=_compact_respond,
        ),
    ]
