"""Legacy compatibility shim for Neo4j graph access.

This module keeps older imports working while the new GraphDB/VectorDB backend
is being tested. The goal is bootability and basic ingestion support, not full
feature parity with the old graph_store implementation.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase

from app.adapters.neo4j._sanitize import sanitize_neo4j_value
from app.adapters.neo4j.graphDB import GraphDB
from app.config.settings import settings
from app.utils.ids import generate_evidence_id, generate_memory_id

log = logging.getLogger("pathfinder.neo4j.graph_store")

_driver: AsyncDriver | None = None


async def _graph_db() -> GraphDB:
    """Return the new GraphDB adapter on the shared driver."""
    return GraphDB(await get_driver())


async def get_driver() -> AsyncDriver:
    """Return or create the shared Neo4j driver."""
    global _driver
    if _driver is None:
        if not str(settings.NEO4J_PASSWORD or "").strip():
            raise RuntimeError("NEO4J_PASSWORD is not configured.")
        _driver = AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )
    return _driver


async def close_driver() -> None:
    """Close the shared Neo4j driver."""
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None


async def init_schema() -> None:
    """Initialize the new GraphDB schema through the compatibility layer."""
    await (await _graph_db()).init_schema()


async def run_cypher(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Execute arbitrary Cypher and return rows as dictionaries."""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(query, **(params or {}))
        rows: list[dict[str, Any]] = []
        async for record in result:
            rows.append(sanitize_neo4j_value({key: record[key] for key in record.keys()}))
    return sanitize_neo4j_value(rows)


async def execute_cypher(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Backward-compatible alias for run_cypher."""
    return await run_cypher(query, params)


async def ensure_student(student_id: str) -> dict[str, Any]:
    """Ensure the root student node exists."""
    return await (await _graph_db()).upsert_student(student_id=student_id)


async def create_student(student_id: str, name: str | None = None) -> dict[str, Any]:
    """Create or return one student node."""
    student = await ensure_student(student_id)
    if name:
        await update_student(student_id, name=name)
        student = await get_student(student_id) or student
    return student


async def get_student(student_id: str) -> dict[str, Any] | None:
    """Fetch one student node by id."""
    rows = await run_cypher(
        """
        MATCH (s:Student {id: $student_id})
        RETURN s {.*} AS student
        LIMIT 1
        """,
        {"student_id": student_id},
    )
    return rows[0].get("student") if rows else None


async def list_students() -> list[dict[str, Any]]:
    """Return every student root node."""
    rows = await run_cypher(
        """
        MATCH (s:Student)
        RETURN s {.*} AS student
        ORDER BY coalesce(s.updated_at, s.created_at) DESC
        """
    )
    return [row.get("student", {}) for row in rows]


async def update_student(student_id: str, **updates: Any) -> dict[str, Any]:
    """Update scalar properties on the root student node."""
    if not updates:
        return await ensure_student(student_id)
    assignments: list[str] = ["s.updated_at = datetime()"]
    params: dict[str, Any] = {"student_id": student_id}
    for idx, (key, value) in enumerate(updates.items()):
        if value is None:
            continue
        field = str(key or "").strip()
        if not field:
            continue
        param = f"value_{idx}"
        assignments.append(f"s.`{field}` = ${param}")
        params[param] = value
    await run_cypher(
        f"""
        MERGE (s:Student {{id: $student_id}})
        ON CREATE SET s.created_at = datetime()
        SET {", ".join(assignments)}
        """,
        params,
    )
    return await get_student(student_id) or {"id": student_id}


async def store_document_node(
    *,
    document_id: str,
    filename: str,
    student_id: str,
    doc_type: str | None = None,
    file_type: str = "unknown",
    **_: Any,
) -> dict[str, Any]:
    """Create or update one document node for the new backend."""
    document = await (await _graph_db()).create_document(
        student_id=student_id,
        document_id=document_id,
        filename=filename,
        file_type=file_type or str(doc_type or "unknown"),
    )
    if doc_type:
        await run_cypher(
            """
            MATCH (d:Document {id: $document_id})
            SET d.doc_type = $doc_type
            """,
            {"document_id": document_id, "doc_type": doc_type},
        )
        document["doc_type"] = doc_type
    return document


async def find_document_by_filename(student_id: str, filename: str) -> dict[str, Any] | None:
    """Find one document for a student by filename."""
    rows = await run_cypher(
        """
        MATCH (:Student {id: $student_id})-[:UPLOADED]->(d:Document {filename: $filename})
        RETURN d {.*} AS document
        LIMIT 1
        """,
        {"student_id": student_id, "filename": filename},
    )
    return rows[0].get("document") if rows else None


async def get_profile_schema(student_id: str) -> dict[str, Any]:
    """Return a lightweight section schema for the student."""
    sections = await (await _graph_db()).get_student_sections(student_id=student_id)
    return {"sections": sections}


async def get_full_profile(student_id: str) -> dict[str, Any]:
    """Return a compatibility-shaped full profile payload."""
    from app.adapters.neo4j.vectorDB import VectorDB

    student_graph = await (await _graph_db()).get_full_student(student_id=student_id)
    student = dict(student_graph.get("student") or {})
    sections = list(student_graph.get("sections") or [])
    entities = list(student_graph.get("entities") or [])

    all_entities: dict[str, list[dict[str, Any]]] = {"Document": [], "Chunk": []}
    for entity in entities:
        entity_type = str(entity.get("entity_type") or "Entity")
        all_entities.setdefault(entity_type, []).append(entity)
    document_rows = await run_cypher(
        """
        MATCH (:Student {id: $student_id})-[:UPLOADED]->(d:Document)
        RETURN d {.*} AS document
        """,
        {"student_id": student_id},
    )
    chunk_rows = await VectorDB(
        await get_driver(),
        index_name="chunk_embeddings",
        dimensions=int(settings.EMBEDDING_DIMENSIONS),
    ).get_chunks_for_student(student_id=student_id)
    all_entities["Document"] = [row.get("document", {}) for row in document_rows]
    all_entities["Chunk"] = chunk_rows
    return sanitize_neo4j_value({
        "root_properties": student,
        "sections": sections,
        "profile_schema": await get_profile_schema(student_id),
        "all_entities": all_entities,
        "unsectioned_items": [],
    })


async def get_graph_data(student_id: str) -> dict[str, Any]:
    """Return graph/profile data for compatibility callers."""
    return await get_full_profile(student_id)


async def upsert_profile_schema_section(
    student_id: str,
    *,
    key: str,
    label: str,
    description: str = "",
    parent_key: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Compatibility wrapper over the new section upsert."""
    section = await (await _graph_db()).upsert_section(
        student_id=student_id,
        key=key,
        description=description or label,
        parent_key=parent_key or "",
    )
    section["label"] = label
    return section


async def upsert_entity_for_student(
    *,
    label: str,
    identity_props: dict[str, Any],
    properties: dict[str, Any],
    student_id: str,
    section_key: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Compatibility wrapper over the new graph node upsert."""
    return await (await _graph_db()).upsert_graph_node(
        student_id=student_id,
        entity_type=label,
        section_key=section_key or "general",
        identity={str(k): str(v) for k, v in (identity_props or {}).items()},
        properties=properties or {},
    )


async def upsert_relationship_for_student(
    *,
    student_id: str,
    source_label: str,
    source_identity: dict[str, Any],
    relationship: str,
    target_label: str,
    target_identity: dict[str, Any],
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper over the new graph relation upsert."""
    return await (await _graph_db()).upsert_graph_relation(
        student_id=student_id,
        source_entity_type=source_label,
        source_identity={str(k): str(v) for k, v in source_identity.items()},
        target_entity_type=target_label,
        target_identity={str(k): str(v) for k, v in target_identity.items()},
        relationship_type=relationship,
        properties=properties or {},
    )


async def create_entity(*, student_id: str, label: str, properties: dict[str, Any], section_key: str | None = None) -> dict[str, Any]:
    """Best-effort compatibility creator for memory ingestion paths."""
    identity = {k: v for k, v in properties.items() if k in {"name", "code", "title", "key", "value"} and v}
    return await upsert_entity_for_student(
        label=label,
        identity_props=identity or {"name": str(label).lower()},
        properties=properties,
        student_id=student_id,
        section_key=section_key or "general",
    )


async def store_evidence(
    *,
    student_id: str,
    source_type: str,
    content: str,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    source_ref: str | None = None,
    embedding: list[float] | None = None,
) -> dict[str, Any]:
    """Temporary evidence shim. Returns a persisted-looking record without full legacy behavior."""
    return {
        "id": generate_evidence_id(),
        "student_id": student_id,
        "source_type": source_type,
        "content": content,
        "session_id": session_id or "",
        "metadata": metadata or {},
        "source_ref": source_ref or "",
        "embedding_present": bool(embedding),
    }


async def store_memory_item(
    student_id: str,
    memory_type: str,
    summary: str,
    *,
    source_ref: str | None = None,
    confidence: float = 0.0,
    salience: float = 0.0,
    status: str = "candidate",
    time_scope: str = "long_term",
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Temporary memory-item shim for compatibility callers."""
    return {
        "id": generate_memory_id("memory"),
        "student_id": student_id,
        "memory_type": memory_type,
        "summary": summary,
        "source_ref": source_ref or "",
        "confidence": confidence,
        "salience": salience,
        "status": status,
        "time_scope": time_scope,
        "tags": tags or [],
        "metadata": metadata or {},
    }


async def store_candidate_fact(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Temporary candidate-fact shim."""
    return {"id": generate_memory_id("fact"), "status": "candidate", "args": args, "kwargs": kwargs}


async def link_memory_to_evidence(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {"status": "noop"}


async def mark_candidate_fact_promoted(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {"status": "noop"}


async def get_relevant_memories(student_id: str, query: str, limit: int = 6) -> dict[str, list[dict[str, Any]]]:
    """Return empty memory buckets for compatibility callers."""
    return {"resolved": [], "candidate": [], "short_term": []}


async def list_saved_recommendations(student_id: str, limit: int = 6) -> list[dict[str, Any]]:
    return []


async def update_saved_recommendation_outcome(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {"status": "noop"}


async def update_entity(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {"status": "noop"}


async def delete_entity(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {"status": "noop"}


async def delete_entity_for_student(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {"status": "noop"}


async def delete_document_cascade(document_id: str) -> dict[str, Any]:
    rows = await run_cypher(
        """
        MATCH (d:Document {id: $document_id})
        OPTIONAL MATCH (c:Chunk)-[:FROM_DOCUMENT]->(d)
        DETACH DELETE c, d
        RETURN $document_id AS document_id
        """,
        {"document_id": document_id},
    )
    return {"status": "success", "document_id": document_id, "rows": rows}


async def reset_student_data(student_id: str) -> dict[str, Any]:
    await run_cypher(
        """
        MATCH (s:Student {id: $student_id})
        OPTIONAL MATCH (s)-[*0..3]-(n)
        DETACH DELETE s, n
        """,
        {"student_id": student_id},
    )
    return {"status": "success", "student_id": student_id}


async def reset_all_data() -> dict[str, Any]:
    await run_cypher("MATCH (n) DETACH DELETE n")
    return {"status": "success"}
