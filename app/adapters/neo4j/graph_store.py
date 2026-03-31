"""Neo4j graph store adapter.

Provides CRUD operations on Pathfinder's student profiles, profile graph,
and layered long-term memory (Evidence, CandidateFact, MemoryItem).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import neo4j.time as neo4j_time
from neo4j import AsyncDriver, AsyncGraphDatabase

from app.config.settings import settings
from app.services.conflict_semantics import normalize_fact_value, split_conflict_groups
from app.utils.ids import generate_evidence_id, generate_memory_id, generate_student_id

log = logging.getLogger("pathfinder.neo4j.graph")

_driver: Optional[AsyncDriver] = None


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
        sanitized = {k: _sanitize(v) for k, v in value.items()}
        metadata_json = sanitized.get("metadata_json")
        if metadata_json and "metadata" not in sanitized:
            try:
                sanitized["metadata"] = json.loads(metadata_json)
            except Exception:
                sanitized["metadata"] = {}
        return sanitized
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    return value


def _metadata_json(metadata: dict[str, Any] | None) -> str:
    try:
        return json.dumps(metadata or {})
    except Exception:
        return "{}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


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
    elif label == "BehavioralPattern":
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
        current_score = (
            len(json.dumps(current, sort_keys=True, default=str))
            + int(bool(current.get("_source_document")))
            + int(bool(current.get("updated_at")))
        )
        candidate_score = (
            len(json.dumps(item, sort_keys=True, default=str))
            + int(bool(item.get("_source_document")))
            + int(bool(item.get("updated_at")))
        )
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
            name = str(item.get(key_field) or "")
            parts = _expand_compound_entity_values(name)
            if len(parts) > 1:
                part_keys = {_normalize_name(part) for part in parts if part}
                if part_keys and part_keys.issubset(atomic_keys):
                    continue
            filtered.append(item)
        values = filtered

    if label == "Goal":
        ranked = sorted(
            values,
            key=lambda item: (
                len(str(item.get(key_field) or "")),
                int(bool(item.get("updated_at"))),
                int(bool(item.get("_source_document"))),
            ),
            reverse=True,
        )
        filtered: list[dict[str, Any]] = []
        kept_keys: list[str] = []
        for item in ranked:
            key = _canonical_entity_key(item, label, key_field)
            if not key:
                filtered.append(item)
                continue
            if any(key != kept and key in kept for kept in kept_keys):
                continue
            filtered.append(item)
            kept_keys.append(key)
        values = filtered

    return values


async def get_driver() -> AsyncDriver:
    """Return or create the singleton Neo4j async driver."""
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


async def init_schema() -> None:
    """Create constraints and indexes if they do not exist."""
    driver = await get_driver()
    async with driver.session() as session:
        statements = [
            "CREATE CONSTRAINT student_id IF NOT EXISTS FOR (s:Student) REQUIRE s.id IS UNIQUE",
            "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",
            "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE",
            "CREATE CONSTRAINT evidence_id IF NOT EXISTS FOR (e:Evidence) REQUIRE e.id IS UNIQUE",
            "CREATE CONSTRAINT candidate_fact_id IF NOT EXISTS FOR (c:CandidateFact) REQUIRE c.id IS UNIQUE",
            "CREATE CONSTRAINT memory_item_id IF NOT EXISTS FOR (m:MemoryItem) REQUIRE m.id IS UNIQUE",
            "CREATE INDEX student_name IF NOT EXISTS FOR (s:Student) ON (s.name)",
            "CREATE INDEX course_code IF NOT EXISTS FOR (c:Course) ON (c.code)",
            "CREATE INDEX skill_name IF NOT EXISTS FOR (s:Skill) ON (s.name)",
            "CREATE INDEX document_scope IF NOT EXISTS FOR (d:Document) ON (d.scope)",
            "CREATE INDEX chunk_doc IF NOT EXISTS FOR (c:Chunk) ON (c.document_id)",
            "CREATE INDEX evidence_student IF NOT EXISTS FOR (e:Evidence) ON (e.student_id)",
            "CREATE INDEX memory_student IF NOT EXISTS FOR (m:MemoryItem) ON (m.student_id)",
            "CREATE INDEX candidate_fact_student IF NOT EXISTS FOR (c:CandidateFact) ON (c.student_id)",
        ]
        for stmt in statements:
            try:
                await session.run(stmt)
            except Exception as exc:
                log.debug("Schema statement skipped: %s (%s)", stmt[:80], exc)
        log.info("Neo4j schema initialized")


async def ensure_student(student_id: str) -> dict[str, Any]:
    """Get or create a student node."""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MERGE (s:Student {id: $id})
            ON CREATE SET s.created_at = datetime(), s.name = coalesce($default_name, 'Student')
            SET s.updated_at = datetime()
            RETURN s {.*} AS student
            """,
            id=student_id,
            default_name="Student",
        )
        record = await result.single()
        return _sanitize(dict(record["student"])) if record else {"id": student_id}


async def get_student(student_id: str) -> dict[str, Any] | None:
    """Return an existing student node without creating one."""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (s:Student {id: $id})
            RETURN s {.*} AS student
            LIMIT 1
            """,
            id=student_id,
        )
        record = await result.single()
        return _sanitize(dict(record["student"])) if record and record.get("student") else None


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
    """Update student properties."""
    if not props:
        return await ensure_student(student_id)

    driver = await get_driver()
    set_clauses = ", ".join(f"s.{key} = ${key}" for key in props)
    async with driver.session() as session:
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


async def create_entity(
    label: str,
    properties: dict[str, Any],
    student_id: str,
    relationship: str = "HAS",
) -> dict[str, Any]:
    """Create an entity node and attach it to a student."""
    props = dict(properties)
    normalized_name = _semantic_entity_key(label, str(props.get("name", "")))
    props["student_id"] = student_id
    if normalized_name:
        props["normalized_name"] = normalized_name
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            f"""
            MATCH (s:Student {{id: $student_id}})
            MERGE (n:{label} {{student_id: $student_id, normalized_name: $normalized_name}})
            ON CREATE SET n += $props, n.created_at = datetime()
            ON MATCH SET n += $props, n.updated_at = datetime()
            MERGE (s)-[:{relationship}]->(n)
            RETURN n {{.*}} AS entity
            """,
            student_id=student_id,
            normalized_name=normalized_name,
            props=props,
        )
        record = await result.single()
        return _sanitize(dict(record["entity"])) if record else {}


async def update_entity(
    label: str,
    match_props: dict[str, Any],
    new_props: dict[str, Any],
    student_id: str | None = None,
) -> dict[str, Any]:
    """Update properties on an existing entity."""
    where_parts = [f"n.{key} = ${key}" for key in match_props]
    params = dict(match_props)
    if student_id:
        where_parts.append("n.student_id = $student_id")
        params["student_id"] = student_id
    set_clauses = ", ".join(f"n.{key} = $new_{key}" for key in new_props)
    params.update({f"new_{key}": value for key, value in new_props.items()})
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            f"""
            MATCH (n:{label})
            WHERE {' AND '.join(where_parts)}
            SET {set_clauses}, n.updated_at = datetime()
            RETURN n {{.*}} AS entity
            """,
            **params,
        )
        record = await result.single()
        return _sanitize(dict(record["entity"])) if record else {}


async def delete_entity(label: str, match_props: dict[str, Any], student_id: str | None = None) -> bool:
    """Delete a node and its relationships."""
    where_parts = [f"n.{key} = ${key}" for key in match_props]
    params = dict(match_props)
    if student_id:
        where_parts.append("n.student_id = $student_id")
        params["student_id"] = student_id
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            f"""
            MATCH (n:{label})
            WHERE {' AND '.join(where_parts)}
            DETACH DELETE n
            RETURN count(n) AS cnt
            """,
            **params,
        )
        record = await result.single()
        return bool(record and record["cnt"] > 0)


async def get_entities(label: str, student_id: str, relationship: str | None = None) -> list[dict[str, Any]]:
    """Return student-linked entities of a given label."""
    rel = f"-[:{relationship}]->" if relationship else "-[]->"
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            f"""
            MATCH (s:Student {{id: $student_id}}){rel}(n:{label})
            RETURN n {{.*}} AS entity
            """,
            student_id=student_id,
        )
        return [_sanitize(dict(record["entity"])) async for record in result]


async def store_document_node(
    document_id: str,
    filename: str,
    scope: str,
    student_id: str,
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
                student_id: $student_id,
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


async def find_document_by_filename(filename: str, student_id: str) -> dict[str, Any] | None:
    """Return the student's document node for filename if it exists."""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (s:Student {id: $sid})-[:UPLOADED]->(d:Document {filename: $fname})
            RETURN d {.*} AS doc
            ORDER BY d.uploaded_at DESC
            LIMIT 1
            """,
            sid=student_id,
            fname=filename,
        )
        record = await result.single()
        return _sanitize(dict(record["doc"])) if record else None


async def delete_document_cascade(document_id: str, student_id: str | None = None) -> bool:
    """Delete a document and its related chunk/evidence records."""
    driver = await get_driver()
    async with driver.session() as session:
        if student_id:
            await session.run(
                """
                MATCH (s:Student {id: $sid})-[:UPLOADED]->(d:Document {id: $doc_id})
                OPTIONAL MATCH (c:Chunk)-[:FROM_DOCUMENT]->(d)
                DETACH DELETE c, d
                """,
                sid=student_id,
                doc_id=document_id,
            )
        else:
            await session.run(
                """
                MATCH (c:Chunk)-[:FROM_DOCUMENT]->(d:Document {id: $doc_id})
                DETACH DELETE c
                """,
                doc_id=document_id,
            )
        result = await session.run(
            "MATCH (d:Document {id: $doc_id}) DETACH DELETE d RETURN count(d) AS cnt",
            doc_id=document_id,
        )
        record = await result.single()
        return bool(record and record["cnt"] > 0)


async def promote_document_to_global(document_id: str, student_id: str | None = None) -> bool:
    """Change a session-scoped document to global scope."""
    driver = await get_driver()
    async with driver.session() as session:
        where_clause = "WHERE d.student_id = $student_id" if student_id else ""
        result = await session.run(
            f"""
            MATCH (d:Document {{id: $doc_id}})
            {where_clause}
            SET d.scope = 'global', d.session_id = null
            RETURN d.id AS id
            """,
            doc_id=document_id,
            student_id=student_id,
        )
        return await result.single() is not None


async def store_extracted_entities(
    entities: list[dict[str, Any]],
    document_id: str,
    student_id: str,
) -> int:
    """Store extracted entities into the student's graph."""
    driver = await get_driver()
    count = 0
    async with driver.session() as session:
        for ent in entities:
            label = ent.get("label", "Entity")
            props = dict(ent.get("properties", {}))
            rel = ent.get("relationship", "HAS")
            props["_source_document"] = document_id
            props["student_id"] = student_id
            normalized_name = _semantic_entity_key(label, str(props.get("name", "")))
            if normalized_name:
                props["normalized_name"] = normalized_name
            try:
                await session.run(
                    f"""
                    MATCH (s:Student {{id: $sid}})
                    MERGE (n:{label} {{student_id: $sid, normalized_name: $normalized_name}})
                    ON CREATE SET n += $props, n.created_at = datetime()
                    ON MATCH SET n += $props, n.updated_at = datetime()
                    MERGE (s)-[:{rel}]->(n)
                    """,
                    sid=student_id,
                    normalized_name=normalized_name,
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
    driver = await get_driver()
    metadata_json = _metadata_json(metadata)
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
    driver = await get_driver()
    metadata_json = _metadata_json(metadata)
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
                metadata_json: $metadata_json,
                embedding: $embedding,
                created_at: datetime(),
                last_used_at: datetime(),
                last_reinforced_at: datetime(),
                nudge_count: 0
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
    driver = await get_driver()
    meta = metadata or {}
    metadata_json = _metadata_json(meta)
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
                metadata_json: $metadata_json,
                title: $title,
                actions: $actions,
                source_session_id: $source_session_id,
                source_query: $source_query,
                follow_up_prompt: $follow_up_prompt,
                next_review_at: $next_review_at,
                priority: $priority,
                recommendation_status: $recommendation_status,
                embedding: $embedding,
                created_at: datetime(),
                last_used_at: datetime(),
                last_reinforced_at: datetime(),
                nudge_count: 0
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
            metadata_json=metadata_json,
            title=meta.get("title"),
            actions=meta.get("actions", []),
            source_session_id=meta.get("source_session_id"),
            source_query=meta.get("source_query"),
            follow_up_prompt=meta.get("follow_up_prompt"),
            next_review_at=meta.get("next_review_at"),
            priority=meta.get("priority", 0),
            recommendation_status=meta.get("status") or "active",
            embedding=embedding,
        )
        record = await result.single()
        return _sanitize(dict(record["memory"])) if record else {"id": memory_id}


async def list_saved_recommendations(student_id: str, limit: int = 25) -> list[dict[str, Any]]:
    """Return saved recommendation/plan memories for a student."""
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


async def get_due_saved_recommendations(student_id: str, limit: int = 5) -> list[dict[str, Any]]:
    """Return active saved plans/recommendations that should be revisited."""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (s:Student {id: $student_id})-[:HAS_MEMORY]->(m:MemoryItem)
            WHERE m.memory_type IN ['saved_plan', 'saved_recommendation']
            RETURN m {.*} AS memory
            """,
            student_id=student_id,
        )
        memories = [_sanitize(dict(record["memory"])) async for record in result]
        active = [
            memory for memory in memories
            if (memory.get("recommendation_status") or "active") == "active"
        ]
        active.sort(
            key=lambda memory: (
                int(memory.get("priority") or 0),
                str(memory.get("created_at") or ""),
            ),
            reverse=True,
        )
        return active[:limit]


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


async def get_relevant_memories(student_id: str, query: str, limit: int = 8) -> dict[str, list[dict[str, Any]]]:
    """Return lightweight semantic candidates from layered memory.

    Uses substring/text scoring in Neo4j as a fallback-friendly semantic approximation.
    Vector reranking is performed in the retrieval service.
    """
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
            return overlap + float(item.get("salience", 0.0)) + float(item.get("confidence", 0.0))

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
    """Increment one-time nudge tracking for a memory node."""
    driver = await get_driver()
    async with driver.session() as session:
        await session.run(
            f"""
            MATCH (n:{label} {{id: $memory_id}})
            SET n.nudge_count = coalesce(n.nudge_count, 0) + 1,
                n.last_nudged_at = datetime()
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
    """Apply a user-selected action for a conflicting candidate fact cluster."""
    driver = await get_driver()
    normalized_selected = normalize_fact_value(fact_type, selected_value)
    now = _iso_utc(_utc_now())
    snooze_until = _iso_utc(_utc_now() + timedelta(days=14))
    async with driver.session() as session:
        facts_result = await session.run(
            """
            MATCH (s:Student {id: $student_id})-[:HAS_CANDIDATE_FACT]->(c:CandidateFact)
            WHERE c.fact_type = $fact_type
              AND coalesce(c.status, 'candidate') <> 'archived'
            RETURN collect(c {.*}) AS facts
            """,
            student_id=student_id,
            fact_type=fact_type,
        )
        record = await facts_result.single()
        facts = [_sanitize(dict(item)) for item in (record["facts"] if record else [])]
        conflict_groups, _ = split_conflict_groups(fact_type, facts)
        target_group = next(
            (
                group
                for group in conflict_groups
                if any(str(item.get("id") or "") == conflict_id for item in group)
                or any(normalize_fact_value(fact_type, item.get("value")) == normalized_selected for item in group)
            ),
            [],
        )
        target_ids = [str(item.get("id")) for item in target_group if item.get("id")]

        if action == "choose_value":
            selected_fact = next(
                (
                    item
                    for item in target_group
                    if normalize_fact_value(fact_type, item.get("value")) == normalized_selected
                ),
                None,
            )
            if not target_ids or not selected_fact:
                return {
                    "action": action,
                    "fact_type": fact_type,
                    "selected_value": selected_value,
                    "message": f"I couldn't find an active {fact_type} conflict for '{selected_value}'.",
                }
            result = await session.run(
                """
                MATCH (c:CandidateFact)
                WHERE c.id IN $target_ids
                SET c.status = CASE
                    WHEN c.id = $selected_id THEN 'resolved'
                    WHEN c.status IN ['candidate', 'resolved', 'conflicted'] THEN 'superseded'
                    ELSE c.status
                END,
                    c.nudge_state = CASE
                    WHEN c.id = $selected_id THEN 'resolved'
                    ELSE 'acknowledged'
                END,
                    c.last_nudged_at = datetime($now),
                    c.nudge_count = coalesce(c.nudge_count, 0) + 1,
                    c.updated_at = datetime($now)
                RETURN collect(c {.*}) AS facts
                """,
                target_ids=target_ids,
                selected_id=str((selected_fact or {}).get("id") or ""),
                now=now,
            )
            record = await result.single()
            facts = [_sanitize(dict(item)) for item in (record["facts"] if record else [])]
            selected_fact = next((fact for fact in facts if str(fact.get("id") or "") == str((selected_fact or {}).get("id") or "")), None)
            if selected_fact:
                await _promote_conflict_choice(student_id, fact_type, selected_fact)
            return {
                "action": action,
                "fact_type": fact_type,
                "selected_value": selected_value,
                "message": f"I'll use '{selected_value}' as your current {fact_type}.",
            }

        nudge_state = "acknowledged" if action == "keep_both" else "snoozed"
        params: dict[str, Any] = {
            "student_id": student_id,
            "fact_type": fact_type,
            "now": now,
            "nudge_state": nudge_state,
        }
        nudge_until_clause = ""
        if action == "ask_later":
            params["nudge_until"] = snooze_until
            nudge_until_clause = ", c.nudge_until = datetime($nudge_until)"

        if not target_ids:
            return {
                "action": action,
                "fact_type": fact_type,
                "message": f"I couldn't find an active {fact_type} conflict to update right now.",
            }

        await session.run(
            f"""
            MATCH (c:CandidateFact)
            WHERE c.id IN $target_ids
            SET c.nudge_state = $nudge_state,
                c.last_nudged_at = datetime($now),
                c.nudge_count = coalesce(c.nudge_count, 0) + 1,
                c.updated_at = datetime($now)
                {nudge_until_clause}
            """,
            target_ids=target_ids,
            **params,
        )
        if action == "keep_both":
            return {
                "action": action,
                "fact_type": fact_type,
                "message": f"Okay, I'll keep both {fact_type} options in mind for now and avoid nudging again soon.",
            }
        return {
            "action": action,
            "fact_type": fact_type,
            "message": f"Okay, I'll ask again later if this {fact_type} conflict becomes important.",
            "next_nudge_after": snooze_until,
        }


async def _promote_conflict_choice(student_id: str, fact_type: str, selected_fact: dict[str, Any]) -> None:
    """Reflect a user-confirmed conflict choice in the controlled profile when possible."""
    value = str(selected_fact.get("value", "")).strip()
    metadata = selected_fact.get("metadata", {}) or {}
    if not value:
        return
    if fact_type == "identity":
        lowered = value.lower()
        if "@" in value:
            await update_student(student_id, email=value)
        elif any(token in lowered for token in ("university", "college", "school")):
            await update_student(student_id, university=value)
        elif any(token in lowered for token in ("computer science", "engineering", "program", "major")):
            await update_student(student_id, program=value)
        else:
            await update_student(student_id, name=value)
        return

    core_map = {
        "goal": ("Goal", "HAS_GOAL"),
        "skill": ("Skill", "HAS_SKILL"),
        "interest": ("Interest", "INTERESTED_IN"),
        "course": ("Course", "TOOK"),
        "experience": ("Company", "WORKED_AT"),
        "project": ("Project", "COMPLETED"),
        "constraint": ("Constraint", "HAS_CONSTRAINT"),
        "preference": ("Preference", "HAS_PREFERENCE"),
        "behavior": ("BehavioralPattern", "HAS_BEHAVIOR"),
    }
    label_rel = core_map.get(fact_type)
    if not label_rel:
        return
    label, relationship = label_rel
    driver = await get_driver()
    async with driver.session() as session:
        await session.run(
            f"""
            MATCH (s:Student {{id: $student_id}})
            MERGE (n:{label} {{student_id: $student_id, normalized_name: $normalized_name}})
            MERGE (s)-[:{relationship}]->(n)
            SET n += $props,
                n.updated_at = datetime()
            ON CREATE SET n.created_at = datetime()
            """,
            student_id=student_id,
            normalized_name=_semantic_entity_key(label, value),
            props={
                "name": value,
                "normalized_name": _semantic_entity_key(label, value),
                "student_id": student_id,
                **metadata,
            },
        )


async def get_full_profile(student_id: str) -> dict[str, Any]:
    """Return the student's complete profile plus layered memory summaries."""
    student = await get_student(student_id) or {}
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
            labels = record["labels"] or []
            if not labels:
                continue
            label = labels[0]
            props = _sanitize(dict(record["props"]))
            props["_relationship"] = record["rel_type"]
            entities_by_label.setdefault(label, []).append(props)

    for label, items in list(entities_by_label.items()):
        if label in {
            "Skill",
            "Course",
            "Goal",
            "Interest",
            "Company",
            "Project",
            "Constraint",
            "Preference",
            "BehavioralPattern",
        }:
            entities_by_label[label] = _dedupe_entities(items, label=label)

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
        "behavioral_patterns": entities_by_label.get("BehavioralPattern", []),
        "candidate_facts": entities_by_label.get("CandidateFact", []),
        "memory_items": entities_by_label.get("MemoryItem", []),
        "evidence": entities_by_label.get("Evidence", []),
        "all_entities": entities_by_label,
    }


async def get_graph_data(student_id: str) -> dict[str, Any]:
    """Return nodes and relationships for frontend graph visualization."""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (s:Student {id: $sid})-[r]->(n)
            RETURN labels(n)[0] AS label, n {.*} AS props, type(r) AS rel_type
            """,
            sid=student_id,
        )
        nodes: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []
        async for record in result:
            props = _sanitize(dict(record["props"]))
            nodes.append({"label": record["label"], **props})
            relationships.append(
                {
                    "from": student_id,
                    "to": props.get("name", props.get("id", props.get("summary", ""))),
                    "type": record["rel_type"],
                }
            )
        return {"nodes": nodes, "relationships": relationships}


async def run_cypher(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Execute an arbitrary Cypher query and return results."""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(query, **(params or {}))
        return [_sanitize(dict(record)) async for record in result]


async def reset_student_data(student_id: str) -> bool:
    """Delete all data for a student profile."""
    driver = await get_driver()
    async with driver.session() as session:
        await session.run(
            """
            MATCH (s:Student {id: $sid})-[]->(d:Document)-[]->(c:Chunk)
            DETACH DELETE c
            """,
            sid=student_id,
        )
        await session.run(
            """
            MATCH (s:Student {id: $sid})-[]->(n)
            DETACH DELETE n
            """,
            sid=student_id,
        )
        result = await session.run(
            "MATCH (s:Student {id: $sid}) DELETE s RETURN count(s) AS cnt",
            sid=student_id,
        )
        record = await result.single()
        return bool(record and record["cnt"] > 0)
