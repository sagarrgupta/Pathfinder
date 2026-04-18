"""Shared MCP/OpenAI-style tool registry."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Awaitable, Callable

from mcp.types import Tool

_SUMMARY_FIELD_LIMIT = 10

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


ToolHandler = Callable[[dict[str, Any], "ToolContext"], Awaitable[dict[str, Any]]]
CompactHandler = Callable[[dict[str, Any], dict[str, Any], "ToolContext"], dict[str, Any]]

_TOOL_SPECS: tuple["ToolSpec", ...] | None = None
_TOOL_SCHEMAS: tuple[dict[str, Any], ...] | None = None
_MCP_TOOLS: tuple[Tool, ...] | None = None
_TOOL_SPEC_BY_NAME: dict[str, "ToolSpec"] | None = None


def _wrap_handler(handler: ToolHandler) -> ToolHandler:
    async def _wrapped(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return _normalize_tool_value(await handler(arguments, context))

    return _wrapped


def _wrap_compact_handler(handler: CompactHandler) -> CompactHandler:
    def _wrapped(arguments: dict[str, Any], result: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return _normalize_tool_value(handler(arguments, result, context))

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
    handler: ToolHandler
    compact_handler: CompactHandler

    def __post_init__(self) -> None:
        object.__setattr__(self, "handler", _wrap_handler(self.handler))
        object.__setattr__(self, "compact_handler", _wrap_compact_handler(self.compact_handler))

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
    _ensure_tool_cache()
    return list(_TOOL_SPECS or ())


def get_tool_schemas() -> list[dict[str, Any]]:
    """Return OpenAI-compatible tool schemas."""
    _ensure_tool_cache()
    return list(_TOOL_SCHEMAS or ())


def get_mcp_tools() -> list[Tool]:
    """Return MCP tool definitions."""
    _ensure_tool_cache()
    return list(_MCP_TOOLS or ())


def get_tool_spec(name: str) -> ToolSpec | None:
    """Return one registered tool spec by name."""
    _ensure_tool_cache()
    return (_TOOL_SPEC_BY_NAME or {}).get(name)


def _ensure_tool_cache() -> None:
    global _TOOL_SPECS, _TOOL_SCHEMAS, _MCP_TOOLS, _TOOL_SPEC_BY_NAME
    if _TOOL_SPECS is not None:
        return

    from app.tools.graph_tools import get_graph_tool_specs
    from app.tools.utility_tools import get_utility_tool_specs
    from app.tools.vector_tools import get_vector_tool_specs
    from app.tools.web_tools import get_web_tool_specs

    specs = tuple(
        [
            *get_graph_tool_specs(),
            *get_vector_tool_specs(),
            *get_utility_tool_specs(),
            *get_web_tool_specs(),
        ]
    )
    _TOOL_SPECS = specs
    _TOOL_SCHEMAS = tuple(spec.as_openai_schema() for spec in specs)
    _MCP_TOOLS = tuple(spec.as_mcp_tool() for spec in specs)
    _TOOL_SPEC_BY_NAME = {spec.name: spec for spec in specs}


async def execute_tool(name: str, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Execute one registered tool by name."""
    spec = get_tool_spec(name)
    if spec is not None:
        return await spec.handler(arguments, context)
    return {"error": f"unknown tool: {name}"}


def summarize_tool_usage(tool_names: list[str]) -> dict[str, str]:
    """Return the high-level method label for successful tool usage."""
    from app.tools.graph_tools import get_graph_tool_specs
    from app.tools.vector_tools import get_vector_tool_specs
    from app.tools.web_tools import get_web_tool_specs

    categories: dict[str, str] = {}
    for spec in get_graph_tool_specs():
        categories[spec.name] = "Graph"
    for spec in get_vector_tool_specs():
        categories[spec.name] = "Vector"
    for spec in get_web_tool_specs():
        categories[spec.name] = "Web"
    used_categories: list[str] = []
    seen: set[str] = set()
    for name in tool_names:
        category = categories.get(str(name or "").strip(), "")
        if category and category not in seen:
            seen.add(category)
            used_categories.append(category)

    if not used_categories:
        return {"method": "direct"}

    method_map = {
        "Graph": "graph",
        "Vector": "rag",
        "Web": "web",
    }
    methods = [method_map[category] for category in used_categories if category in method_map]
    return {"method": "+".join(methods) if methods else "direct"}


def build_tool_transcript_payload(
    name: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
    context: ToolContext,
) -> dict[str, Any]:
    """Return the compact LLM-facing transcript payload for one tool call."""
    spec = get_tool_spec(name)
    status = "error" if isinstance(result, dict) and result.get("error") else "ok"
    if spec is None:
        return {
            "tool": name,
            "status": status,
            "summary": {"error": "unknown tool"},
        }

    if status == "error":
        return {
            "tool": name,
            "status": "error",
            "error": str(result.get("error", "") or "tool error"),
        }

    return {
        "tool": name,
        "status": "ok",
        "summary": spec.compact_handler(arguments, result, context),
    }


def is_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool)) or value is None


def bounded_text(value: Any, limit: int = 240) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def pick_scalar_fields(
    payload: dict[str, Any],
    *,
    exclude: set[str] | None = None,
    limit: int = _SUMMARY_FIELD_LIMIT,
) -> dict[str, Any]:
    """Return a stable, bounded set of scalar-ish fields from a dict."""
    exclude = set(exclude or set())
    summary: dict[str, Any] = {}
    for key in sorted(payload.keys()):
        if key in exclude:
            continue
        value = payload.get(key)
        if value in (None, "", [], {}):
            continue
        if is_scalar(value):
            summary[key] = value
        elif isinstance(value, list) and all(is_scalar(item) for item in value):
            summary[key] = value[:10]
        if len(summary) >= limit:
            break
    return summary
