# """Canonical MCP-style tool registry shared by internal and external callers."""

# from __future__ import annotations

# import json
# import logging
# import re
# from dataclasses import dataclass
# from typing import Any, Awaitable, Callable

# from mcp.types import Tool

# from app.adapters.neo4j.graph_store import (
#     create_entity,
#     ensure_student,
#     execute_cypher,
#     get_full_profile,
#     get_profile_schema,
#     get_relevant_memories,
#     list_saved_recommendations,
#     run_cypher,
#     store_candidate_fact,
#     update_student,
#     upsert_entity_for_student,
#     upsert_relationship_for_student,
#     upsert_profile_schema_section,
# )
# from app.adapters.neo4j.vector_store import hybrid_search
# from app.adapters.web_search.fallback_chain import search as web_search
# from app.adapters.web_search.url_fetcher import fetch_url_content
# from app.core.quality import build_session_summary
# from app.core.state import PathfinderState
# from app.tools.graph_tools import get_graph_tool_specs as get_new_graph_tool_specs
# from app.tools.vector_tools import get_vector_tool_specs as get_new_vector_tool_specs

# log = logging.getLogger("pathfinder.tools.registry")

# _IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# _DEFAULT_RELATIONSHIP = "HAS"
# _JSON_LIMIT = 8000
# _INTERNAL_SUPPORT_LABELS = {"CandidateFact", "MemoryItem", "Evidence", "Section", "SchemaSection"}


# @dataclass(frozen=True)
# class ToolContext:
#     """Execution context shared by tool handlers."""

#     student_id: str
#     session_id: str = ""
#     state: PathfinderState | None = None


# @dataclass(frozen=True)
# class ToolSpec:
#     """Canonical tool definition."""

#     name: str
#     description: str
#     input_schema: dict[str, Any]
#     handler: Callable[[dict[str, Any], ToolContext], Awaitable[dict[str, Any]]]

#     def as_openai_schema(self) -> dict[str, Any]:
#         schema = _schema_with_context_fields(self.input_schema)
#         return {
#             "type": "function",
#             "function": {
#                 "name": self.name,
#                 "description": self.description,
#                 "strict": True,
#                 "parameters": schema,
#             },
#         }

#     def as_mcp_tool(self) -> Tool:
#         schema = _schema_with_context_fields(self.input_schema)
#         return Tool(
#             name=self.name,
#             description=self.description,
#             inputSchema=schema,
#         )


# def get_tool_specs() -> list[ToolSpec]:
#     """Return every canonical tool spec."""
#     return list(_TOOL_SPECS)


# def get_new_neo4j_test_tool_specs() -> list[Any]:
#     """Return a tool surface that keeps non-Neo4j utilities and swaps in the new graph/vector backend."""
#     return list(_NEW_NEO4J_TEST_TOOL_SPECS)


# def get_tool_schemas() -> list[dict[str, Any]]:
#     """Return OpenAI-compatible tool schemas."""
#     return [spec.as_openai_schema() for spec in _TOOL_SPECS]


# def get_new_neo4j_test_tool_schemas() -> list[dict[str, Any]]:
#     """Return OpenAI-compatible tool schemas for the new Neo4j test surface."""
#     return [spec.as_openai_schema() for spec in _NEW_NEO4J_TEST_TOOL_SPECS]


# def get_mcp_tools() -> list[Tool]:
#     """Return MCP tool definitions."""
#     return [spec.as_mcp_tool() for spec in _TOOL_SPECS]


# def get_new_neo4j_test_mcp_tools() -> list[Tool]:
#     """Return MCP tool definitions for the new Neo4j test surface."""
#     return [spec.as_mcp_tool() for spec in _NEW_NEO4J_TEST_TOOL_SPECS]


# async def execute_tool(name: str, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     """Execute one registered tool, catching runtime errors so one bad call
#     does not abort the entire agentic loop."""
#     for spec in _TOOL_SPECS:
#         if spec.name == name:
#             try:
#                 return await spec.handler(arguments, context)
#             except Exception as exc:
#                 log.warning("Tool %s raised %s: %s", name, type(exc).__name__, exc)
#                 return {"error": f"{type(exc).__name__}: {exc}"}
#     return {"error": f"unknown tool: {name}"}


# async def execute_new_neo4j_test_tool(name: str, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     """Execute one tool from the new Neo4j test surface."""
#     for spec in _NEW_NEO4J_TEST_TOOL_SPECS:
#         if spec.name == name:
#             try:
#                 return await spec.handler(arguments, context)
#             except Exception as exc:
#                 log.warning("Tool %s raised %s: %s", name, type(exc).__name__, exc)
#                 return {"error": f"{type(exc).__name__}: {exc}"}
#     return {"error": f"unknown tool: {name}"}


# def _safe_identifier(value: str, kind: str) -> str:
#     value = str(value or "").strip()
#     if not _IDENTIFIER_RE.fullmatch(value):
#         raise ValueError(f"invalid {kind}: {value!r}")
#     return value


# def _tool_limit(value: Any, default: int = 5, maximum: int = 20) -> int:
#     try:
#         parsed = int(value)
#     except Exception:
#         parsed = default
#     return max(1, min(parsed, maximum))


# def _context_state(context: ToolContext) -> PathfinderState:
#     return context.state or {}


# def _schema_with_context_fields(schema: dict[str, Any]) -> dict[str, Any]:
#     """Add optional external caller context fields to every tool schema."""
#     copied = json.loads(json.dumps(schema))
#     properties = copied.setdefault("properties", {})
#     if isinstance(properties, dict):
#         properties.setdefault("student_id", {"type": "string"})
#         properties.setdefault("session_id", {"type": "string"})
#     return copied


# def _profile_small_facts(profile: dict[str, Any]) -> dict[str, Any]:
#     root = profile.get("root_properties", {}) if isinstance(profile.get("root_properties", {}), dict) else {}
#     sections = profile.get("sections", []) if isinstance(profile.get("sections", []), list) else []
#     all_entities = profile.get("all_entities", {}) if isinstance(profile.get("all_entities", {}), dict) else {}
#     section_names = [
#         str(item.get("label") or item.get("key") or "").strip()
#         for item in sections
#         if isinstance(item, dict) and str(item.get("label") or item.get("key") or "").strip()
#     ][:5]
#     entity_types = [
#         str(label).strip()
#         for label, items in all_entities.items()
#         if label not in _INTERNAL_SUPPORT_LABELS and isinstance(items, list) and items
#     ][:8]
#     return {
#         "name": str(root.get("name", "") or ""),
#         "institution": str(root.get("university", "") or ""),
#         "program": str(root.get("program", "") or ""),
#         "semester": str(root.get("semester", "") or ""),
#         "gpa": str(root.get("gpa", "") or ""),
#         "sections": section_names,
#         "entity_types": entity_types,
#     }


# async def _get_profile_summary(_: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     await ensure_student(context.student_id)
#     profile = await get_full_profile(context.student_id)
#     return {
#         "profile_summary": _profile_small_facts(profile),
#         "profile_schema": profile.get("profile_schema", {}),
#         "counts": {
#             "sections": len(profile.get("sections", [])),
#             "unsectioned_items": len(profile.get("unsectioned_items", [])),
#             "graph_entities": sum(
#                 len(items)
#                 for label, items in (profile.get("all_entities", {}) or {}).items()
#                 if label not in _INTERNAL_SUPPORT_LABELS
#             ),
#             "support_records": sum(
#                 len(items)
#                 for label, items in (profile.get("all_entities", {}) or {}).items()
#                 if label in _INTERNAL_SUPPORT_LABELS - {"Section", "SchemaSection"}
#             ),
#         },
#     }


# async def _get_profile_schema(_: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     return {"profile_schema": await get_profile_schema(context.student_id)}


# async def _upsert_profile_schema_section(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     key = str(arguments.get("key", "") or "").strip().lower()
#     label = str(arguments.get("label", "") or "").strip()
#     if not key or not label:
#         return {"error": "key and label are required"}
#     section = await upsert_profile_schema_section(
#         context.student_id,
#         key=key,
#         label=label,
#         description=str(arguments.get("description", "") or "").strip(),
#         purpose=str(arguments.get("purpose", "") or "").strip(),
#         parent_key=str(arguments.get("parent_key", "") or "").strip() or None,
#         confidence=float(arguments.get("confidence", 0.75) or 0.75),
#     )
#     return {"section": section}


# async def _update_student_profile(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     updates = arguments.get("updates", {}) if isinstance(arguments.get("updates", {}), dict) else {}
#     flat: dict[str, Any] = {}
#     for key, value in updates.items():
#         k = str(key).strip()
#         if not k:
#             continue
#         if isinstance(value, dict):
#             for sub_key, sub_value in value.items():
#                 sk = str(sub_key).strip()
#                 if sk and sub_value is not None and str(sub_value).strip():
#                     flat[sk] = str(sub_value).strip() if not isinstance(sub_value, (int, float, bool)) else sub_value
#         elif value is not None and str(value).strip():
#             flat[k] = str(value).strip() if not isinstance(value, (int, float, bool)) else value
#     if not flat:
#         return {"error": "no profile fields provided"}
#     updated = await update_student(context.student_id, **flat)
#     return {"updated_profile": updated}


# async def _upsert_graph_node(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     label = _safe_identifier(arguments.get("entity_type", ""), "entity_type")
#     relationship = _safe_identifier(arguments.get("relationship_type", _DEFAULT_RELATIONSHIP), "relationship_type")
#     identity = arguments.get("identity", {}) if isinstance(arguments.get("identity", {}), dict) else {}
#     properties = arguments.get("properties", {}) if isinstance(arguments.get("properties", {}), dict) else {}
#     section_key = str(arguments.get("section_key", "") or "").strip().lower() or None
#     if not identity and not properties:
#         return {"error": "identity or properties is required"}
#     entity = await upsert_entity_for_student(
#         label=label,
#         identity_props=identity,
#         properties=properties,
#         student_id=context.student_id,
#         relationship=relationship,
#         section_key=section_key,
#     )
#     return {"node": entity}


# async def _upsert_graph_relation(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     source_type = _safe_identifier(arguments.get("source_entity_type", ""), "source_entity_type")
#     target_type = _safe_identifier(arguments.get("target_entity_type", ""), "target_entity_type")
#     relationship_type = _safe_identifier(arguments.get("relationship_type", ""), "relationship_type")
#     source_identity = arguments.get("source_identity", {}) if isinstance(arguments.get("source_identity", {}), dict) else {}
#     target_identity = arguments.get("target_identity", {}) if isinstance(arguments.get("target_identity", {}), dict) else {}
#     properties = arguments.get("properties", {}) if isinstance(arguments.get("properties", {}), dict) else {}
#     if not source_identity or not target_identity:
#         return {"error": "source_identity and target_identity are required"}
#     relation = await upsert_relationship_for_student(
#         student_id=context.student_id,
#         source_label=source_type,
#         source_identity=source_identity,
#         relationship=relationship_type,
#         target_label=target_type,
#         target_identity=target_identity,
#         properties=properties,
#     )
#     return {"relation": relation}


# async def _list_entity_types(_: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     profile = await get_full_profile(context.student_id)
#     all_entities = profile.get("all_entities", {})
#     entity_counts = {
#         label: len(items)
#         for label, items in all_entities.items()
#         if isinstance(items, list) and items
#     }
#     return {"entity_types": sorted(entity_counts.keys()), "entity_counts": entity_counts}


# def _filter_clauses(filters: dict[str, Any], prefix: str, alias: str) -> tuple[list[str], dict[str, Any]]:
#     clauses: list[str] = []
#     params: dict[str, Any] = {}
#     for idx, (field, value) in enumerate((filters or {}).items()):
#         field_name = _safe_identifier(field, "field")
#         param_name = f"{prefix}_{idx}"
#         clauses.append(f"toString({alias}.{field_name}) = ${param_name}")
#         params[param_name] = str(value)
#     return clauses, params


# async def _typed_node_lookup(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     entity_type = _safe_identifier(arguments.get("entity_type", ""), "entity_type")
#     limit = _tool_limit(arguments.get("limit", 20), default=20, maximum=50)
#     filters = arguments.get("filters", {}) if isinstance(arguments.get("filters", {}), dict) else {}
#     clauses, params = _filter_clauses(filters, "node", "n")
#     where = " AND ".join(["s.id = $student_id"] + clauses)
#     rows = await run_cypher(
#         f"""
#         MATCH (s:Profile)
#         CALL {{
#             WITH s
#             MATCH (s)-[r]->(n:{entity_type})
#             WHERE type(r) <> 'HAS_SECTION' AND type(r) <> 'HAS_SCHEMA_SECTION'
#             RETURN n, type(r) AS rel_type, coalesce(n._schema_section, '') AS section_key
#             UNION
#             WITH s
#             MATCH (s)-[:HAS_SECTION|HAS_SCHEMA_SECTION]->(section:Section)-[:HAS_ITEM]->(n:{entity_type})
#             RETURN n, 'HAS_ITEM' AS rel_type, section.key AS section_key
#         }}
#         WITH s, n, rel_type, section_key
#         WHERE {where}
#         RETURN n {{.*, _relationship: rel_type, _schema_section: section_key}} AS node
#         ORDER BY coalesce(n.updated_at, n.created_at) DESC
#         LIMIT $limit
#         """,
#         {"student_id": context.student_id, "limit": limit, **params},
#     )
#     return {"entity_type": entity_type, "results": [row.get("node", {}) for row in rows]}


# async def _typed_relation_lookup(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     relationship_type = _safe_identifier(arguments.get("relationship_type", ""), "relationship_type")
#     target_type = _safe_identifier(arguments.get("target_entity_type", ""), "target_entity_type")
#     limit = _tool_limit(arguments.get("limit", 20), default=20, maximum=50)
#     filters = arguments.get("target_filters", {}) if isinstance(arguments.get("target_filters", {}), dict) else {}
#     clauses, params = _filter_clauses(filters, "rel", "n")
#     where = " AND ".join(["s.id = $student_id"] + clauses)
#     rows = await run_cypher(
#         f"""
#         MATCH (s:Profile)
#         CALL {{
#             WITH s
#             MATCH (s)-[r:{relationship_type}]->(n:{target_type})
#             RETURN r, n
#             UNION
#             WITH s
#             MATCH (s)-[:HAS_SECTION|HAS_SCHEMA_SECTION]->(:Section)-[:HAS_ITEM]->(n:{target_type})<-[r:{relationship_type}]-()
#             RETURN r, n
#         }}
#         WITH s, r, n
#         WHERE {where}
#         RETURN {{
#             relationship_type: type(r),
#             target: n {{.*}},
#             relationship: properties(r)
#         }} AS relation
#         LIMIT $limit
#         """,
#         {"student_id": context.student_id, "limit": limit, **params},
#     )
#     return {"relationship_type": relationship_type, "results": [row.get("relation", {}) for row in rows]}


# async def _fetch_node_by_id(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     node_id = str(arguments.get("node_id", "") or "").strip()
#     entity_type = _safe_identifier(arguments.get("entity_type", ""), "entity_type")
#     if not node_id:
#         return {"error": "node_id is required"}
#     rows = await run_cypher(
#         f"""
#         MATCH (s:Profile {{id: $student_id}})
#         CALL {{
#             WITH s
#             MATCH (s)-[r]->(n:{entity_type})
#             WHERE type(r) <> 'HAS_SECTION' AND type(r) <> 'HAS_SCHEMA_SECTION'
#             RETURN n, type(r) AS rel_type, coalesce(n._schema_section, '') AS section_key
#             UNION
#             WITH s
#             MATCH (s)-[:HAS_SECTION|HAS_SCHEMA_SECTION]->(section:Section)-[:HAS_ITEM]->(n:{entity_type})
#             RETURN n, 'HAS_ITEM' AS rel_type, section.key AS section_key
#         }}
#         WITH s, n, rel_type, section_key
#         WHERE toString(n.id) = $node_id OR toString(n.name) = $node_id
#         RETURN n {{.*, _relationship: rel_type, _schema_section: section_key}} AS node
#         LIMIT 1
#         """,
#         {"student_id": context.student_id, "node_id": node_id},
#     )
#     return {"node": rows[0].get("node", {}) if rows else {}}


# async def _fetch_relation_detail(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     relationship_type = _safe_identifier(arguments.get("relationship_type", ""), "relationship_type")
#     target_type = _safe_identifier(arguments.get("target_entity_type", ""), "target_entity_type")
#     target_field = _safe_identifier(arguments.get("target_field", "id"), "target_field")
#     target_value = str(arguments.get("target_value", "") or "").strip()
#     rows = await run_cypher(
#         f"""
#         MATCH (s:Profile {{id: $student_id}})
#         CALL {{
#             WITH s
#             MATCH (s)-[r:{relationship_type}]->(n:{target_type})
#             RETURN r, n
#             UNION
#             WITH s
#             MATCH (s)-[:HAS_SECTION|HAS_SCHEMA_SECTION]->(:Section)-[:HAS_ITEM]->(n:{target_type})<-[r:{relationship_type}]-()
#             RETURN r, n
#         }}
#         WITH r, n
#         WHERE toString(n.{target_field}) = $target_value
#         RETURN {{
#             relationship_type: type(r),
#             relationship: properties(r),
#             target: n {{.*}}
#         }} AS relation
#         LIMIT 1
#         """,
#         {"student_id": context.student_id, "target_value": target_value},
#     )
#     return {"relation": rows[0].get("relation", {}) if rows else {}}


# async def _list_document_groups(_: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     profile = await get_full_profile(context.student_id)
#     documents = ((profile.get("all_entities", {}) or {}).get("Document", [])) or []
#     groups: dict[str, int] = {}
#     for doc in documents:
#         if not isinstance(doc, dict):
#             continue
#         role = str(doc.get("document_role") or doc.get("doc_type") or doc.get("file_type") or "unknown")
#         groups[role] = groups.get(role, 0) + 1
#     return {"document_groups": groups, "documents": documents[:12]}


# async def _search_documents_semantic(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     query = str(arguments.get("query", "") or "").strip()
#     if not query:
#         return {"error": "query is required"}
#     limit = _tool_limit(arguments.get("limit", 5))
#     results = await hybrid_search(
#         query=query,
#         k=limit,
#         student_id=context.student_id,
#     )
#     trimmed = [
#         {
#             "id": item.get("id", ""),
#             "filename": item.get("filename", ""),
#             "page_number": item.get("page_number", ""),
#             "score": item.get("score", 0),
#             "text": str(item.get("text", "") or "")[:1200],
#         }
#         for item in results
#     ]
#     return {"query": query, "results": trimmed}


# async def _search_memory_semantic(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     query = str(arguments.get("query", "") or "").strip()
#     if not query:
#         return {"error": "query is required"}
#     limit = _tool_limit(arguments.get("limit", 8), default=8)
#     memories = await get_relevant_memories(context.student_id, query, limit=limit)
#     return memories


# async def _fetch_document_snippet(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     chunk_id = str(arguments.get("chunk_id", "") or "").strip()
#     document_id = str(arguments.get("document_id", "") or "").strip()
#     if not chunk_id and not document_id:
#         return {"error": "chunk_id or document_id is required"}
#     if chunk_id:
#         rows = await run_cypher(
#             """
#             MATCH (s:Profile {id: $student_id})-[:UPLOADED]->(:Document)<-[:FROM_DOCUMENT]-(c:Chunk {id: $chunk_id})
#             RETURN c {.*} AS chunk
#             LIMIT 1
#             """,
#             {"student_id": context.student_id, "chunk_id": chunk_id},
#         )
#         return {"chunk": rows[0].get("chunk", {}) if rows else {}}
#     rows = await run_cypher(
#         """
#         MATCH (s:Profile {id: $student_id})-[:UPLOADED]->(d:Document {id: $document_id})<-[:FROM_DOCUMENT]-(c:Chunk)
#         RETURN c {.*} AS chunk
#         ORDER BY c.chunk_index ASC
#         LIMIT 5
#         """,
#         {"student_id": context.student_id, "document_id": document_id},
#     )
#     return {"chunks": [row.get("chunk", {}) for row in rows]}


# async def _view_durable_memory_summary(_: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     profile = await get_full_profile(context.student_id)
#     saved = await list_saved_recommendations(context.student_id, limit=6)
#     memories = await get_relevant_memories(context.student_id, str((_context_state(context)).get("query", "") or ""), limit=6)
#     return {
#         "profile_facts": profile.get("profile_facts", [])[:10],
#         "candidate_fact_ledger": profile.get("candidate_fact_ledger", [])[:10],
#         "saved_recommendations": saved,
#         "memory_summary": memories,
#     }


# async def _add_or_update_fact(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     fact_type = str(arguments.get("fact_type", "") or "").strip().lower()
#     value = str(arguments.get("value", "") or "").strip()
#     confidence = float(arguments.get("confidence", 0.9) or 0.9)
#     salience = float(arguments.get("salience", 0.85) or 0.85)
#     source_ref = str(arguments.get("source_ref", context.session_id or "specialist_tool") or "specialist_tool")
#     if not fact_type or not value:
#         return {"error": "fact_type and value are required"}
#     record = await store_candidate_fact(
#         context.student_id,
#         fact_type,
#         value,
#         source_ref=source_ref,
#         confidence=confidence,
#         salience=salience,
#         status="resolved",
#         metadata={"tool": "add_or_update_fact", "session_id": context.session_id},
#     )
#     return {"fact": record}


# async def _add_or_update_goal(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     name = str(arguments.get("name", "") or "").strip()
#     if not name:
#         return {"error": "name is required"}
#     entity = await create_entity(
#         label="Goal",
#         properties={"name": name, "details": str(arguments.get("details", "") or "")},
#         student_id=context.student_id,
#         relationship="HAS_GOAL",
#     )
#     return {"goal": entity}


# async def _add_or_update_preference(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     summary = str(arguments.get("summary", "") or "").strip()
#     preference_key = str(arguments.get("preference_key", "") or "").strip()
#     if not summary and not preference_key:
#         return {"error": "summary or preference_key is required"}
#     if preference_key and preference_key in {"name", "gpa", "university", "program", "semester", "email"}:
#         updated = await update_student(context.student_id, **{preference_key: str(arguments.get("value", "") or "")})
#         return {"updated_profile": updated}
#     entity = await create_entity(
#         label="Preference",
#         properties={"name": preference_key or summary, "value": str(arguments.get("value", summary) or summary)},
#         student_id=context.student_id,
#         relationship="PREFERS",
#     )
#     return {"preference": entity}


# async def _supersede_outdated_fact(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     fact_id = str(arguments.get("fact_id", "") or "").strip()
#     if not fact_id:
#         return {"error": "fact_id is required"}
#     rows = await execute_cypher(
#         """
#         MATCH (s:Profile {id: $student_id})-[:HAS_CANDIDATE_FACT|HAS_MEMORY]->(n)
#         WHERE n.id = $fact_id
#         SET n.status = 'superseded',
#             n.superseded_at = datetime(),
#             n.updated_at = datetime()
#         RETURN n {.*} AS item
#         """,
#         {"student_id": context.student_id, "fact_id": fact_id},
#     )
#     return {"item": rows[0].get("item", {}) if rows else {}}


# async def _graph_add_node(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     label = _safe_identifier(arguments.get("entity_type", ""), "entity_type")
#     relationship = _safe_identifier(arguments.get("relationship_type", _DEFAULT_RELATIONSHIP), "relationship_type")
#     properties = arguments.get("properties", {}) if isinstance(arguments.get("properties", {}), dict) else {}
#     section_key = str(arguments.get("section_key", "") or "").strip().lower() or None
#     identity = {}
#     for key in ("name", "code", "id", "key"):
#         if key in properties and properties[key]:
#             identity[key] = properties[key]
#     entity = await upsert_entity_for_student(
#         label=label,
#         identity_props=identity,
#         properties=properties,
#         student_id=context.student_id,
#         relationship=relationship,
#         section_key=section_key,
#     )
#     return {"node": entity}


# async def _graph_update_node(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     label = _safe_identifier(arguments.get("entity_type", ""), "entity_type")
#     filters = arguments.get("match", {}) if isinstance(arguments.get("match", {}), dict) else {}
#     updates = arguments.get("updates", {}) if isinstance(arguments.get("updates", {}), dict) else {}
#     if not filters or not updates:
#         return {"error": "match and updates are required"}
#     where_parts, params = _filter_clauses(filters, "match", "n")
#     set_parts = []
#     for idx, (field, value) in enumerate(updates.items()):
#         field_name = _safe_identifier(field, "field")
#         param_name = f"update_{idx}"
#         set_parts.append(f"n.{field_name} = ${param_name}")
#         params[param_name] = value
#     rows = await execute_cypher(
#         f"""
#         MATCH (s:Profile {{id: $student_id}})
#         CALL {{
#             WITH s
#             MATCH (s)-[r]->(n:{label})
#             WHERE type(r) <> 'HAS_SECTION' AND type(r) <> 'HAS_SCHEMA_SECTION'
#             RETURN n, type(r) AS rel_type
#             UNION
#             WITH s
#             MATCH (s)-[:HAS_SECTION|HAS_SCHEMA_SECTION]->(:Section)-[:HAS_ITEM]->(n:{label})
#             RETURN n, 'HAS_ITEM' AS rel_type
#         }}
#         WITH n, rel_type
#         WHERE {" AND ".join(where_parts)}
#         SET {", ".join(set_parts)}, n.updated_at = datetime()
#         RETURN n {{.*, _relationship: rel_type}} AS node
#         LIMIT 5
#         """,
#         {"student_id": context.student_id, **params},
#     )
#     return {"updated_nodes": [row.get("node", {}) for row in rows]}


# async def _graph_add_relation(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     source_type = _safe_identifier(arguments.get("source_entity_type", ""), "source_entity_type")
#     target_type = _safe_identifier(arguments.get("target_entity_type", ""), "target_entity_type")
#     relationship_type = _safe_identifier(arguments.get("relationship_type", ""), "relationship_type")
#     source_match = arguments.get("source_match", {}) if isinstance(arguments.get("source_match", {}), dict) else {}
#     target_match = arguments.get("target_match", {}) if isinstance(arguments.get("target_match", {}), dict) else {}
#     properties = arguments.get("properties", {}) if isinstance(arguments.get("properties", {}), dict) else {}
#     source_clauses, source_params = _filter_clauses(source_match, "src", "src")
#     target_clauses, target_params = _filter_clauses(target_match, "dst", "dst")
#     property_set = []
#     params: dict[str, Any] = {"student_id": context.student_id, **source_params, **target_params}
#     for idx, (field, value) in enumerate(properties.items()):
#         field_name = _safe_identifier(field, "field")
#         param_name = f"rel_{idx}"
#         property_set.append(f"r.{field_name} = ${param_name}")
#         params[param_name] = value
#     rows = await execute_cypher(
#         f"""
#         MATCH (s:Profile {{id: $student_id}})
#         CALL {{
#             WITH s
#             MATCH (s)-[]->(src:{source_type})
#             RETURN src
#             UNION
#             WITH s
#             MATCH (s)-[:HAS_SECTION|HAS_SCHEMA_SECTION]->(:Section)-[:HAS_ITEM]->(src:{source_type})
#             RETURN src
#         }}
#         CALL {{
#             WITH s
#             MATCH (s)-[]->(dst:{target_type})
#             RETURN dst
#             UNION
#             WITH s
#             MATCH (s)-[:HAS_SECTION|HAS_SCHEMA_SECTION]->(:Section)-[:HAS_ITEM]->(dst:{target_type})
#             RETURN dst
#         }}
#         WITH src, dst
#         WHERE {" AND ".join(source_clauses + target_clauses)}
#         MERGE (src)-[r:{relationship_type}]->(dst)
#         {"SET " + ", ".join(property_set) if property_set else ""}
#         RETURN {{
#             relationship_type: type(r),
#             source: src {{.*}},
#             target: dst {{.*}},
#             relationship: properties(r)
#         }} AS relation
#         LIMIT 5
#         """,
#         params,
#     )
#     return {"relations": [row.get("relation", {}) for row in rows]}


# async def _graph_update_relation(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     source_type = _safe_identifier(arguments.get("source_entity_type", ""), "source_entity_type")
#     target_type = _safe_identifier(arguments.get("target_entity_type", ""), "target_entity_type")
#     relationship_type = _safe_identifier(arguments.get("relationship_type", ""), "relationship_type")
#     source_match = arguments.get("source_match", {}) if isinstance(arguments.get("source_match", {}), dict) else {}
#     target_match = arguments.get("target_match", {}) if isinstance(arguments.get("target_match", {}), dict) else {}
#     updates = arguments.get("updates", {}) if isinstance(arguments.get("updates", {}), dict) else {}
#     source_clauses, source_params = _filter_clauses(source_match, "usrc", "src")
#     target_clauses, target_params = _filter_clauses(target_match, "udst", "dst")
#     params: dict[str, Any] = {"student_id": context.student_id, **source_params, **target_params}
#     set_parts = []
#     for idx, (field, value) in enumerate(updates.items()):
#         field_name = _safe_identifier(field, "field")
#         param_name = f"rupdate_{idx}"
#         set_parts.append(f"r.{field_name} = ${param_name}")
#         params[param_name] = value
#     rows = await execute_cypher(
#         f"""
#         MATCH (s:Profile {{id: $student_id}})
#         CALL {{
#             WITH s
#             MATCH (s)-[]->(src:{source_type})
#             RETURN src
#             UNION
#             WITH s
#             MATCH (s)-[:HAS_SECTION|HAS_SCHEMA_SECTION]->(:Section)-[:HAS_ITEM]->(src:{source_type})
#             RETURN src
#         }}
#         CALL {{
#             WITH s
#             MATCH (s)-[]->(dst:{target_type})
#             RETURN dst
#             UNION
#             WITH s
#             MATCH (s)-[:HAS_SECTION|HAS_SCHEMA_SECTION]->(:Section)-[:HAS_ITEM]->(dst:{target_type})
#             RETURN dst
#         }}
#         WITH src, dst
#         WHERE {" AND ".join(source_clauses + target_clauses)}
#         MATCH (src)-[r:{relationship_type}]->(dst)
#         SET {", ".join(set_parts)}
#         RETURN {{
#             relationship_type: type(r),
#             source: src {{.*}},
#             target: dst {{.*}},
#             relationship: properties(r)
#         }} AS relation
#         LIMIT 5
#         """,
#         params,
#     )
#     return {"relations": [row.get("relation", {}) for row in rows]}


# async def _graph_soft_delete_node(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     label = _safe_identifier(arguments.get("entity_type", ""), "entity_type")
#     match = arguments.get("match", {}) if isinstance(arguments.get("match", {}), dict) else {}
#     clauses, params = _filter_clauses(match, "delete", "n")
#     rows = await execute_cypher(
#         f"""
#         MATCH (s:Profile {{id: $student_id}})
#         CALL {{
#             WITH s
#             MATCH (s)-[r]->(n:{label})
#             WHERE type(r) <> 'HAS_SECTION' AND type(r) <> 'HAS_SCHEMA_SECTION'
#             RETURN n, type(r) AS rel_type
#             UNION
#             WITH s
#             MATCH (s)-[:HAS_SECTION|HAS_SCHEMA_SECTION]->(:Section)-[:HAS_ITEM]->(n:{label})
#             RETURN n, 'HAS_ITEM' AS rel_type
#         }}
#         WITH n, rel_type
#         WHERE {" AND ".join(clauses)}
#         SET n.status = 'superseded',
#             n.superseded_at = datetime(),
#             n.updated_at = datetime()
#         RETURN n {{.*, _relationship: rel_type}} AS node
#         LIMIT 5
#         """,
#         {"student_id": context.student_id, **params},
#     )
#     return {"nodes": [row.get("node", {}) for row in rows]}


# async def _graph_soft_delete_relation(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
#     source_type = _safe_identifier(arguments.get("source_entity_type", ""), "source_entity_type")
#     target_type = _safe_identifier(arguments.get("target_entity_type", ""), "target_entity_type")
#     relationship_type = _safe_identifier(arguments.get("relationship_type", ""), "relationship_type")
#     source_match = arguments.get("source_match", {}) if isinstance(arguments.get("source_match", {}), dict) else {}
#     target_match = arguments.get("target_match", {}) if isinstance(arguments.get("target_match", {}), dict) else {}
#     source_clauses, source_params = _filter_clauses(source_match, "dsrc", "src")
#     target_clauses, target_params = _filter_clauses(target_match, "ddst", "dst")
#     rows = await execute_cypher(
#         f"""
#         MATCH (s:Profile {{id: $student_id}})
#         CALL {{
#             WITH s
#             MATCH (s)-[]->(src:{source_type})
#             RETURN src
#             UNION
#             WITH s
#             MATCH (s)-[:HAS_SECTION|HAS_SCHEMA_SECTION]->(:Section)-[:HAS_ITEM]->(src:{source_type})
#             RETURN src
#         }}
#         CALL {{
#             WITH s
#             MATCH (s)-[]->(dst:{target_type})
#             RETURN dst
#             UNION
#             WITH s
#             MATCH (s)-[:HAS_SECTION|HAS_SCHEMA_SECTION]->(:Section)-[:HAS_ITEM]->(dst:{target_type})
#             RETURN dst
#         }}
#         WITH src, dst
#         WHERE {" AND ".join(source_clauses + target_clauses)}
#         MATCH (src)-[r:{relationship_type}]->(dst)
#         SET r.status = 'superseded',
#             r.superseded_at = datetime(),
#             r.updated_at = datetime()
#         RETURN {{
#             relationship_type: type(r),
#             source: src {{.*}},
#             target: dst {{.*}},
#             relationship: properties(r)
#         }} AS relation
#         LIMIT 5
#         """,
#         {"student_id": context.student_id, **source_params, **target_params},
#     )
#     return {"relations": [row.get("relation", {}) for row in rows]}



# _TOOL_SPECS: tuple[ToolSpec, ...] = (
#     ToolSpec(
#         "get_profile_summary",
#         "Return a compact summary of the current student's durable profile and core counts.",
#         {"type": "object", "properties": {}, "additionalProperties": False},
#         _get_profile_summary,
#     ),
#     ToolSpec(
#         "get_profile_schema",
#         "Return the current student's reusable profile schema sections and descriptions.",
#         {"type": "object", "properties": {}, "additionalProperties": False},
#         _get_profile_schema,
#     ),
#     ToolSpec(
#         "upsert_profile_schema_section",
#         "Create or update one reusable profile schema section for the current student.",
#         {
#             "type": "object",
#             "properties": {
#                 "key": {"type": "string"},
#                 "label": {"type": "string"},
#                 "description": {"type": "string"},
#                 "purpose": {"type": "string"},
#                 "parent_key": {"type": "string"},
#                 "confidence": {"type": "number", "minimum": 0, "maximum": 1},
#             },
#             "required": ["key", "label"],
#             "additionalProperties": False,
#         },
#         _upsert_profile_schema_section,
#     ),
#     ToolSpec(
#         "update_student_profile",
#         "Update supported top-level student profile fields for the current student.",
#         {
#             "type": "object",
#             "properties": {
#                 "updates": {"type": "object", "additionalProperties": {"type": "string"}},
#             },
#             "required": ["updates"],
#             "additionalProperties": False,
#         },
#         _update_student_profile,
#     ),
#     ToolSpec(
#         "list_entity_types",
#         "List available graph entity types and counts for the current student profile.",
#         {"type": "object", "properties": {}, "additionalProperties": False},
#         _list_entity_types,
#     ),
#     ToolSpec(
#         "typed_node_lookup",
#         "Fetch student graph nodes by explicit entity type and exact field filters.",
#         {
#             "type": "object",
#             "properties": {
#                 "entity_type": {"type": "string"},
#                 "filters": {"type": "object", "additionalProperties": {"type": "string"}},
#                 "limit": {"type": "integer", "minimum": 1, "maximum": 20},
#             },
#             "required": ["entity_type", "filters"],
#             "additionalProperties": False,
#         },
#         _typed_node_lookup,
#     ),
#     ToolSpec(
#         "typed_relation_lookup",
#         "Fetch student graph relations by explicit relation type, target entity type, and exact target filters.",
#         {
#             "type": "object",
#             "properties": {
#                 "relationship_type": {"type": "string"},
#                 "target_entity_type": {"type": "string"},
#                 "target_filters": {"type": "object", "additionalProperties": {"type": "string"}},
#                 "limit": {"type": "integer", "minimum": 1, "maximum": 20},
#             },
#             "required": ["relationship_type", "target_entity_type", "target_filters"],
#             "additionalProperties": False,
#         },
#         _typed_relation_lookup,
#     ),
#     ToolSpec(
#         "fetch_node_by_id",
#         "Fetch a single graph node by explicit entity type and node id or name.",
#         {
#             "type": "object",
#             "properties": {
#                 "entity_type": {"type": "string"},
#                 "node_id": {"type": "string"},
#             },
#             "required": ["entity_type", "node_id"],
#             "additionalProperties": False,
#         },
#         _fetch_node_by_id,
#     ),
#     ToolSpec(
#         "fetch_relation_detail",
#         "Fetch a single relation using explicit relation type, target entity type, target field, and target value.",
#         {
#             "type": "object",
#             "properties": {
#                 "relationship_type": {"type": "string"},
#                 "target_entity_type": {"type": "string"},
#                 "target_field": {"type": "string"},
#                 "target_value": {"type": "string"},
#             },
#             "required": ["relationship_type", "target_entity_type", "target_field", "target_value"],
#             "additionalProperties": False,
#         },
#         _fetch_relation_detail,
#     ),
#     ToolSpec(
#         "list_document_groups",
#         "List the current student's stored documents grouped by semantic role.",
#         {"type": "object", "properties": {}, "additionalProperties": False},
#         _list_document_groups,
#     ),
#     ToolSpec(
#         "search_documents_semantic",
#         "Run semantic search over the student's ingested documents.",
#         {
#             "type": "object",
#             "properties": {
#                 "query": {"type": "string"},
#                 "limit": {"type": "integer", "minimum": 1, "maximum": 20},
#             },
#             "required": ["query"],
#             "additionalProperties": False,
#         },
#         _search_documents_semantic,
#     ),
#     ToolSpec(
#         "search_memory_semantic",
#         "Search the student's durable memory and candidate facts using the provided query text.",
#         {
#             "type": "object",
#             "properties": {
#                 "query": {"type": "string"},
#                 "limit": {"type": "integer", "minimum": 1, "maximum": 20},
#             },
#             "required": ["query"],
#             "additionalProperties": False,
#         },
#         _search_memory_semantic,
#     ),
#     ToolSpec(
#         "fetch_document_snippet",
#         "Fetch a stored chunk by chunk id or the first few chunks for a document id.",
#         {
#             "type": "object",
#             "properties": {
#                 "chunk_id": {"type": "string"},
#                 "document_id": {"type": "string"},
#             },
#             "additionalProperties": False,
#         },
#         _fetch_document_snippet,
#     ),
#     ToolSpec(
#         "view_durable_memory_summary",
#         "Return a compact summary of durable profile memory, candidate facts, and saved recommendations.",
#         {"type": "object", "properties": {}, "additionalProperties": False},
#         _view_durable_memory_summary,
#     ),
#     ToolSpec(
#         "add_or_update_fact",
#         "Persist a durable fact for the current student when there is strong evidence.",
#         {
#             "type": "object",
#             "properties": {
#                 "fact_type": {"type": "string"},
#                 "value": {"type": "string"},
#                 "confidence": {"type": "number"},
#                 "salience": {"type": "number"},
#                 "source_ref": {"type": "string"},
#             },
#             "required": ["fact_type", "value"],
#             "additionalProperties": False,
#         },
#         _add_or_update_fact,
#     ),
#     ToolSpec(
#         "add_or_update_goal",
#         "Persist a goal node for the current student.",
#         {
#             "type": "object",
#             "properties": {
#                 "name": {"type": "string"},
#                 "details": {"type": "string"},
#             },
#             "required": ["name"],
#             "additionalProperties": False,
#         },
#         _add_or_update_goal,
#     ),
#     ToolSpec(
#         "add_or_update_preference",
#         "Persist a preference or small profile preference update for the current student.",
#         {
#             "type": "object",
#             "properties": {
#                 "preference_key": {"type": "string"},
#                 "value": {"type": "string"},
#                 "summary": {"type": "string"},
#             },
#             "additionalProperties": False,
#         },
#         _add_or_update_preference,
#     ),
#     ToolSpec(
#         "supersede_outdated_fact",
#         "Soft-delete or supersede an existing memory or fact by id.",
#         {
#             "type": "object",
#             "properties": {"fact_id": {"type": "string"}},
#             "required": ["fact_id"],
#             "additionalProperties": False,
#         },
#         _supersede_outdated_fact,
#     ),
#     ToolSpec(
#         "graph_add_node",
#         "Add a new student-linked graph node with an explicit entity type. Always pass section_key to organize under the right schema section.",
#         {
#             "type": "object",
#             "properties": {
#                 "entity_type": {"type": "string"},
#                 "relationship_type": {"type": "string"},
#                 "section_key": {"type": "string"},
#                 "properties": {"type": "object", "additionalProperties": True},
#             },
#             "required": ["entity_type", "properties"],
#             "additionalProperties": False,
#         },
#         _graph_add_node,
#     ),
#     ToolSpec(
#         "upsert_graph_node",
#         "Create or update a student-linked graph node using identity fields and rich properties.",
#         {
#             "type": "object",
#             "properties": {
#                 "entity_type": {"type": "string"},
#                 "relationship_type": {"type": "string"},
#                 "section_key": {"type": "string"},
#                 "identity": {"type": "object", "additionalProperties": {"type": "string"}},
#                 "properties": {"type": "object", "additionalProperties": True},
#             },
#             "required": ["entity_type", "properties"],
#             "additionalProperties": False,
#         },
#         _upsert_graph_node,
#     ),
#     ToolSpec(
#         "graph_update_node",
#         "Update an existing student-linked graph node by explicit entity type, exact match fields, and update fields.",
#         {
#             "type": "object",
#             "properties": {
#                 "entity_type": {"type": "string"},
#                 "match": {"type": "object", "additionalProperties": {"type": "string"}},
#                 "updates": {"type": "object", "additionalProperties": True},
#             },
#             "required": ["entity_type", "match", "updates"],
#             "additionalProperties": False,
#         },
#         _graph_update_node,
#     ),
#     ToolSpec(
#         "graph_add_relation",
#         "Add an explicit relation between two existing graph nodes using typed source and target matches.",
#         {
#             "type": "object",
#             "properties": {
#                 "source_entity_type": {"type": "string"},
#                 "source_match": {"type": "object", "additionalProperties": {"type": "string"}},
#                 "target_entity_type": {"type": "string"},
#                 "target_match": {"type": "object", "additionalProperties": {"type": "string"}},
#                 "relationship_type": {"type": "string"},
#                 "properties": {"type": "object", "additionalProperties": True},
#             },
#             "required": ["source_entity_type", "source_match", "target_entity_type", "target_match", "relationship_type"],
#             "additionalProperties": False,
#         },
#         _graph_add_relation,
#     ),
#     ToolSpec(
#         "upsert_graph_relation",
#         "Create or update an explicit relation between two student graph nodes using identity matches.",
#         {
#             "type": "object",
#             "properties": {
#                 "source_entity_type": {"type": "string"},
#                 "source_identity": {"type": "object", "additionalProperties": {"type": "string"}},
#                 "target_entity_type": {"type": "string"},
#                 "target_identity": {"type": "object", "additionalProperties": {"type": "string"}},
#                 "relationship_type": {"type": "string"},
#                 "properties": {"type": "object", "additionalProperties": True},
#             },
#             "required": ["source_entity_type", "source_identity", "target_entity_type", "target_identity", "relationship_type"],
#             "additionalProperties": False,
#         },
#         _upsert_graph_relation,
#     ),
#     ToolSpec(
#         "graph_update_relation",
#         "Update an explicit relation between two graph nodes using typed source and target matches.",
#         {
#             "type": "object",
#             "properties": {
#                 "source_entity_type": {"type": "string"},
#                 "source_match": {"type": "object", "additionalProperties": {"type": "string"}},
#                 "target_entity_type": {"type": "string"},
#                 "target_match": {"type": "object", "additionalProperties": {"type": "string"}},
#                 "relationship_type": {"type": "string"},
#                 "updates": {"type": "object", "additionalProperties": True},
#             },
#             "required": ["source_entity_type", "source_match", "target_entity_type", "target_match", "relationship_type", "updates"],
#             "additionalProperties": False,
#         },
#         _graph_update_relation,
#     ),
#     ToolSpec(
#         "graph_soft_delete_node",
#         "Soft-delete or supersede a graph node by explicit entity type and exact match fields.",
#         {
#             "type": "object",
#             "properties": {
#                 "entity_type": {"type": "string"},
#                 "match": {"type": "object", "additionalProperties": {"type": "string"}},
#             },
#             "required": ["entity_type", "match"],
#             "additionalProperties": False,
#         },
#         _graph_soft_delete_node,
#     ),
#     ToolSpec(
#         "graph_soft_delete_relation",
#         "Soft-delete or supersede a relation between two graph nodes by explicit typed source and target matches.",
#         {
#             "type": "object",
#             "properties": {
#                 "source_entity_type": {"type": "string"},
#                 "source_match": {"type": "object", "additionalProperties": {"type": "string"}},
#                 "target_entity_type": {"type": "string"},
#                 "target_match": {"type": "object", "additionalProperties": {"type": "string"}},
#                 "relationship_type": {"type": "string"},
#             },
#             "required": ["source_entity_type", "source_match", "target_entity_type", "target_match", "relationship_type"],
#             "additionalProperties": False,
#         },
#         _graph_soft_delete_relation,
#     ),
# )

# _NON_NEO4J_TOOL_NAMES: frozenset[str] = frozenset(
#     {
#         "search_web",
#         "fetch_url",
#         "find_official_sources",
#         "get_recent_conversation_window",
#         "get_session_summary",
#         "list_context_categories",
#         "respond",
#     }
# )

# _NON_NEO4J_TOOL_SPECS: tuple[ToolSpec, ...] = tuple(
#     spec for spec in _TOOL_SPECS if spec.name in _NON_NEO4J_TOOL_NAMES
# )

# _NEW_NEO4J_TOOL_SPECS: tuple[Any, ...] = tuple(
#     [
#         *get_new_graph_tool_specs(),
#         *get_new_vector_tool_specs(),
#     ]
# )

# _NEW_NEO4J_TEST_TOOL_SPECS: tuple[Any, ...] = (
#     *_NON_NEO4J_TOOL_SPECS,
#     *_NEW_NEO4J_TOOL_SPECS,
# )


# def compact_result(result: dict[str, Any]) -> dict[str, Any]:
#     """Keep tool messages bounded for tool-calling transcripts."""
#     if not isinstance(result, dict):
#         return {"value": str(result)[:_JSON_LIMIT]}
#     serialized = json.dumps(result, ensure_ascii=True, default=str)
#     if len(serialized) <= _JSON_LIMIT:
#         return result
#     return {"truncated": True, "preview": serialized[:_JSON_LIMIT]}
