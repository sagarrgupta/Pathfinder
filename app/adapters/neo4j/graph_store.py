"""Neo4j graph store adapter.

Provides CRUD operations on the knowledge graph: students, courses,
skills, documents, and their relationships.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, date, time, timedelta
from typing import Any, Optional

from neo4j import AsyncGraphDatabase, AsyncDriver
import neo4j.time as neo4j_time

from app.config.settings import settings
from app.services.conflict_semantics import normalize_fact_value, split_conflict_groups
from app.utils.ids import generate_evidence_id, generate_memory_id, generate_student_id

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


def _metadata_json(metadata: dict[str, Any] | None) -> str:
    try:
        return json.dumps(metadata or {})
    except Exception:
        return "{}"


def _utc_now() -> datetime:
    return datetime.utcnow()


def _iso_utc(value: datetime) -> str:
    return value.isoformat() + "Z"


def _normalize_name(value: str | None) -> str:
    text = re.sub(r"[^\w\s/+&,-]", "", (value or "").strip())
    text = re.sub(r"\s+", " ", text)
    return text.casefold()


def _semantic_entity_key(label: str | None, value: str | None) -> str:
    text = _normalize_name(value)
    if not text:
        return ""
    if label == "Goal":
        replacements = {
            "obtain": "get",
            "seeking": "get",
            "looking": "get",
            "want": "get",
            "wanting": "get",
            "enter": "industry",
            "entering": "industry",
            "internships": "internship",
            "jobs": "job",
            "roles": "role",
        }
        stopwords = {"to", "a", "an", "the", "and", "go", "into", "first", "for", "my"}
        tokens = []
        for token in re.findall(r"[a-z0-9]+", text):
            mapped = replacements.get(token, token)
            if mapped not in stopwords:
                tokens.append(mapped)
        return " ".join(sorted(dict.fromkeys(tokens)))
    return text


def _canonical_entity_key(item: dict[str, Any], label: str | None, key_field: str = "name") -> str:
    raw = str(item.get("normalized_name") or item.get(key_field) or item.get("value") or item.get("summary") or "")
    text = _semantic_entity_key(label, raw)
    if not text:
        return str(item.get("id", ""))
    if label == "Goal":
        text = re.sub(r"^(seeking|looking for|aiming for|wanting|want)\s+", "", text)
        text = re.sub(r"\binternships\b", "internship", text)
        text = re.sub(r"\bjobs\b", "job", text)
        text = re.sub(r"\broles\b", "role", text)
        text = text.rstrip(".")
    elif label == "Interest":
        text = re.sub(r"^(interested in)\s+", "", text)
        text = text.rstrip(".")
    elif label == "Preference":
        text = re.sub(r"^(prefer|prefers)\s+", "", text)
        text = text.rstrip(".")
    return text


def _expand_compound_entity_values(name: str) -> list[str]:
    if not name:
        return []
    stripped = name.strip()
    if len(stripped) > 80:
        return []
    normalized = re.sub(r"\s+(and|&)\s+", ",", stripped, flags=re.IGNORECASE)
    parts = [part.strip(" .") for part in normalized.split(",")]
    return [part for part in parts if part]


def _dedupe_entities(items: list[dict[str, Any]], key_field: str = "name", label: str | None = None) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for item in items:
        key = _canonical_entity_key(item, label, key_field)
        current = deduped.get(key)
        if current is None:
            deduped[key] = item
            continue
        current_score = len(json.dumps(current, sort_keys=True, default=str)) + int(bool(current.get("updated_at")))
        candidate_score = len(json.dumps(item, sort_keys=True, default=str)) + int(bool(item.get("updated_at")))
        if candidate_score >= current_score:
            deduped[key] = item
    values = list(deduped.values())

    if label in {"Skill", "Interest"}:
        atomic_keys = {
            _canonical_entity_key(item, label, key_field)
            for item in values
            if len(_expand_compound_entity_values(str(item.get(key_field) or ""))) <= 1
        }
        filtered: list[dict[str, Any]] = []
        for item in values:
            parts = _expand_compound_entity_values(str(item.get(key_field) or ""))
            if len(parts) > 1:
                part_keys = {_normalize_name(part) for part in parts if part}
                if part_keys and part_keys.issubset(atomic_keys):
                    continue
            filtered.append(item)
        values = filtered

    return values

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
            "CREATE CONSTRAINT evidence_id IF NOT EXISTS FOR (e:Evidence) REQUIRE e.id IS UNIQUE",
            "CREATE CONSTRAINT candidate_fact_id IF NOT EXISTS FOR (c:CandidateFact) REQUIRE c.id IS UNIQUE",
            "CREATE CONSTRAINT memory_item_id IF NOT EXISTS FOR (m:MemoryItem) REQUIRE m.id IS UNIQUE",
        ]
        indexes = [
            "CREATE INDEX course_code IF NOT EXISTS FOR (c:Course) ON (c.code)",
            "CREATE INDEX skill_name IF NOT EXISTS FOR (s:Skill) ON (s.name)",
            "CREATE INDEX document_scope IF NOT EXISTS FOR (d:Document) ON (d.scope)",
            "CREATE INDEX chunk_doc IF NOT EXISTS FOR (c:Chunk) ON (c.document_id)",
            "CREATE INDEX evidence_student IF NOT EXISTS FOR (e:Evidence) ON (e.student_id)",
            "CREATE INDEX memory_student IF NOT EXISTS FOR (m:MemoryItem) ON (m.student_id)",
            "CREATE INDEX candidate_fact_student IF NOT EXISTS FOR (c:CandidateFact) ON (c.student_id)",
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


async def get_student(student_id: str) -> dict[str, Any] | None:
    """Return a student node by ID if it exists."""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (s:Student {id: $id})
            RETURN s {.*} AS student
            """,
            id=student_id,
        )
        record = await result.single()
        return _sanitize(dict(record["student"])) if record else None


async def create_student(
    name: str,
    email: str | None = None,
    university: str | None = None,
    program: str | None = None,
) -> dict[str, Any]:
    """Create a new local student profile."""
    student_id = generate_student_id()
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            CREATE (s:Student {
                id: $id,
                name: $name,
                email: $email,
                university: $university,
                program: $program,
                created_at: datetime(),
                updated_at: datetime()
            })
            RETURN s {.*} AS student
            """,
            id=student_id,
            name=name,
            email=email,
            university=university,
            program=program,
        )
        record = await result.single()
        return _sanitize(dict(record["student"])) if record else {"id": student_id, "name": name}


async def list_students() -> list[dict[str, Any]]:
    """Return all known local student profiles."""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (s:Student)
            OPTIONAL MATCH (s)-[]->(n)
            WITH s, count(n) AS relation_count
            RETURN s {.*} AS student, relation_count
            ORDER BY coalesce(s.updated_at, s.created_at) DESC
            """
        )
        students = []
        async for record in result:
            student = _sanitize(dict(record["student"]))
            completeness_fields = [
                student.get("name"),
                student.get("university"),
                student.get("program"),
                student.get("gpa"),
                student.get("semester"),
                student.get("email"),
            ]
            student["completeness"] = round(
                sum(1 for field in completeness_fields if field) / len(completeness_fields), 2
            )
            student["relation_count"] = record["relation_count"]
            students.append(student)
        return students


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


async def update_entity(
    label: str, match_props: dict[str, Any], new_props: dict[str, Any], student_id: str | None = None
) -> dict[str, Any]:
    """Update properties on an existing entity node."""
    driver = await get_driver()
    where_parts = [f"n.{k} = ${k}" for k in match_props]
    params = {**match_props, **{f"new_{k}": v for k, v in new_props.items()}}
    if student_id:
        where_parts.append(
            "EXISTS { MATCH (:Student {id: $student_id})-[]->(n) }"
        )
        params["student_id"] = student_id
    where = " AND ".join(where_parts)
    set_clauses = ", ".join(f"n.{k} = $new_{k}" for k in new_props)
    async with driver.session() as session:
        result = await session.run(
            f"""
            MATCH (n:{label}) WHERE {where}
            SET {set_clauses}, n.updated_at = datetime()
            RETURN n {{.*}} AS entity
            """,
            **params,
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


async def delete_entity_for_student(
    label: str,
    match_props: dict[str, Any],
    student_id: str,
) -> bool:
    """Delete a node linked to a specific student profile."""
    driver = await get_driver()
    where = " AND ".join(f"n.{k} = ${k}" for k in match_props)
    async with driver.session() as session:
        result = await session.run(
            f"""
            MATCH (s:Student {{id: $student_id}})-[]->(n:{label})
            WHERE {where}
            DETACH DELETE n
            RETURN count(n) AS cnt
            """,
            student_id=student_id,
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


async def find_document_by_filename(
    filename: str, student_id: str = "default"
) -> dict[str, Any] | None:
    """Return the Document node for *filename* if it exists, else None."""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (s:Student {id: $sid})-[:UPLOADED]->(d:Document {filename: $fname})
            RETURN d {.*} AS doc
            """,
            sid=student_id,
            fname=filename,
        )
        record = await result.single()
        return _sanitize(dict(record["doc"])) if record else None


async def delete_document_cascade(document_id: str, student_id: str = "default") -> bool:
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
            """
            MATCH (s:Student {id: $student_id})-[:UPLOADED]->(d:Document {id: $doc_id})
            DETACH DELETE d
            RETURN count(d) AS cnt
            """,
            doc_id=document_id,
            student_id=student_id,
        )
        record = await result.single()
        return record["cnt"] > 0 if record else False


async def promote_document_to_global(document_id: str, student_id: str = "default") -> bool:
    """Change a session-scoped document to global scope."""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (s:Student {id: $student_id})-[:UPLOADED]->(d:Document {id: $doc_id})
            SET d.scope = 'global', d.session_id = null
            RETURN d.id AS id
            """,
            doc_id=document_id,
            student_id=student_id,
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


async def store_evidence(
    student_id: str,
    source_type: str,
    content: str,
    *,
    source_ref: str | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    embedding: list[float] | None = None,
) -> dict[str, Any]:
    """Store a raw evidence item for later provenance-aware retrieval."""
    evidence_id = generate_evidence_id()
    metadata_json = _metadata_json(metadata)
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (s:Student {id: $student_id})
            CREATE (s)-[:HAS_EVIDENCE]->(e:Evidence {
                id: $id,
                student_id: $student_id,
                source_type: $source_type,
                source_ref: $source_ref,
                session_id: $session_id,
                content: $content,
                metadata: $metadata,
                metadata_json: $metadata_json,
                embedding: $embedding,
                status: 'resolved',
                created_at: datetime(),
                last_used_at: datetime()
            })
            RETURN e {.*} AS evidence
            """,
            id=evidence_id,
            student_id=student_id,
            source_type=source_type,
            source_ref=source_ref,
            session_id=session_id,
            content=content,
            metadata=metadata or {},
            metadata_json=metadata_json,
            embedding=embedding,
        )
        record = await result.single()
        return _sanitize(dict(record["evidence"])) if record else {"id": evidence_id}


async def store_candidate_fact(
    student_id: str,
    fact_type: str,
    value: str,
    *,
    source_ref: str,
    confidence: float,
    salience: float,
    status: str = "candidate",
    time_scope: str = "long_term",
    metadata: dict[str, Any] | None = None,
    embedding: list[float] | None = None,
) -> dict[str, Any]:
    """Store a candidate memory/fact node."""
    fact_id = generate_memory_id("candidate")
    metadata_json = _metadata_json(metadata)
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (s:Student {id: $student_id})
            CREATE (s)-[:HAS_CANDIDATE_FACT]->(c:CandidateFact {
                id: $id,
                student_id: $student_id,
                fact_type: $fact_type,
                value: $value,
                source_ref: $source_ref,
                confidence: $confidence,
                salience: $salience,
                status: $status,
                time_scope: $time_scope,
                metadata: $metadata,
                metadata_json: $metadata_json,
                embedding: $embedding,
                created_at: datetime(),
                last_used_at: datetime(),
                last_reinforced_at: datetime(),
                nudge_count: 0,
                nudge_state: 'pending'
            })
            RETURN c {.*} AS fact
            """,
            id=fact_id,
            student_id=student_id,
            fact_type=fact_type,
            value=value,
            source_ref=source_ref,
            confidence=confidence,
            salience=salience,
            status=status,
            time_scope=time_scope,
            metadata=metadata or {},
            metadata_json=metadata_json,
            embedding=embedding,
        )
        record = await result.single()
        return _sanitize(dict(record["fact"])) if record else {"id": fact_id}


async def store_memory_item(
    student_id: str,
    memory_type: str,
    summary: str,
    *,
    source_ref: str,
    confidence: float,
    salience: float,
    status: str = "candidate",
    time_scope: str = "long_term",
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    embedding: list[float] | None = None,
) -> dict[str, Any]:
    """Store a generic long-term memory item."""
    memory_id = generate_memory_id("memory")
    metadata_json = _metadata_json(metadata)
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (s:Student {id: $student_id})
            CREATE (s)-[:HAS_MEMORY]->(m:MemoryItem {
                id: $id,
                student_id: $student_id,
                memory_type: $memory_type,
                summary: $summary,
                source_ref: $source_ref,
                confidence: $confidence,
                salience: $salience,
                status: $status,
                time_scope: $time_scope,
                tags: $tags,
                metadata: $metadata,
                metadata_json: $metadata_json,
                embedding: $embedding,
                created_at: datetime(),
                last_used_at: datetime(),
                last_reinforced_at: datetime(),
                nudge_count: 0,
                nudge_state: 'pending'
            })
            RETURN m {.*} AS memory
            """,
            id=memory_id,
            student_id=student_id,
            memory_type=memory_type,
            summary=summary,
            source_ref=source_ref,
            confidence=confidence,
            salience=salience,
            status=status,
            time_scope=time_scope,
            tags=tags or [],
            metadata=metadata or {},
            metadata_json=metadata_json,
            embedding=embedding,
        )
        record = await result.single()
        return _sanitize(dict(record["memory"])) if record else {"id": memory_id}


async def link_memory_to_evidence(
    memory_label: str,
    memory_id: str,
    evidence_id: str,
    relationship: str = "DERIVED_FROM",
) -> None:
    """Link a layered-memory node to its source evidence."""
    driver = await get_driver()
    async with driver.session() as session:
        await session.run(
            f"""
            MATCH (m:{memory_label} {{id: $memory_id}})
            MATCH (e:Evidence {{id: $evidence_id}})
            MERGE (m)-[:{relationship}]->(e)
            """,
            memory_id=memory_id,
            evidence_id=evidence_id,
        )


async def get_due_saved_recommendations(student_id: str, limit: int = 5) -> list[dict[str, Any]]:
    """Return active saved plans/recommendations when available."""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (s:Student {id: $student_id})-[:HAS_MEMORY]->(m:MemoryItem)
            WHERE m.memory_type IN ['saved_plan', 'saved_recommendation']
            RETURN m {.*} AS memory
            ORDER BY m.created_at DESC
            LIMIT $limit
            """,
            student_id=student_id,
            limit=limit,
        )
        return [_sanitize(dict(record["memory"])) async for record in result]


async def list_saved_recommendations(student_id: str, limit: int = 25) -> list[dict[str, Any]]:
    """Return saved plans/recommendations for explicit profile recall."""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (s:Student {id: $student_id})-[:HAS_MEMORY]->(m:MemoryItem)
            WHERE m.memory_type IN ['saved_plan', 'saved_recommendation']
            RETURN m {.*} AS memory
            ORDER BY coalesce(m.updated_at, m.created_at) DESC
            LIMIT $limit
            """,
            student_id=student_id,
            limit=limit,
        )
        return [_sanitize(dict(record["memory"])) async for record in result]


async def get_relevant_memories(student_id: str, query: str, limit: int = 8) -> dict[str, list[dict[str, Any]]]:
    """Return lightweight semantic candidates from layered memory."""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (s:Student {id: $student_id})
            OPTIONAL MATCH (s)-[:HAS_MEMORY]->(m:MemoryItem)
            WITH s, collect(m) AS memories
            OPTIONAL MATCH (s)-[:HAS_CANDIDATE_FACT]->(c:CandidateFact)
            WITH memories, collect(c) AS candidate_facts
            OPTIONAL MATCH (s)-[:HAS_EVIDENCE]->(e:Evidence)
            RETURN memories, candidate_facts, collect(e) AS evidence
            """,
            student_id=student_id,
        )
        record = await result.single()
        if not record:
            return {"memory_items": [], "candidate_facts": [], "evidence": []}

        query_lower = query.lower()

        def score(item: Any, text_keys: tuple[str, ...]) -> float:
            if not item:
                return 0.0
            text = " ".join(str(item.get(key, "")) for key in text_keys).lower()
            overlap = sum(1 for token in query_lower.split() if token and token in text)
            return overlap + float(item.get("salience", 0.0) or 0.0) + float(item.get("confidence", 0.0) or 0.0)

        def prepare(items: list[Any], text_keys: tuple[str, ...]) -> list[dict[str, Any]]:
            prepared = []
            for item in items:
                if not item:
                    continue
                data = _sanitize(dict(item))
                data["match_score"] = score(data, text_keys)
                prepared.append(data)
            prepared.sort(key=lambda item: item.get("match_score", 0.0), reverse=True)
            return prepared[:limit]

        return {
            "memory_items": prepare(record["memories"], ("summary", "memory_type")),
            "candidate_facts": prepare(record["candidate_facts"], ("value", "fact_type")),
            "evidence": prepare(record["evidence"], ("content", "source_type"))[: max(3, limit // 2)],
        }


async def mark_memory_nudged(label: str, memory_id: str) -> None:
    """Increment nudge counters/timestamps for a memory-like node."""
    driver = await get_driver()
    async with driver.session() as session:
        await session.run(
            f"""
            MATCH (n:{label} {{id: $memory_id}})
            SET n.nudge_count = coalesce(n.nudge_count, 0) + 1,
                n.nudge_state = 'acknowledged',
                n.last_nudged_at = datetime(),
                n.updated_at = datetime()
            """,
            memory_id=memory_id,
        )


async def apply_conflict_choice(
    *,
    student_id: str,
    conflict_id: str,
    fact_type: str,
    action: str,
    selected_value: str | None = None,
) -> dict[str, Any]:
    """Apply a user-selected action for a conflicting candidate-fact cluster."""
    if action not in {"choose_value", "unresolved"}:
        return {"updated": 0, "action": action}

    normalized_selected = normalize_fact_value(fact_type, selected_value)
    now = _iso_utc(_utc_now())
    snooze_until = _iso_utc(_utc_now() + timedelta(days=14))

    facts_rows = await run_cypher(
        """
        MATCH (s:Student {id: $sid})-[:HAS_CANDIDATE_FACT]->(c:CandidateFact)
        WHERE toLower(coalesce(c.fact_type, '')) = toLower($fact_type)
          AND coalesce(c.status, 'candidate') <> 'archived'
        RETURN c {.*} AS fact
        """,
        {"sid": student_id, "fact_type": fact_type},
    )
    facts = [row.get("fact", {}) for row in facts_rows if row.get("fact")]
    conflict_groups, _ = split_conflict_groups(fact_type, facts)
    target_group = next(
        (
            group for group in conflict_groups
            if any(str(item.get("id") or "") == conflict_id for item in group)
            or any(normalize_fact_value(fact_type, str(item.get("value", ""))) == normalized_selected for item in group)
        ),
        [],
    )
    target_ids = [str(item.get("id")) for item in target_group if item.get("id")]

    if action == "unresolved":
        if not target_ids:
            target_ids = [conflict_id] if conflict_id else []
        rows = await run_cypher(
            """
            MATCH (c:CandidateFact)
            WHERE c.id IN $target_ids
            SET c.nudge_count = coalesce(c.nudge_count, 0) + 1,
                c.nudge_state = 'snoozed',
                c.nudge_until = datetime($snooze_until),
                c.last_nudged_at = datetime($now),
                c.updated_at = datetime($now)
            RETURN count(c) AS updated
            """,
            {"target_ids": target_ids, "snooze_until": snooze_until, "now": now},
        )
        return {"updated": int(rows[0].get("updated", 0) if rows else 0), "action": action}

    if not normalized_selected:
        return {"updated": 0, "action": action}

    selected_fact = next(
        (
            item for item in target_group
            if normalize_fact_value(fact_type, str(item.get("value", ""))) == normalized_selected
        ),
        None,
    )
    if not target_ids or not selected_fact:
        return {
            "updated": 0,
            "action": action,
            "selected_value": selected_value,
            "message": f"I couldn't find an active {fact_type} conflict for '{selected_value}'.",
        }

    rows = await run_cypher(
        """
        MATCH (c:CandidateFact)
        WHERE c.id IN $target_ids
        SET c.status = CASE
            WHEN c.id = $selected_id THEN 'resolved'
            WHEN c.status IN ['candidate', 'resolved', 'conflicted'] THEN 'superseded'
            ELSE c.status
        END,
            c.nudge_state = CASE WHEN c.id = $selected_id THEN 'resolved' ELSE 'acknowledged' END,
            c.last_nudged_at = datetime($now),
            c.nudge_count = coalesce(c.nudge_count, 0) + 1,
            c.updated_at = datetime($now),
            c.last_reinforced_at = CASE WHEN c.id = $selected_id THEN datetime($now) ELSE c.last_reinforced_at END
        RETURN count(c) AS updated
        """,
        {
            "target_ids": target_ids,
            "selected_id": str(selected_fact.get("id")),
            "now": now,
        },
    )

    await _promote_conflict_choice(student_id, fact_type, selected_fact)
    return {
        "updated": int(rows[0].get("updated", 0) if rows else 0),
        "superseded": max(0, len(target_ids) - 1),
        "action": action,
        "selected_value": str(selected_fact.get("value", "")),
    }


async def _promote_conflict_choice(student_id: str, fact_type: str, selected_fact: dict[str, Any]) -> None:
    """Reflect a user-confirmed conflict choice in controlled profile fields."""
    value = str(selected_fact.get("value", "")).strip()
    if not value:
        return
    lowered_type = (fact_type or "").strip().lower()
    if lowered_type == "name":
        await update_student(student_id, name=value)
    elif lowered_type == "university":
        await update_student(student_id, university=value)
    elif lowered_type == "program":
        await update_student(student_id, program=value)
    elif lowered_type == "semester":
        await update_student(student_id, semester=value)
    elif lowered_type == "gpa":
        await update_student(student_id, gpa=value)
    elif lowered_type == "email":
        await update_student(student_id, email=value)


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

    for label, items in list(entities_by_label.items()):
        entities_by_label[label] = _dedupe_entities(items, label=label)

    # Backward-compatible keys mapped from Neo4j labels
    completeness_fields = [
        student.get("name"),
        student.get("university"),
        student.get("program"),
        student.get("gpa"),
        student.get("semester"),
        student.get("email"),
    ]
    return {
        "personal": student,
        "courses": entities_by_label.get("Course", []),
        "skills": entities_by_label.get("Skill", []),
        "goals": entities_by_label.get("Goal", []),
        "interests": entities_by_label.get("Interest", []),
        "experience": entities_by_label.get("Company", []),
        "documents": entities_by_label.get("Document", []),
        "projects": entities_by_label.get("Project", []),
        "constraints": entities_by_label.get("Constraint", []),
        "preferences": entities_by_label.get("Preference", []),
        "candidate_facts": entities_by_label.get("CandidateFact", []),
        "memory_items": entities_by_label.get("MemoryItem", []),
        "evidence": entities_by_label.get("Evidence", []),
        "all_entities": entities_by_label,
        "completeness": round(sum(1 for field in completeness_fields if field) / len(completeness_fields), 2),
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
