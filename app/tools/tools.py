"""Central registry for every tool the LLM can call.

This file is the spine of the tool system. It defines:

- `ToolSpec`     — metadata plus handlers for one callable tool.
- `ToolContext`  — who the tool is being run for (student/session) and
                   the current LangGraph state.
- Agent "profiles" (`document_ingestor`, `query_ingestor`, `specialist`)
  each with a frozen set of tools they are NOT allowed to see.
- `execute_agent_tool` — enforces those profiles at call time and wraps
  results into a compact, LLM-friendly shape.

The actual tool implementations live in sibling files (`graph_tools`,
`vector_tools`, `web_tools`, `utility_tools`); this file just stitches
them together and exposes them in three flavours:
- OpenAI tool schemas for LangChain's `bind_tools`
- MCP `Tool` definitions for the stdio server
- a `by-name` lookup used internally by the runners.
"""

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
    """Turn Neo4j date/time objects into plain strings recursively.

    Neo4j's driver returns its own `Date`/`DateTime`/`Time` types, which
    are not JSON-serializable and break the MCP + replay pipelines. We
    walk the structure once on the way out and stringify them.
    """
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
_MCP_TOOLS: tuple[Tool, ...] | None = None
_TOOL_SPEC_BY_NAME: dict[str, "ToolSpec"] | None = None

# Per-agent tool exclusions. Each set lists the tool names the agent must
# NOT see. The model never receives these schemas and `execute_agent_tool`
# rejects calls to them. Think of this as "role-based access control" for
# the LLM.

# Document ingester: its job is to read a freshly-uploaded document and
# write structured knowledge (entities, sections, relations) grounded in
# chunks that `doc_analyst` already stored. So it gets graph-write tools
# but not chunk-write tools, web, `respond`, or admin tools.
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

# Chat-message ingester: same idea, but there is no document for this turn,
# so chunk writes and chunk-grounding links are off too. It only writes
# bare graph structure (sections, entities, fields, relations).
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

# Specialist (the answering agent): READ-ONLY against the graph. By the
# time the specialist runs, both ingesters have already written whatever
# they are going to write. The specialist's job is to read and respond —
# web and `respond` stay enabled so it can look things up and finish.
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

# Per-profile caches so we compute the visible tool list once per agent.
# The model objects are immutable, so caching is safe.
_AGENT_TOOL_SPECS_CACHE: dict[str, tuple["ToolSpec", ...]] = {}
_AGENT_TOOL_SCHEMAS_CACHE: dict[str, tuple[dict[str, Any], ...]] = {}
_AGENT_TOOL_BY_NAME_CACHE: dict[str, dict[str, "ToolSpec"]] = {}


def _wrap_handler(handler: ToolHandler) -> ToolHandler:
    """Decorate a handler so its return value is always JSON-safe."""
    async def _wrapped(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return _normalize_tool_value(await handler(arguments, context))

    return _wrapped


def _wrap_compact_handler(handler: CompactHandler) -> CompactHandler:
    """Same normalization for the compact (LLM-facing) summary handler."""
    def _wrapped(arguments: dict[str, Any], result: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        return _normalize_tool_value(handler(arguments, result, context))

    return _wrapped


@dataclass(frozen=True)
class ToolContext:
    """Whose behalf a tool is running on, plus read access to turn state.

    Every tool handler receives the same `ToolContext`. This is how a
    graph read "knows" which student to filter by without each tool
    having to accept it as an explicit argument.
    """

    student_id: str
    session_id: str = ""
    state: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolSpec:
    """One tool: name, description, JSON schema, and its two handlers.

    `handler` returns the full result (stored in replay artifacts).
    `compact_handler` returns a small, LLM-friendly summary — that's
    what goes back into the model's context so tool output doesn't blow
    up the context window. Both are automatically normalized so callers
    never see raw Neo4j temporal objects.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler
    compact_handler: CompactHandler

    def __post_init__(self) -> None:
        object.__setattr__(self, "handler", _wrap_handler(self.handler))
        object.__setattr__(self, "compact_handler", _wrap_compact_handler(self.compact_handler))

    def as_openai_schema(self) -> dict[str, Any]:
        """Shape for LangChain's `bind_tools` / OpenAI tool-calling API."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                # Graph identities and properties have dynamic keys. Strict
                # mode forbids those maps (and requires every field), so use
                # standard function calling without stripping valid arguments.
                "strict": False,
                "parameters": self.input_schema,
            },
        }

    def as_mcp_tool(self) -> Tool:
        """Shape for the MCP stdio server (`app.tools.mcp_server`)."""
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema=self.input_schema,
        )


def get_tool_specs() -> list[ToolSpec]:
    """Every tool registered in Pathfinder (across all sub-files)."""
    _ensure_tool_cache()
    return list(_TOOL_SPECS or ())


def get_mcp_tools() -> list[Tool]:
    """MCP-shaped tool definitions for the stdio server."""
    _ensure_tool_cache()
    return list(_MCP_TOOLS or ())


def get_tool_spec(name: str) -> ToolSpec | None:
    """Look up one tool spec by name (None if unknown)."""
    _ensure_tool_cache()
    return (_TOOL_SPEC_BY_NAME or {}).get(name)


def _ensure_tool_cache() -> None:
    """Build the global tool caches on first use.

    We import the sub-modules lazily here to avoid circular imports at
    package load time, and we memoize so the registration cost is paid
    exactly once per process.
    """
    global _TOOL_SPECS, _MCP_TOOLS, _TOOL_SPEC_BY_NAME
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
    _MCP_TOOLS = tuple(spec.as_mcp_tool() for spec in specs)
    _TOOL_SPEC_BY_NAME = {spec.name: spec for spec in specs}


async def execute_tool(name: str, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Run one tool by name (no profile check). Used by the MCP server."""
    spec = get_tool_spec(name)
    if spec is not None:
        try:
            return await spec.handler(arguments, context)
        except ValueError as exc:
            # ValueErrors are treated as "recoverable" so the model can see
            # the problem and try again instead of crashing the loop.
            log.warning("Tool %s returned recoverable error: %s", name, exc)
            return {"error": str(exc)}
    return {"error": f"unknown tool: {name}"}


def _resolve_agent_profile(agent: str) -> frozenset[str]:
    """Return the exclusion set for an agent, or raise on a typo."""
    if agent not in _AGENT_TOOL_EXCLUSIONS:
        valid = ", ".join(sorted(_AGENT_TOOL_EXCLUSIONS.keys()))
        raise ValueError(f"unknown agent profile {agent!r}; valid profiles: {valid}")
    return _AGENT_TOOL_EXCLUSIONS[agent]


def get_agent_tool_specs(agent: str) -> list[ToolSpec]:
    """Subset of tools one profile is allowed to see — with caching."""
    cached = _AGENT_TOOL_SPECS_CACHE.get(agent)
    if cached is not None:
        return list(cached)
    excluded = _resolve_agent_profile(agent)
    specs = tuple(spec for spec in get_tool_specs() if spec.name not in excluded)
    _AGENT_TOOL_SPECS_CACHE[agent] = specs
    _AGENT_TOOL_BY_NAME_CACHE[agent] = {spec.name: spec for spec in specs}
    return list(specs)


def get_agent_tool_schemas(agent: str) -> list[dict[str, Any]]:
    """OpenAI tool schemas for the subset the agent can see."""
    cached = _AGENT_TOOL_SCHEMAS_CACHE.get(agent)
    if cached is not None:
        return list(cached)
    schemas = tuple(spec.as_openai_schema() for spec in get_agent_tool_specs(agent))
    _AGENT_TOOL_SCHEMAS_CACHE[agent] = schemas
    return list(schemas)


async def execute_agent_tool(
    agent: str, name: str, arguments: dict[str, Any], context: ToolContext
) -> dict[str, Any]:
    """Run a tool but enforce the agent's profile — the security boundary.

    If the agent asked for an excluded tool, we return a structured error
    instead of silently calling it. This is what prevents the read-only
    specialist from issuing graph writes even if it tried to.
    """
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
    """Turn the list of tools used into a short method label (e.g. "graph+web").

    Used by the API layer to tell the client roughly *how* the answer was
    produced without shipping the full tool log.
    """
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
    """Shrink one tool call's raw result to a short LLM-friendly dict.

    Runners feed this back into the model as the content of a
    `ToolMessage`. Keeping it compact is how we stay under the context
    window even when a tool returns megabytes of raw data.
    """
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
    """True for simple values that can be dropped into summaries as-is."""
    return isinstance(value, (str, int, float, bool)) or value is None


def bounded_text(value: Any, limit: int = 240) -> str:
    """Stringify + truncate to keep summaries short in the model transcript."""
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
    """Grab a stable, small subset of scalar fields for compact summaries.

    Sorted key order + hard field limit keeps summaries deterministic
    across runs (important for replay diffs) and prevents a single noisy
    payload from swamping the model's context.
    """
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
