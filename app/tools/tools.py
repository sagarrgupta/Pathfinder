"""Shared MCP/OpenAI-style tool registry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Awaitable, Callable

from mcp.types import Tool

_JSON_LIMIT = 8000

try:
    from neo4j.time import Date as Neo4jDate
    from neo4j.time import DateTime as Neo4jDateTime
    from neo4j.time import Time as Neo4jTime
except Exception:  # pragma: no cover - defensive import guard
    Neo4jDate = tuple()  # type: ignore[assignment]
    Neo4jDateTime = tuple()  # type: ignore[assignment]
    Neo4jTime = tuple()  # type: ignore[assignment]


def _normalize_tool_value(value: Any) -> Any:
    """Convert Neo4j-specific values into msgpack/JSON-safe Python values."""
    temporal_types = tuple(
        temporal_type
        for temporal_type in (Neo4jDateTime, Neo4jDate, Neo4jTime, datetime, date, time)
        if isinstance(temporal_type, type)
    )
    if temporal_types and isinstance(value, temporal_types):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _normalize_tool_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_tool_value(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_tool_value(item) for item in value]
    if isinstance(value, set):
        return [_normalize_tool_value(item) for item in value]
    return value


def _wrap_handler(
    handler: Callable[[dict[str, Any], "ToolContext"], Awaitable[dict[str, Any]]],
) -> Callable[[dict[str, Any], "ToolContext"], Awaitable[dict[str, Any]]]:
    async def _wrapped(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return _normalize_tool_value(await handler(arguments, context))

    return _wrapped


@dataclass(frozen=True)
class ToolContext:
    """Execution context shared by tool handlers."""

    student_id: str
    session_id: str = ""
    state: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolSpec:
    """Tool definition used by MCP and internal callers."""
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any], ToolContext], Awaitable[dict[str, Any]]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "handler", _wrap_handler(self.handler))

    def as_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "strict": True,
                "parameters": self.input_schema,
            },
        }

    def as_mcp_tool(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema=self.input_schema,
        )


def get_tool_specs() -> list[ToolSpec]:
    """Return every registered tool spec."""
    from app.tools.graph_tools import get_graph_tool_specs
    from app.tools.utility_tools import get_utility_tool_specs
    from app.tools.vector_tools import get_vector_tool_specs
    from app.tools.web_tools import get_web_tool_specs

    return [
        *get_graph_tool_specs(),
        *get_vector_tool_specs(),
        *get_utility_tool_specs(),
        *get_web_tool_specs(),
    ]


def get_tool_schemas() -> list[dict[str, Any]]:
    """Return OpenAI-compatible tool schemas."""
    return [spec.as_openai_schema() for spec in get_tool_specs()]


def get_mcp_tools() -> list[Tool]:
    """Return MCP tool definitions."""
    return [spec.as_mcp_tool() for spec in get_tool_specs()]


async def execute_tool(name: str, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Execute one registered tool by name."""
    for spec in get_tool_specs():
        if spec.name == name:
            return await spec.handler(arguments, context)
    return {"error": f"unknown tool: {name}"}


def compact_result(result: dict[str, Any]) -> dict[str, Any]:
    """Keep tool messages bounded for tool-calling transcripts."""
    if not isinstance(result, dict):
        return {"value": str(result)[:_JSON_LIMIT]}
    serialized = json.dumps(result, ensure_ascii=True, default=str)
    if len(serialized) <= _JSON_LIMIT:
        return result
    return {"truncated": True, "preview": serialized[:_JSON_LIMIT]}
