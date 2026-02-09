"""Neo4j graph store adapter.

Provides CRUD operations on the knowledge graph: students, courses,
skills, documents, and their relationships.
"""

from __future__ import annotations

import logging
from datetime import datetime, date, time, timedelta
from typing import Any, Optional

from neo4j import AsyncGraphDatabase, AsyncDriver
import neo4j.time as neo4j_time

from app.config.settings import settings

log = logging.getLogger("pathfinder.neo4j.graph")


def _sanitize(value: Any) -> Any:
    """Convert Neo4j-specific types to Python-native types recursively."""
    if isinstance(value, neo4j_time.DateTime):
        return value.to_native().isoformat()
    if isinstance(value, neo4j_time.Date):
        return value.to_native().isoformat()
    if isinstance(value, neo4j_time.Time):
        return str(value)
    if isinstance(value, neo4j_time.Duration):
        return str(value)
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    return value

# ── Singleton Driver ────────────────────────────────────────────

_driver: Optional[AsyncDriver] = None


async def get_driver() -> AsyncDriver:
    """Return (or create) the singleton Neo4j async driver."""
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )
        log.info("Neo4j driver created: %s", settings.NEO4J_URI)
    return _driver


async def close_driver() -> None:
    """Close the Neo4j driver on shutdown."""
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None
        log.info("Neo4j driver closed")


# ── Schema Initialization ──────────────────────────────────────


async def init_schema() -> None:
    """Create constraints and indexes if they don't exist."""
    driver = await get_driver()
    async with driver.session() as session:
        constraints = [
            "CREATE CONSTRAINT student_id IF NOT EXISTS FOR (s:Student) REQUIRE s.id IS UNIQUE",
            "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",
            "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE",
        ]
        indexes = [
            "CREATE INDEX course_code IF NOT EXISTS FOR (c:Course) ON (c.code)",
            "CREATE INDEX skill_name IF NOT EXISTS FOR (s:Skill) ON (s.name)",
            "CREATE INDEX document_scope IF NOT EXISTS FOR (d:Document) ON (d.scope)",
            "CREATE INDEX chunk_doc IF NOT EXISTS FOR (c:Chunk) ON (c.document_id)",
        ]
        for stmt in constraints + indexes:
            try:
                await session.run(stmt)
            except Exception as exc:
                log.debug("Schema statement skipped: %s (%s)", stmt[:60], exc)
        log.info("Neo4j schema initialized")


# ── Student CRUD ────────────────────────────────────────────────


async def ensure_student(student_id: str = "default") -> dict[str, Any]:
    """Get or create the student node. Returns its properties."""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MERGE (s:Student {id: $id})
            ON CREATE SET s.created_at = datetime()
            SET s.updated_at = datetime()
            RETURN s {.*} AS student
            """,
            id=student_id,
        )
        record = await result.single()
        return _sanitize(dict(record["student"])) if record else {"id": student_id}


async def update_student(student_id: str, **props: Any) -> dict[str, Any]:
    """Update student properties (name, gpa, university, …)."""
    driver = await get_driver()
    async with driver.session() as session:
        set_clauses = ", ".join(f"s.{k} = ${k}" for k in props)
        result = await session.run(
            f"""
            MATCH (s:Student {{id: $id}})
            SET {set_clauses}, s.updated_at = datetime()
            RETURN s {{.*}} AS student
            """,
            id=student_id,
            **props,
        )
        record = await result.single()
        return _sanitize(dict(record["student"])) if record else {}


# ── Entity CRUD (generic) ──────────────────────────────────────


async def create_entity(
    label: str,
    properties: dict[str, Any],
    student_id: str = "default",
    relationship: str = "HAS",
) -> dict[str, Any]:
    """Create a node with *label* and link it to the student via *relationship*."""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            f"""
            MATCH (s:Student {{id: $student_id}})
            CREATE (s)-[:{relationship}]->(n:{label} $props)
            SET n.created_at = datetime()
            RETURN n {{.*}} AS entity
            """,
            student_id=student_id,
            props=properties,
        )
        record = await result.single()
        return _sanitize(dict(record["entity"])) if record else {}


async def delete_entity(label: str, match_props: dict[str, Any]) -> bool:
    """Delete a node (and its relationships) matching *label* and *match_props*."""
    driver = await get_driver()
    where = " AND ".join(f"n.{k} = ${k}" for k in match_props)
    async with driver.session() as session:
        result = await session.run(
            f"MATCH (n:{label}) WHERE {where} DETACH DELETE n RETURN count(n) AS cnt",
            **match_props,
        )
        record = await result.single()
        return record["cnt"] > 0 if record else False


async def get_entities(
    label: str,
    student_id: str = "default",
    relationship: str | None = None,
) -> list[dict[str, Any]]:
    """Return all nodes of *label* linked to the student."""
    driver = await get_driver()
    rel = f"-[:{relationship}]->" if relationship else "-[]->"
    async with driver.session() as session:
        result = await session.run(
            f"""
            MATCH (s:Student {{id: $student_id}}){rel}(n:{label})
            RETURN n {{.*}} AS entity
            """,
            student_id=student_id,
        )
        return [_sanitize(dict(record["entity"])) async for record in result]


# ── Document Entities ───────────────────────────────────────────


async def store_document_node(
    document_id: str,
    filename: str,
    scope: str,
    student_id: str = "default",
    session_id: str | None = None,
    doc_type: str = "other",
) -> dict[str, Any]:
    """Create a Document node linked to the student."""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (s:Student {id: $student_id})
            CREATE (s)-[:UPLOADED]->(d:Document {
                id: $doc_id,
                filename: $filename,
                scope: $scope,
                session_id: $session_id,
                type: $doc_type,
                uploaded_at: datetime()
            })
            RETURN d {.*} AS doc
            """,
            student_id=student_id,
            doc_id=document_id,
            filename=filename,
            scope=scope,
            session_id=session_id,
            doc_type=doc_type,
        )
        record = await result.single()
        return _sanitize(dict(record["doc"])) if record else {}


async def delete_document_cascade(document_id: str) -> bool:
    """Delete a document and ALL entities sourced only from it."""
    driver = await get_driver()
    async with driver.session() as session:
        # Delete chunks belonging to this document
        await session.run(
            """
            MATCH (c:Chunk)-[:FROM_DOCUMENT]->(d:Document {id: $doc_id})
            DETACH DELETE c
            """,
            doc_id=document_id,
        )
        # Delete the document node itself
        result = await session.run(
            "MATCH (d:Document {id: $doc_id}) DETACH DELETE d RETURN count(d) AS cnt",
            doc_id=document_id,
        )
        record = await result.single()
        return record["cnt"] > 0 if record else False


async def promote_document_to_global(document_id: str) -> bool:
    """Change a session-scoped document to global scope."""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (d:Document {id: $doc_id})
            SET d.scope = 'global', d.session_id = null
            RETURN d.id AS id
            """,
            doc_id=document_id,
        )
        record = await result.single()
        return record is not None


# ── Extracted Entities from Documents ───────────────────────────


async def store_extracted_entities(
    entities: list[dict[str, Any]],
    document_id: str,
    student_id: str = "default",
) -> int:
    """Store entities extracted from a document into the KG.

    Each item in *entities* must have at least ``label`` and ``properties``.
    An optional ``relationship`` key (default ``HAS``) links to the student.
    """
    driver = await get_driver()
    count = 0
    async with driver.session() as session:
        for ent in entities:
            label = ent.get("label", "Entity")
            props = ent.get("properties", {})
            rel = ent.get("relationship", "HAS")
            props["_source_document"] = document_id
            try:
                await session.run(
                    f"""
                    MATCH (s:Student {{id: $sid}})
                    MERGE (n:{label} {{name: $name}})
                    ON CREATE SET n += $props, n.created_at = datetime()
                    ON MATCH SET n += $props
                    MERGE (s)-[:{rel}]->(n)
                    """,
                    sid=student_id,
                    name=props.get("name", ""),
                    props=props,
                )
                count += 1
            except Exception as exc:
                log.warning("Failed to store entity %s: %s", props, exc)
    return count


# ── Profile Queries ─────────────────────────────────────────────


async def get_full_profile(student_id: str = "default") -> dict[str, Any]:
    """Return the complete student profile from the KG.

    Uses a single dynamic Cypher query to fetch ALL connected entities,
    grouped by label. Maintains backward-compatible keys (courses, skills, ...)
    while also providing ``all_entities`` for fully dynamic frontend rendering.
    """
    student = await ensure_student(student_id)

    # Single query to get every connected entity, grouped by label
    driver = await get_driver()
    entities_by_label: dict[str, list[dict[str, Any]]] = {}
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (s:Student {id: $sid})-[r]->(n)
            RETURN labels(n) AS labels, n {.*} AS props, type(r) AS rel_type
            """,
            sid=student_id,
        )
        async for record in result:
            label = record["labels"][0] if record["labels"] else "Unknown"
            props = _sanitize(dict(record["props"]))
            props["_relationship"] = record["rel_type"]
            if label not in entities_by_label:
                entities_by_label[label] = []
            entities_by_label[label].append(props)

    # Backward-compatible keys mapped from Neo4j labels
    return {
        "personal": student,
        "courses": entities_by_label.get("Course", []),
        "skills": entities_by_label.get("Skill", []),
        "goals": entities_by_label.get("Goal", []),
        "interests": entities_by_label.get("Interest", []),
        "experience": entities_by_label.get("Company", []),
        "documents": entities_by_label.get("Document", []),
        "projects": entities_by_label.get("Project", []),
        # Dynamic: all entity types for frontend flexibility
        "all_entities": entities_by_label,
    }


async def get_graph_data(student_id: str = "default") -> dict[str, Any]:
    """Return nodes + relationships for frontend graph visualization."""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (s:Student {id: $sid})-[r]->(n)
            RETURN
                labels(n)[0] AS label,
                n {.*} AS props,
                type(r) AS rel_type
            """,
            sid=student_id,
        )
        nodes: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []
        async for record in result:
            props = _sanitize(dict(record["props"]))
            nodes.append({"label": record["label"], **props})
            relationships.append({
                "from": student_id,
                "to": props.get("name", props.get("id", "")),
                "type": record["rel_type"],
            })
        return {"nodes": nodes, "relationships": relationships}


# ── Cypher Query (for Profile Manager / GraphCypherQAChain) ─────


async def run_cypher(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Execute an arbitrary read-only Cypher query and return results."""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(query, **(params or {}))
        return [_sanitize(dict(record)) async for record in result]


async def reset_student_data(student_id: str = "default") -> bool:
    """Delete ALL data for a student (profile, entities, documents, chunks).

    This removes the student node and everything connected to it.
    """
    driver = await get_driver()
    async with driver.session() as session:
        # First delete 2nd-level nodes (chunks connected to documents)
        await session.run(
            """
            MATCH (s:Student {id: $sid})-[]->(d:Document)-[]->(c:Chunk)
            DETACH DELETE c
            """,
            sid=student_id,
        )
        # Delete all directly-connected nodes
        await session.run(
            """
            MATCH (s:Student {id: $sid})-[]->(n)
            DETACH DELETE n
            """,
            sid=student_id,
        )
        # Delete the student node itself
        result = await session.run(
            "MATCH (s:Student {id: $sid}) DELETE s RETURN count(s) AS cnt",
            sid=student_id,
        )
        record = await result.single()
        log.info("Reset all data for student %s", student_id)
        return record["cnt"] > 0 if record else False
