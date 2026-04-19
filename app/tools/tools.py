"""Shared MCP/OpenAI-style tool registry."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, time
import logging
from typing import Any, Awaitable, Callable

from mcp.types import Tool

_SUMMARY_FIELD_LIMIT = 10
log = logging.getLogger("pathfinder.tools")

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

# Per-agent tool exclusions. Each set lists the tool names the agent must
# NOT see. The model never receives these schemas and `execute_agent_tool`
# rejects calls to them.

# Document ingester: writes graph structure + grounding to pre-stored chunks.
# No web, no respond, no chunk writes (already done), no admin.
_DOCUMENT_INGESTOR_EXCLUDED_TOOLS: frozenset[str] = frozenset({
    "search_web",
    "fetch_url",
    "find_official_sources",
    "respond",
    "delete_chunk",
    "delete_document_chunks",
    "create_vector_index",
    "vector_health_check",
    "upsert_chunk",
    "upsert_chunk_metadata",
    "batch_upsert_chunks",
    "get_chunks_for_student",
})

# Chat-message ingester: writes graph structure only. No chunks (no document
# to own them), no grounding (nothing to link to), no web, no respond, no admin.
_QUERY_INGESTOR_EXCLUDED_TOOLS: frozenset[str] = frozenset({
    "search_web",
    "fetch_url",
    "find_official_sources",
    "respond",
    "delete_chunk",
    "delete_document_chunks",
    "create_vector_index",
    "vector_health_check",
    "upsert_chunk",
    "upsert_chunk_metadata",
    "batch_upsert_chunks",
    "link_entity_to_chunk",
    "link_entity_to_document",
    "get_chunks_for_student",
})

# Specialist (the answering agent): READ-ONLY against the graph. Ingestion ran
# before it; its job is to read and respond. Web and `respond` stay enabled.
_SPECIALIST_EXCLUDED_TOOLS: frozenset[str] = frozenset({
    "upsert_section",
    "upsert_graph_node",
    "upsert_graph_relation",
    "upsert_entity_field",
    "upsert_nested_field",
    "update_student",
    "link_entity_to_chunk",
    "link_entity_to_document",
    "upsert_chunk",
    "upsert_chunk_metadata",
    "batch_upsert_chunks",
    "delete_chunk",
    "delete_document_chunks",
    "create_vector_index",
    "vector_health_check",
})

_AGENT_TOOL_EXCLUSIONS: dict[str, frozenset[str]] = {
    "document_ingestor": _DOCUMENT_INGESTOR_EXCLUDED_TOOLS,
    "query_ingestor": _QUERY_INGESTOR_EXCLUDED_TOOLS,
    "specialist": _SPECIALIST_EXCLUDED_TOOLS,
}

_AGENT_TOOL_SPECS_CACHE: dict[str, tuple["ToolSpec", ...]] = {}
_AGENT_TOOL_SCHEMAS_CACHE: dict[str, tuple[dict[str, Any], ...]] = {}
_AGENT_TOOL_BY_NAME_CACHE: dict[str, dict[str, "ToolSpec"]] = {}


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
        try:
            return await spec.handler(arguments, context)
        except ValueError as exc:
            log.warning("Tool %s returned recoverable error: %s", name, exc)
            return {"error": str(exc)}
    return {"error": f"unknown tool: {name}"}


def list_agent_profiles() -> list[str]:
    """Return the names of registered agent tool profiles."""
    return list(_AGENT_TOOL_EXCLUSIONS.keys())


def _resolve_agent_profile(agent: str) -> frozenset[str]:
    """Look up the exclusion set for an agent, raising on unknown profiles."""
    if agent not in _AGENT_TOOL_EXCLUSIONS:
        valid = ", ".join(sorted(_AGENT_TOOL_EXCLUSIONS.keys()))
        raise ValueError(f"unknown agent profile {agent!r}; valid profiles: {valid}")
    return _AGENT_TOOL_EXCLUSIONS[agent]


def get_agent_tool_specs(agent: str) -> list[ToolSpec]:
    """Return the ToolSpec subset visible to a specific agent profile."""
    cached = _AGENT_TOOL_SPECS_CACHE.get(agent)
    if cached is not None:
        return list(cached)
    excluded = _resolve_agent_profile(agent)
    specs = tuple(spec for spec in get_tool_specs() if spec.name not in excluded)
    _AGENT_TOOL_SPECS_CACHE[agent] = specs
    _AGENT_TOOL_BY_NAME_CACHE[agent] = {spec.name: spec for spec in specs}
    return list(specs)


def get_agent_tool_schemas(agent: str) -> list[dict[str, Any]]:
    """Return OpenAI-compatible schemas for the agent's tool subset."""
    cached = _AGENT_TOOL_SCHEMAS_CACHE.get(agent)
    if cached is not None:
        return list(cached)
    schemas = tuple(spec.as_openai_schema() for spec in get_agent_tool_specs(agent))
    _AGENT_TOOL_SCHEMAS_CACHE[agent] = schemas
    return list(schemas)


async def execute_agent_tool(
    agent: str, name: str, arguments: dict[str, Any], context: ToolContext
) -> dict[str, Any]:
    """Execute one tool, rejecting names not allowed for the given agent profile."""
    if agent not in _AGENT_TOOL_BY_NAME_CACHE:
        get_agent_tool_specs(agent)
    spec = _AGENT_TOOL_BY_NAME_CACHE.get(agent, {}).get(name)
    if spec is None:
        if name in (_AGENT_TOOL_EXCLUSIONS.get(agent) or frozenset()):
            return {"error": f"tool '{name}' is not available to agent '{agent}'"}
        return {"error": f"unknown tool: {name}"}
    try:
        return await spec.handler(arguments, context)
    except ValueError as exc:
        log.warning("Agent %s tool %s returned recoverable error: %s", agent, name, exc)
        return {"error": str(exc)}


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
