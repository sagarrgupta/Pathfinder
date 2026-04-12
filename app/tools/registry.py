"""Canonical MCP-style tool registry shared by internal and external callers."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from mcp.types import Tool

from app.adapters.neo4j.graph_store import (
    create_entity,
    ensure_student,
    execute_cypher,
    get_full_profile,
    get_relevant_memories,
    list_saved_recommendations,
    run_cypher,
    store_candidate_fact,
    update_student,
)
from app.adapters.neo4j.vector_store import hybrid_search
from app.adapters.web_search.fallback_chain import search as web_search
from app.adapters.web_search.url_fetcher import fetch_url_content
from app.core.quality import build_session_summary
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.tools.registry")

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DEFAULT_RELATIONSHIP = "HAS"
_JSON_LIMIT = 8000


@dataclass(frozen=True)
class ToolContext:
    """Execution context shared by tool handlers."""

    student_id: str
    session_id: str = ""
    state: PathfinderState | None = None


@dataclass(frozen=True)
class ToolSpec:
    """Canonical tool definition."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any], ToolContext], Awaitable[dict[str, Any]]]

    def as_openai_schema(self) -> dict[str, Any]:
        schema = _schema_with_context_fields(self.input_schema)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "strict": True,
                "parameters": schema,
            },
        }

    def as_mcp_tool(self) -> Tool:
        schema = _schema_with_context_fields(self.input_schema)
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema=schema,
        )


def get_tool_specs() -> list[ToolSpec]:
    """Return every canonical tool spec."""
    return list(_TOOL_SPECS)


def get_tool_schemas() -> list[dict[str, Any]]:
    """Return OpenAI-compatible tool schemas."""
    return [spec.as_openai_schema() for spec in _TOOL_SPECS]


def get_mcp_tools() -> list[Tool]:
    """Return MCP tool definitions."""
    return [spec.as_mcp_tool() for spec in _TOOL_SPECS]


async def execute_tool(name: str, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Execute one registered tool."""
    for spec in _TOOL_SPECS:
        if spec.name == name:
            return await spec.handler(arguments, context)
    return {"error": f"unknown tool: {name}"}


def _safe_identifier(value: str, kind: str) -> str:
    value = str(value or "").strip()
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"invalid {kind}: {value!r}")
    return value


def _tool_limit(value: Any, default: int = 5, maximum: int = 20) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(1, min(parsed, maximum))


def _context_state(context: ToolContext) -> PathfinderState:
    return context.state or {}


def _schema_with_context_fields(schema: dict[str, Any]) -> dict[str, Any]:
    """Add optional external caller context fields to every tool schema."""
    copied = json.loads(json.dumps(schema))
    properties = copied.setdefault("properties", {})
    if isinstance(properties, dict):
        properties.setdefault("student_id", {"type": "string"})
        properties.setdefault("session_id", {"type": "string"})
    return copied


def _profile_small_facts(profile: dict[str, Any]) -> dict[str, Any]:
    personal = profile.get("personal", {}) if isinstance(profile.get("personal", {}), dict) else {}
    goals = [
        str(item.get("name") or item.get("value") or "").strip()
        for item in profile.get("goals", [])
        if isinstance(item, dict) and str(item.get("name") or item.get("value") or "").strip()
    ][:5]
    preferences = [
        str(item.get("name") or item.get("value") or "").strip()
        for item in profile.get("preferences", [])
        if isinstance(item, dict) and str(item.get("name") or item.get("value") or "").strip()
    ][:5]
    skills = [
        str(item.get("name") or "").strip()
        for item in profile.get("skills", [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ][:8]
    return {
        "name": str(personal.get("name", "") or ""),
        "institution": str(personal.get("university", "") or ""),
        "program": str(personal.get("program", "") or ""),
        "semester": str(personal.get("semester", "") or ""),
        "gpa": str(personal.get("gpa", "") or ""),
        "goals": goals,
        "preferences": preferences,
        "skills": skills,
    }


async def _get_profile_summary(_: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    await ensure_student(context.student_id)
    profile = await get_full_profile(context.student_id)
    return {
        "profile_summary": _profile_small_facts(profile),
        "counts": {
            "courses": len(profile.get("courses", [])),
            "skills": len(profile.get("skills", [])),
            "goals": len(profile.get("goals", [])),
            "documents": len(profile.get("documents", [])),
        },
    }


async def _list_entity_types(_: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    profile = await get_full_profile(context.student_id)
    all_entities = profile.get("all_entities", {})
    entity_counts = {
        label: len(items)
        for label, items in all_entities.items()
        if isinstance(items, list) and items
    }
    return {"entity_types": sorted(entity_counts.keys()), "entity_counts": entity_counts}


def _filter_clauses(filters: dict[str, Any], prefix: str, alias: str) -> tuple[list[str], dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    for idx, (field, value) in enumerate((filters or {}).items()):
        field_name = _safe_identifier(field, "field")
        param_name = f"{prefix}_{idx}"
        clauses.append(f"toString({alias}.{field_name}) = ${param_name}")
        params[param_name] = str(value)
    return clauses, params


async def _typed_node_lookup(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    entity_type = _safe_identifier(arguments.get("entity_type", ""), "entity_type")
    limit = _tool_limit(arguments.get("limit", 8), default=8)
    filters = arguments.get("filters", {}) if isinstance(arguments.get("filters", {}), dict) else {}
    clauses, params = _filter_clauses(filters, "node", "n")
    where = " AND ".join(["s.id = $student_id"] + clauses)
    rows = await run_cypher(
        f"""
        MATCH (s:Student)-[r]->(n:{entity_type})
        WHERE {where}
        RETURN n {{.*, _relationship: type(r)}} AS node
        ORDER BY coalesce(n.updated_at, n.created_at) DESC
        LIMIT $limit
        """,
        {"student_id": context.student_id, "limit": limit, **params},
    )
    return {"entity_type": entity_type, "results": [row.get("node", {}) for row in rows]}


async def _typed_relation_lookup(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    relationship_type = _safe_identifier(arguments.get("relationship_type", ""), "relationship_type")
    target_type = _safe_identifier(arguments.get("target_entity_type", ""), "target_entity_type")
    limit = _tool_limit(arguments.get("limit", 8), default=8)
    filters = arguments.get("target_filters", {}) if isinstance(arguments.get("target_filters", {}), dict) else {}
    clauses, params = _filter_clauses(filters, "rel", "n")
    where = " AND ".join(["s.id = $student_id"] + clauses)
    rows = await run_cypher(
        f"""
        MATCH (s:Student)-[r:{relationship_type}]->(n:{target_type})
        WHERE {where}
        RETURN {{
            relationship_type: type(r),
            target: n {{.*}},
            relationship: properties(r)
        }} AS relation
        LIMIT $limit
        """,
        {"student_id": context.student_id, "limit": limit, **params},
    )
    return {"relationship_type": relationship_type, "results": [row.get("relation", {}) for row in rows]}


async def _fetch_node_by_id(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    node_id = str(arguments.get("node_id", "") or "").strip()
    entity_type = _safe_identifier(arguments.get("entity_type", ""), "entity_type")
    if not node_id:
        return {"error": "node_id is required"}
    rows = await run_cypher(
        f"""
        MATCH (s:Student {{id: $student_id}})-[r]->(n:{entity_type})
        WHERE toString(n.id) = $node_id OR toString(n.name) = $node_id
        RETURN n {{.*, _relationship: type(r)}} AS node
        LIMIT 1
        """,
        {"student_id": context.student_id, "node_id": node_id},
    )
    return {"node": rows[0].get("node", {}) if rows else {}}


async def _fetch_relation_detail(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    relationship_type = _safe_identifier(arguments.get("relationship_type", ""), "relationship_type")
    target_type = _safe_identifier(arguments.get("target_entity_type", ""), "target_entity_type")
    target_field = _safe_identifier(arguments.get("target_field", "id"), "target_field")
    target_value = str(arguments.get("target_value", "") or "").strip()
    rows = await run_cypher(
        f"""
        MATCH (s:Student {{id: $student_id}})-[r:{relationship_type}]->(n:{target_type})
        WHERE toString(n.{target_field}) = $target_value
        RETURN {{
            relationship_type: type(r),
            relationship: properties(r),
            target: n {{.*}}
        }} AS relation
        LIMIT 1
        """,
        {"student_id": context.student_id, "target_value": target_value},
    )
    return {"relation": rows[0].get("relation", {}) if rows else {}}


async def _list_document_groups(_: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    profile = await get_full_profile(context.student_id)
    groups: dict[str, int] = {}
    for doc in profile.get("documents", []):
        if not isinstance(doc, dict):
            continue
        role = str(doc.get("document_role") or doc.get("doc_type") or doc.get("file_type") or "unknown")
        groups[role] = groups.get(role, 0) + 1
    return {"document_groups": groups, "documents": profile.get("documents", [])[:12]}


async def _search_documents_semantic(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    query = str(arguments.get("query", "") or "").strip()
    if not query:
        return {"error": "query is required"}
    limit = _tool_limit(arguments.get("limit", 5))
    results = await hybrid_search(
        query=query,
        k=limit,
        student_id=context.student_id,
        session_id=context.session_id or None,
    )
    trimmed = [
        {
            "id": item.get("id", ""),
            "filename": item.get("filename", ""),
            "page_number": item.get("page_number", ""),
            "score": item.get("score", 0),
            "text": str(item.get("text", "") or "")[:1200],
        }
        for item in results
    ]
    return {"query": query, "results": trimmed}


async def _search_memory_semantic(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    query = str(arguments.get("query", "") or "").strip()
    if not query:
        return {"error": "query is required"}
    limit = _tool_limit(arguments.get("limit", 8), default=8)
    memories = await get_relevant_memories(context.student_id, query, limit=limit)
    return memories


async def _fetch_document_snippet(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    chunk_id = str(arguments.get("chunk_id", "") or "").strip()
    document_id = str(arguments.get("document_id", "") or "").strip()
    if not chunk_id and not document_id:
        return {"error": "chunk_id or document_id is required"}
    if chunk_id:
        rows = await run_cypher(
            """
            MATCH (s:Student {id: $student_id})-[:UPLOADED]->(:Document)<-[:FROM_DOCUMENT]-(c:Chunk {id: $chunk_id})
            RETURN c {.*} AS chunk
            LIMIT 1
            """,
            {"student_id": context.student_id, "chunk_id": chunk_id},
        )
        return {"chunk": rows[0].get("chunk", {}) if rows else {}}
    rows = await run_cypher(
        """
        MATCH (s:Student {id: $student_id})-[:UPLOADED]->(d:Document {id: $document_id})<-[:FROM_DOCUMENT]-(c:Chunk)
        RETURN c {.*} AS chunk
        ORDER BY c.chunk_index ASC
        LIMIT 5
        """,
        {"student_id": context.student_id, "document_id": document_id},
    )
    return {"chunks": [row.get("chunk", {}) for row in rows]}


async def _search_web(arguments: dict[str, Any], _: ToolContext) -> dict[str, Any]:
    query = str(arguments.get("query", "") or "").strip()
    if not query:
        return {"error": "query is required"}
    max_results = _tool_limit(arguments.get("max_results", 5), default=5, maximum=10)
    results = await web_search(query, max_results=max_results)
    return {"results": results[:max_results]}


async def _fetch_url(arguments: dict[str, Any], _: ToolContext) -> dict[str, Any]:
    url = str(arguments.get("url", "") or "").strip()
    if not url:
        return {"error": "url is required"}
    result = await fetch_url_content(url)
    return {"result": result or {}, "error": "" if result else "fetch failed"}


async def _find_official_sources(arguments: dict[str, Any], _: ToolContext) -> dict[str, Any]:
    query = str(arguments.get("query", "") or "").strip()
    if not query:
        return {"error": "query is required"}
    results = await web_search(query, max_results=8)
    official = []
    for item in results:
        url = str(item.get("url", "") or "")
        if any(domain in url for domain in (".edu", ".gov", ".ac.", "official", "catalog")):
            official.append(item)
    return {"results": official[:5]}


async def _get_recent_conversation_window(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    state = _context_state(context)
    limit = _tool_limit(arguments.get("limit", 8), default=8, maximum=20)
    messages = list(state.get("messages", []))
    window = []
    for msg in messages[-limit:]:
        if isinstance(msg, tuple) and len(msg) == 2:
            role = "user" if str(msg[0]) in {"human", "user"} else "assistant"
            window.append({"role": role, "content": str(msg[1])})
        elif hasattr(msg, "content"):
            role_name = str(getattr(msg, "type", "") or getattr(msg, "role", ""))
            role = "user" if role_name in {"human", "user"} else "assistant"
            window.append({"role": role, "content": str(getattr(msg, "content", "") or "")})
    return {"recent_messages": window}


async def _get_session_summary(_: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    state = _context_state(context)
    summary = dict(state.get("session_summary", {}) or {})
    if not summary:
        profile = await get_full_profile(context.student_id)
        summary = build_session_summary(profile, list(state.get("messages", [])), str(state.get("query", "") or ""))
    return {"session_summary": summary}


async def _list_context_categories(_: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    profile = await get_full_profile(context.student_id)
    memories = await get_relevant_memories(context.student_id, str((_context_state(context)).get("query", "") or ""), limit=4)
    return {
        "categories": {
            "graph_entity_types": sorted((profile.get("all_entities", {}) or {}).keys()),
            "documents_available": len(profile.get("documents", [])),
            "memory_buckets": sorted(memories.keys()),
            "session_context_available": bool(context.state),
        }
    }


async def _view_durable_memory_summary(_: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    profile = await get_full_profile(context.student_id)
    saved = await list_saved_recommendations(context.student_id, limit=6)
    memories = await get_relevant_memories(context.student_id, str((_context_state(context)).get("query", "") or ""), limit=6)
    return {
        "profile_facts": profile.get("profile_facts", [])[:10],
        "candidate_fact_ledger": profile.get("candidate_fact_ledger", [])[:10],
        "saved_recommendations": saved,
        "memory_summary": memories,
    }


async def _add_or_update_fact(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    fact_type = str(arguments.get("fact_type", "") or "").strip().lower()
    value = str(arguments.get("value", "") or "").strip()
    confidence = float(arguments.get("confidence", 0.9) or 0.9)
    salience = float(arguments.get("salience", 0.85) or 0.85)
    source_ref = str(arguments.get("source_ref", context.session_id or "specialist_tool") or "specialist_tool")
    if not fact_type or not value:
        return {"error": "fact_type and value are required"}
    record = await store_candidate_fact(
        context.student_id,
        fact_type,
        value,
        source_ref=source_ref,
        confidence=confidence,
        salience=salience,
        status="resolved",
        metadata={"tool": "add_or_update_fact", "session_id": context.session_id},
    )
    return {"fact": record}


async def _add_or_update_goal(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    name = str(arguments.get("name", "") or "").strip()
    if not name:
        return {"error": "name is required"}
    entity = await create_entity(
        label="Goal",
        properties={"name": name, "details": str(arguments.get("details", "") or "")},
        student_id=context.student_id,
        relationship="HAS_GOAL",
    )
    return {"goal": entity}


async def _add_or_update_preference(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    summary = str(arguments.get("summary", "") or "").strip()
    preference_key = str(arguments.get("preference_key", "") or "").strip()
    if not summary and not preference_key:
        return {"error": "summary or preference_key is required"}
    if preference_key and preference_key in {"name", "gpa", "university", "program", "semester", "email"}:
        updated = await update_student(context.student_id, **{preference_key: str(arguments.get("value", "") or "")})
        return {"updated_profile": updated}
    entity = await create_entity(
        label="Preference",
        properties={"name": preference_key or summary, "value": str(arguments.get("value", summary) or summary)},
        student_id=context.student_id,
        relationship="PREFERS",
    )
    return {"preference": entity}


async def _supersede_outdated_fact(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    fact_id = str(arguments.get("fact_id", "") or "").strip()
    if not fact_id:
        return {"error": "fact_id is required"}
    rows = await execute_cypher(
        """
        MATCH (s:Student {id: $student_id})-[:HAS_CANDIDATE_FACT|HAS_MEMORY]->(n)
        WHERE n.id = $fact_id
        SET n.status = 'superseded',
            n.superseded_at = datetime(),
            n.updated_at = datetime()
        RETURN n {.*} AS item
        """,
        {"student_id": context.student_id, "fact_id": fact_id},
    )
    return {"item": rows[0].get("item", {}) if rows else {}}


async def _graph_add_node(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    label = _safe_identifier(arguments.get("entity_type", ""), "entity_type")
    relationship = _safe_identifier(arguments.get("relationship_type", _DEFAULT_RELATIONSHIP), "relationship_type")
    properties = arguments.get("properties", {}) if isinstance(arguments.get("properties", {}), dict) else {}
    entity = await create_entity(label, properties, context.student_id, relationship=relationship)
    return {"node": entity}


async def _graph_update_node(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    label = _safe_identifier(arguments.get("entity_type", ""), "entity_type")
    filters = arguments.get("match", {}) if isinstance(arguments.get("match", {}), dict) else {}
    updates = arguments.get("updates", {}) if isinstance(arguments.get("updates", {}), dict) else {}
    if not filters or not updates:
        return {"error": "match and updates are required"}
    where_parts, params = _filter_clauses(filters, "match", "n")
    set_parts = []
    for idx, (field, value) in enumerate(updates.items()):
        field_name = _safe_identifier(field, "field")
        param_name = f"update_{idx}"
        set_parts.append(f"n.{field_name} = ${param_name}")
        params[param_name] = value
    rows = await execute_cypher(
        f"""
        MATCH (s:Student {{id: $student_id}})-[r]->(n:{label})
        WHERE {" AND ".join(where_parts)}
        SET {", ".join(set_parts)}, n.updated_at = datetime()
        RETURN n {{.*, _relationship: type(r)}} AS node
        LIMIT 5
        """,
        {"student_id": context.student_id, **params},
    )
    return {"updated_nodes": [row.get("node", {}) for row in rows]}


async def _graph_add_relation(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    source_type = _safe_identifier(arguments.get("source_entity_type", ""), "source_entity_type")
    target_type = _safe_identifier(arguments.get("target_entity_type", ""), "target_entity_type")
    relationship_type = _safe_identifier(arguments.get("relationship_type", ""), "relationship_type")
    source_match = arguments.get("source_match", {}) if isinstance(arguments.get("source_match", {}), dict) else {}
    target_match = arguments.get("target_match", {}) if isinstance(arguments.get("target_match", {}), dict) else {}
    properties = arguments.get("properties", {}) if isinstance(arguments.get("properties", {}), dict) else {}
    source_clauses, source_params = _filter_clauses(source_match, "src", "src")
    target_clauses, target_params = _filter_clauses(target_match, "dst", "dst")
    property_set = []
    params: dict[str, Any] = {"student_id": context.student_id, **source_params, **target_params}
    for idx, (field, value) in enumerate(properties.items()):
        field_name = _safe_identifier(field, "field")
        param_name = f"rel_{idx}"
        property_set.append(f"r.{field_name} = ${param_name}")
        params[param_name] = value
    rows = await execute_cypher(
        f"""
        MATCH (s:Student {{id: $student_id}})-[]->(src:{source_type})
        MATCH (s)-[]->(dst:{target_type})
        WHERE {" AND ".join(source_clauses + target_clauses)}
        MERGE (src)-[r:{relationship_type}]->(dst)
        {"SET " + ", ".join(property_set) if property_set else ""}
        RETURN {{
            relationship_type: type(r),
            source: src {{.*}},
            target: dst {{.*}},
            relationship: properties(r)
        }} AS relation
        LIMIT 5
        """,
        params,
    )
    return {"relations": [row.get("relation", {}) for row in rows]}


async def _graph_update_relation(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    source_type = _safe_identifier(arguments.get("source_entity_type", ""), "source_entity_type")
    target_type = _safe_identifier(arguments.get("target_entity_type", ""), "target_entity_type")
    relationship_type = _safe_identifier(arguments.get("relationship_type", ""), "relationship_type")
    source_match = arguments.get("source_match", {}) if isinstance(arguments.get("source_match", {}), dict) else {}
    target_match = arguments.get("target_match", {}) if isinstance(arguments.get("target_match", {}), dict) else {}
    updates = arguments.get("updates", {}) if isinstance(arguments.get("updates", {}), dict) else {}
    source_clauses, source_params = _filter_clauses(source_match, "usrc", "src")
    target_clauses, target_params = _filter_clauses(target_match, "udst", "dst")
    params: dict[str, Any] = {"student_id": context.student_id, **source_params, **target_params}
    set_parts = []
    for idx, (field, value) in enumerate(updates.items()):
        field_name = _safe_identifier(field, "field")
        param_name = f"rupdate_{idx}"
        set_parts.append(f"r.{field_name} = ${param_name}")
        params[param_name] = value
    rows = await execute_cypher(
        f"""
        MATCH (s:Student {{id: $student_id}})-[]->(src:{source_type})
        MATCH (s)-[]->(dst:{target_type})
        MATCH (src)-[r:{relationship_type}]->(dst)
        WHERE {" AND ".join(source_clauses + target_clauses)}
        SET {", ".join(set_parts)}
        RETURN {{
            relationship_type: type(r),
            source: src {{.*}},
            target: dst {{.*}},
            relationship: properties(r)
        }} AS relation
        LIMIT 5
        """,
        params,
    )
    return {"relations": [row.get("relation", {}) for row in rows]}


async def _graph_soft_delete_node(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    label = _safe_identifier(arguments.get("entity_type", ""), "entity_type")
    match = arguments.get("match", {}) if isinstance(arguments.get("match", {}), dict) else {}
    clauses, params = _filter_clauses(match, "delete", "n")
    rows = await execute_cypher(
        f"""
        MATCH (s:Student {{id: $student_id}})-[r]->(n:{label})
        WHERE {" AND ".join(clauses)}
        SET n.status = 'superseded',
            n.superseded_at = datetime(),
            n.updated_at = datetime()
        RETURN n {{.*, _relationship: type(r)}} AS node
        LIMIT 5
        """,
        {"student_id": context.student_id, **params},
    )
    return {"nodes": [row.get("node", {}) for row in rows]}


async def _graph_soft_delete_relation(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    source_type = _safe_identifier(arguments.get("source_entity_type", ""), "source_entity_type")
    target_type = _safe_identifier(arguments.get("target_entity_type", ""), "target_entity_type")
    relationship_type = _safe_identifier(arguments.get("relationship_type", ""), "relationship_type")
    source_match = arguments.get("source_match", {}) if isinstance(arguments.get("source_match", {}), dict) else {}
    target_match = arguments.get("target_match", {}) if isinstance(arguments.get("target_match", {}), dict) else {}
    source_clauses, source_params = _filter_clauses(source_match, "dsrc", "src")
    target_clauses, target_params = _filter_clauses(target_match, "ddst", "dst")
    rows = await execute_cypher(
        f"""
        MATCH (s:Student {{id: $student_id}})-[]->(src:{source_type})
        MATCH (s)-[]->(dst:{target_type})
        MATCH (src)-[r:{relationship_type}]->(dst)
        WHERE {" AND ".join(source_clauses + target_clauses)}
        SET r.status = 'superseded',
            r.superseded_at = datetime(),
            r.updated_at = datetime()
        RETURN {{
            relationship_type: type(r),
            source: src {{.*}},
            target: dst {{.*}},
            relationship: properties(r)
        }} AS relation
        LIMIT 5
        """,
        {"student_id": context.student_id, **source_params, **target_params},
    )
    return {"relations": [row.get("relation", {}) for row in rows]}


_TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "get_profile_summary",
        "Return a compact summary of the current student's durable profile and core counts.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        _get_profile_summary,
    ),
    ToolSpec(
        "list_entity_types",
        "List available graph entity types and counts for the current student profile.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        _list_entity_types,
    ),
    ToolSpec(
        "typed_node_lookup",
        "Fetch student graph nodes by explicit entity type and exact field filters.",
        {
            "type": "object",
            "properties": {
                "entity_type": {"type": "string"},
                "filters": {"type": "object", "additionalProperties": {"type": "string"}},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["entity_type", "filters"],
            "additionalProperties": False,
        },
        _typed_node_lookup,
    ),
    ToolSpec(
        "typed_relation_lookup",
        "Fetch student graph relations by explicit relation type, target entity type, and exact target filters.",
        {
            "type": "object",
            "properties": {
                "relationship_type": {"type": "string"},
                "target_entity_type": {"type": "string"},
                "target_filters": {"type": "object", "additionalProperties": {"type": "string"}},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["relationship_type", "target_entity_type", "target_filters"],
            "additionalProperties": False,
        },
        _typed_relation_lookup,
    ),
    ToolSpec(
        "fetch_node_by_id",
        "Fetch a single graph node by explicit entity type and node id or name.",
        {
            "type": "object",
            "properties": {
                "entity_type": {"type": "string"},
                "node_id": {"type": "string"},
            },
            "required": ["entity_type", "node_id"],
            "additionalProperties": False,
        },
        _fetch_node_by_id,
    ),
    ToolSpec(
        "fetch_relation_detail",
        "Fetch a single relation using explicit relation type, target entity type, target field, and target value.",
        {
            "type": "object",
            "properties": {
                "relationship_type": {"type": "string"},
                "target_entity_type": {"type": "string"},
                "target_field": {"type": "string"},
                "target_value": {"type": "string"},
            },
            "required": ["relationship_type", "target_entity_type", "target_field", "target_value"],
            "additionalProperties": False,
        },
        _fetch_relation_detail,
    ),
    ToolSpec(
        "list_document_groups",
        "List the current student's stored documents grouped by semantic role.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        _list_document_groups,
    ),
    ToolSpec(
        "search_documents_semantic",
        "Run semantic search over the student's ingested documents.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        _search_documents_semantic,
    ),
    ToolSpec(
        "search_memory_semantic",
        "Search the student's durable memory and candidate facts using the provided query text.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        _search_memory_semantic,
    ),
    ToolSpec(
        "fetch_document_snippet",
        "Fetch a stored chunk by chunk id or the first few chunks for a document id.",
        {
            "type": "object",
            "properties": {
                "chunk_id": {"type": "string"},
                "document_id": {"type": "string"},
            },
            "additionalProperties": False,
        },
        _fetch_document_snippet,
    ),
    ToolSpec(
        "search_web",
        "Search the web for current or external information.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        _search_web,
    ),
    ToolSpec(
        "fetch_url",
        "Fetch a specific webpage URL and return its extracted content.",
        {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
            "additionalProperties": False,
        },
        _fetch_url,
    ),
    ToolSpec(
        "find_official_sources",
        "Search for likely official sources relevant to the query.",
        {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        _find_official_sources,
    ),
    ToolSpec(
        "get_recent_conversation_window",
        "Return the recent conversation turns available in the current session.",
        {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20}},
            "additionalProperties": False,
        },
        _get_recent_conversation_window,
    ),
    ToolSpec(
        "get_session_summary",
        "Return the compact session summary currently available for this chat.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        _get_session_summary,
    ),
    ToolSpec(
        "list_context_categories",
        "List what categories of graph, document, memory, and session context are available.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        _list_context_categories,
    ),
    ToolSpec(
        "view_durable_memory_summary",
        "Return a compact summary of durable profile memory, candidate facts, and saved recommendations.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        _view_durable_memory_summary,
    ),
    ToolSpec(
        "add_or_update_fact",
        "Persist a durable fact for the current student when there is strong evidence.",
        {
            "type": "object",
            "properties": {
                "fact_type": {"type": "string"},
                "value": {"type": "string"},
                "confidence": {"type": "number"},
                "salience": {"type": "number"},
                "source_ref": {"type": "string"},
            },
            "required": ["fact_type", "value"],
            "additionalProperties": False,
        },
        _add_or_update_fact,
    ),
    ToolSpec(
        "add_or_update_goal",
        "Persist a goal node for the current student.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "details": {"type": "string"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
        _add_or_update_goal,
    ),
    ToolSpec(
        "add_or_update_preference",
        "Persist a preference or small profile preference update for the current student.",
        {
            "type": "object",
            "properties": {
                "preference_key": {"type": "string"},
                "value": {"type": "string"},
                "summary": {"type": "string"},
            },
            "additionalProperties": False,
        },
        _add_or_update_preference,
    ),
    ToolSpec(
        "supersede_outdated_fact",
        "Soft-delete or supersede an existing memory or fact by id.",
        {
            "type": "object",
            "properties": {"fact_id": {"type": "string"}},
            "required": ["fact_id"],
            "additionalProperties": False,
        },
        _supersede_outdated_fact,
    ),
    ToolSpec(
        "graph_add_node",
        "Add a new student-linked graph node with an explicit entity type and relationship type.",
        {
            "type": "object",
            "properties": {
                "entity_type": {"type": "string"},
                "relationship_type": {"type": "string"},
                "properties": {"type": "object", "additionalProperties": True},
            },
            "required": ["entity_type", "properties"],
            "additionalProperties": False,
        },
        _graph_add_node,
    ),
    ToolSpec(
        "graph_update_node",
        "Update an existing student-linked graph node by explicit entity type, exact match fields, and update fields.",
        {
            "type": "object",
            "properties": {
                "entity_type": {"type": "string"},
                "match": {"type": "object", "additionalProperties": {"type": "string"}},
                "updates": {"type": "object", "additionalProperties": True},
            },
            "required": ["entity_type", "match", "updates"],
            "additionalProperties": False,
        },
        _graph_update_node,
    ),
    ToolSpec(
        "graph_add_relation",
        "Add an explicit relation between two existing graph nodes using typed source and target matches.",
        {
            "type": "object",
            "properties": {
                "source_entity_type": {"type": "string"},
                "source_match": {"type": "object", "additionalProperties": {"type": "string"}},
                "target_entity_type": {"type": "string"},
                "target_match": {"type": "object", "additionalProperties": {"type": "string"}},
                "relationship_type": {"type": "string"},
                "properties": {"type": "object", "additionalProperties": True},
            },
            "required": ["source_entity_type", "source_match", "target_entity_type", "target_match", "relationship_type"],
            "additionalProperties": False,
        },
        _graph_add_relation,
    ),
    ToolSpec(
        "graph_update_relation",
        "Update an explicit relation between two graph nodes using typed source and target matches.",
        {
            "type": "object",
            "properties": {
                "source_entity_type": {"type": "string"},
                "source_match": {"type": "object", "additionalProperties": {"type": "string"}},
                "target_entity_type": {"type": "string"},
                "target_match": {"type": "object", "additionalProperties": {"type": "string"}},
                "relationship_type": {"type": "string"},
                "updates": {"type": "object", "additionalProperties": True},
            },
            "required": ["source_entity_type", "source_match", "target_entity_type", "target_match", "relationship_type", "updates"],
            "additionalProperties": False,
        },
        _graph_update_relation,
    ),
    ToolSpec(
        "graph_soft_delete_node",
        "Soft-delete or supersede a graph node by explicit entity type and exact match fields.",
        {
            "type": "object",
            "properties": {
                "entity_type": {"type": "string"},
                "match": {"type": "object", "additionalProperties": {"type": "string"}},
            },
            "required": ["entity_type", "match"],
            "additionalProperties": False,
        },
        _graph_soft_delete_node,
    ),
    ToolSpec(
        "graph_soft_delete_relation",
        "Soft-delete or supersede a relation between two graph nodes by explicit typed source and target matches.",
        {
            "type": "object",
            "properties": {
                "source_entity_type": {"type": "string"},
                "source_match": {"type": "object", "additionalProperties": {"type": "string"}},
                "target_entity_type": {"type": "string"},
                "target_match": {"type": "object", "additionalProperties": {"type": "string"}},
                "relationship_type": {"type": "string"},
            },
            "required": ["source_entity_type", "source_match", "target_entity_type", "target_match", "relationship_type"],
            "additionalProperties": False,
        },
        _graph_soft_delete_relation,
    ),
)


def compact_result(result: dict[str, Any]) -> dict[str, Any]:
    """Keep tool messages bounded for tool-calling transcripts."""
    if not isinstance(result, dict):
        return {"value": str(result)[:_JSON_LIMIT]}
    serialized = json.dumps(result, ensure_ascii=True, default=str)
    if len(serialized) <= _JSON_LIMIT:
        return result
    return {"truncated": True, "preview": serialized[:_JSON_LIMIT]}
