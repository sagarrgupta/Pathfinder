"""Neo4j graph store adapter.

Provides CRUD operations on the knowledge graph: students, courses,
skills, documents, and their relationships.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, date, time, timedelta, timezone
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


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _merge_unique_strings(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            text = str(item or "").strip()
            key = text.casefold()
            if text and key not in seen:
                seen.add(key)
                merged.append(text)
    return merged


def _fact_source_support_kind(source_type: str | None, source_ref: str | None) -> str:
    lowered_type = str(source_type or "").strip().lower()
    lowered_ref = str(source_ref or "").strip().lower()
    if any(token in lowered_type for token in ("document", "resume", "transcript", "upload", "pdf")):
        return "document"
    if lowered_ref.startswith("doc:") or lowered_ref.startswith("document:"):
        return "document"
    if lowered_type in {"profile_text", "chat_query"}:
        return "direct_input"
    return "other"


def _candidate_promotion_score(
    confidence: float,
    salience: float,
    support_count: int,
    direct_statement_count: int,
    document_support_count: int,
) -> float:
    score = (confidence * 0.45) + (salience * 0.2)
    score += min(0.15, max(0, support_count - 1) * 0.06)
    if direct_statement_count > 0:
        score += 0.12
    if document_support_count > 0:
        score += 0.08
    return round(min(1.0, score), 2)


def _candidate_confirmation_state(fact: dict[str, Any]) -> str:
    status = str(fact.get("status") or "candidate").lower()
    support_count = int(fact.get("support_count") or 0)
    direct_statement_count = int(fact.get("direct_statement_count") or 0)
    document_support_count = int(fact.get("document_support_count") or 0)
    promotion_score = _safe_float(fact.get("promotion_score"), 0.0)
    if status == "resolved":
        return "confirmed"
    if promotion_score >= 0.8 or (support_count >= 2 and (direct_statement_count > 0 or document_support_count > 0)):
        return "reinforced"
    return "inferred"


def _profile_completeness_breakdown(
    student: dict[str, Any],
    entities_by_label: dict[str, list[dict[str, Any]]],
    candidate_fact_ledger: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    confirmed_or_reinforced = [
        item
        for item in candidate_fact_ledger
        if item.get("confirmation_state") in {"confirmed", "reinforced"}
    ]
    by_type: dict[str, list[dict[str, Any]]] = {}
    for fact in confirmed_or_reinforced:
        by_type.setdefault(str(fact.get("fact_type") or "generic").lower(), []).append(fact)

    categories = {
        "identity": [
            bool(student.get("name")),
            bool(student.get("email")),
            bool(student.get("university")),
        ],
        "academics": [
            bool(student.get("program")),
            bool(student.get("semester")),
            bool(student.get("gpa")),
            bool(entities_by_label.get("Course")),
        ],
        "goals": [
            bool(entities_by_label.get("Goal")),
            bool(by_type.get("goal")),
        ],
        "skills": [
            bool(entities_by_label.get("Skill")),
            bool(by_type.get("skill")),
        ],
        "experience": [
            bool(entities_by_label.get("Company")),
            bool(entities_by_label.get("Project")),
            bool(entities_by_label.get("Document")),
        ],
        "preferences": [
            bool(entities_by_label.get("Preference")),
            bool(entities_by_label.get("Constraint")),
            bool(by_type.get("preference")),
            bool(by_type.get("constraint")),
        ],
    }
    breakdown: dict[str, dict[str, Any]] = {}
    for category, checks in categories.items():
        total = len(checks)
        score = round(sum(1 for item in checks if item) / total, 2) if total else 0.0
        breakdown[category] = {
            "score": score,
            "covered": sum(1 for item in checks if item),
            "total": total,
        }
    return breakdown


def _profile_fact_summary(
    profile_facts: list[dict[str, Any]],
    candidate_fact_ledger: list[dict[str, Any]],
) -> dict[str, Any]:
    confirmed = sum(1 for item in candidate_fact_ledger if item.get("confirmation_state") == "confirmed")
    reinforced = sum(1 for item in candidate_fact_ledger if item.get("confirmation_state") == "reinforced")
    inferred = sum(1 for item in candidate_fact_ledger if item.get("confirmation_state") == "inferred")
    direct = sum(1 for item in candidate_fact_ledger if int(item.get("direct_statement_count") or 0) > 0)
    document_backed = sum(1 for item in candidate_fact_ledger if int(item.get("document_support_count") or 0) > 0)
    stable_count = sum(1 for item in profile_facts if str(item.get("stability") or "").lower() == "stable")
    evolving_count = sum(1 for item in profile_facts if str(item.get("stability") or "").lower() == "evolving")
    temporary_count = sum(1 for item in profile_facts if str(item.get("stability") or "").lower() == "temporary")
    temporal_profile = _build_temporal_profile(profile_facts, candidate_fact_ledger)
    return {
        "durable_profile_facts": len(profile_facts),
        "confirmed_candidate_facts": confirmed,
        "reinforced_candidate_facts": reinforced,
        "inferred_candidate_facts": inferred,
        "direct_statement_backed": direct,
        "document_backed": document_backed,
        "stable_profile_facts": stable_count,
        "evolving_profile_facts": evolving_count,
        "temporary_profile_facts": temporary_count,
        "stale_candidate_facts": len(temporal_profile.get("stale_candidates", [])),
    }


def _parse_datetimeish(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _build_temporal_profile(
    profile_facts: list[dict[str, Any]],
    candidate_fact_ledger: list[dict[str, Any]],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=120)
    event_cutoff = now - timedelta(days=365)

    stable_facts = [fact for fact in profile_facts if str(fact.get("stability") or "").lower() == "stable"]
    evolving_facts = [fact for fact in profile_facts if str(fact.get("stability") or "").lower() == "evolving"]
    temporary_facts = [fact for fact in profile_facts if str(fact.get("stability") or "").lower() == "temporary"]
    expired_preferences: list[dict[str, Any]] = []
    recent_events: list[dict[str, Any]] = []

    stale_candidates: list[dict[str, Any]] = []
    active_candidates: list[dict[str, Any]] = []
    for item in candidate_fact_ledger:
        status = str(item.get("status") or "candidate").lower()
        fact_type = str(item.get("fact_type") or "").lower()
        stability = str(item.get("stability") or "").lower()
        updated_at = _parse_datetimeish(item.get("updated_at") or item.get("created_at"))
        is_stale = status in {"superseded", "archived"} or (
            stability == "temporary"
            and updated_at is not None
            and updated_at < stale_cutoff
        )
        if stability == "temporary" and fact_type in {"preference", "constraint"} and updated_at is not None and updated_at < stale_cutoff:
            expired_preferences.append(item)
        if is_stale:
            stale_candidates.append(item)
        else:
            active_candidates.append(item)

        event_at = updated_at or _parse_datetimeish(item.get("created_at"))
        if event_at is None or event_at < event_cutoff:
            continue
        event_type = "reinforced" if int(item.get("support_count") or 0) > 1 else "observed"
        if status in {"resolved", "superseded", "archived", "conflicted"}:
            event_type = status
        recent_events.append(
            {
                "fact_type": fact_type or "generic",
                "value": str(item.get("value", "")).strip(),
                "status": status,
                "stability": stability,
                "event_type": event_type,
                "timestamp": event_at.isoformat(),
            }
        )

    recent_events.sort(key=lambda item: str(item.get("timestamp", "")), reverse=True)

    return {
        "stable_facts": stable_facts,
        "evolving_facts": evolving_facts,
        "temporary_facts": temporary_facts,
        "active_candidates": active_candidates,
        "stale_candidates": stale_candidates,
        "expired_preferences": expired_preferences,
        "recent_events": recent_events[:12],
        "summary": {
            "stable_count": len(stable_facts),
            "evolving_count": len(evolving_facts),
            "temporary_count": len(temporary_facts),
            "active_candidate_count": len(active_candidates),
            "stale_candidate_count": len(stale_candidates),
            "expired_preference_count": len(expired_preferences),
            "recent_event_count": min(len(recent_events), 12),
        },
    }


def _profile_fact_from_personal(key: str, value: Any) -> dict[str, Any] | None:
    text = str(value or "").strip()
    if not text:
        return None
    return {
        "fact_type": key,
        "value": text,
        "normalized_value": text.casefold(),
        "source_kind": "student_property",
        "stability": "stable",
        "confidence": 1.0,
        "status": "resolved",
        "metadata": {"field": key},
    }


def _profile_fact_from_entity(label: str, entity: dict[str, Any]) -> dict[str, Any] | None:
    value = str(entity.get("name") or entity.get("value") or "").strip()
    if not value:
        return None
    fact_type_map = {
        "Course": "course",
        "Skill": "skill",
        "Goal": "goal",
        "Interest": "interest",
        "Company": "experience",
        "Project": "project",
        "Constraint": "constraint",
        "Preference": "preference",
    }
    fact_type = fact_type_map.get(label)
    if not fact_type:
        return None
    return {
        "fact_type": fact_type,
        "value": value,
        "normalized_value": value.casefold(),
        "source_kind": "core_entity",
        "stability": "stable" if fact_type in {"skill", "course", "project", "experience"} else "evolving",
        "confidence": float(entity.get("confidence", 1.0) or 1.0),
        "status": "resolved",
        "metadata": {"label": label, "relationship": entity.get("_relationship", "")},
    }


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


async def ensure_student(student_id: str) -> dict[str, Any]:
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
    student_id: str,
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
    student_id: str,
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
    filename: str, student_id: str
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


async def delete_document_cascade(document_id: str, student_id: str) -> bool:
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


async def promote_document_to_global(document_id: str, student_id: str) -> bool:
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
    student_id: str,
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
    normalized_value: str | None = None,
    stability: str = "evolving",
    evidence_kind: str = "inference",
    metadata: dict[str, Any] | None = None,
    embedding: list[float] | None = None,
    source_type: str | None = None,
) -> dict[str, Any]:
    """Store a candidate memory/fact node."""
    driver = await get_driver()
    async with driver.session() as session:
        normalized = (normalized_value or value).strip()
        existing_result = await session.run(
            """
            MATCH (s:Student {id: $student_id})-[:HAS_CANDIDATE_FACT]->(c:CandidateFact)
            WHERE c.fact_type = $fact_type
              AND c.normalized_value = $normalized_value
              AND coalesce(c.status, 'candidate') <> 'archived'
            RETURN c {.*} AS fact
            ORDER BY coalesce(c.updated_at, c.last_reinforced_at, c.created_at) DESC
            LIMIT 1
            """,
            student_id=student_id,
            fact_type=fact_type,
            normalized_value=normalized,
        )
        existing_record = await existing_result.single()
        existing = _sanitize(dict(existing_record["fact"])) if existing_record else None

        support_kind = _fact_source_support_kind(source_type, source_ref)
        now_iso = _iso_utc(_utc_now())
        base_metadata = dict(metadata or {})
        provenance_item = {
            "source_ref": source_ref,
            "source_type": source_type or "",
            "observed_at": now_iso,
            "confidence": confidence,
            "evidence_kind": evidence_kind,
        }

        if existing:
            existing_metadata = dict(existing.get("metadata") or {})
            support_count = int(existing.get("support_count") or existing_metadata.get("support_count") or 1) + 1
            direct_statement_count = int(
                existing.get("direct_statement_count") or existing_metadata.get("direct_statement_count") or 0
            ) + (1 if evidence_kind == "direct_statement" else 0)
            document_support_count = int(
                existing.get("document_support_count") or existing_metadata.get("document_support_count") or 0
            ) + (1 if support_kind == "document" else 0)
            revision_count = int(existing.get("revision_count") or existing_metadata.get("revision_count") or 1) + 1
            promotion_score = _candidate_promotion_score(
                max(_safe_float(existing.get("confidence"), confidence), confidence),
                max(_safe_float(existing.get("salience"), salience), salience),
                support_count,
                direct_statement_count,
                document_support_count,
            )
            merged_metadata = {
                **existing_metadata,
                **base_metadata,
                "support_count": support_count,
                "direct_statement_count": direct_statement_count,
                "document_support_count": document_support_count,
                "revision_count": revision_count,
                "first_observed_at": existing_metadata.get("first_observed_at") or existing.get("created_at") or now_iso,
                "last_observed_at": now_iso,
                "source_refs": _merge_unique_strings(existing_metadata.get("source_refs", []), [source_ref]),
                "provenance": [*list(existing_metadata.get("provenance", []))[-5:], provenance_item],
            }
            metadata_json = _metadata_json(merged_metadata)
            result = await session.run(
                """
                MATCH (c:CandidateFact {id: $id})
                SET c.value = $value,
                    c.source_ref = $source_ref,
                    c.confidence = $confidence,
                    c.salience = $salience,
                    c.status = CASE
                        WHEN c.status = 'conflicted' THEN c.status
                        WHEN $status = 'resolved' THEN 'resolved'
                        ELSE coalesce(c.status, $status)
                    END,
                    c.time_scope = $time_scope,
                    c.stability = CASE
                        WHEN c.stability = 'stable' THEN c.stability
                        ELSE $stability
                    END,
                    c.evidence_kind = CASE
                        WHEN c.evidence_kind = 'direct_statement' THEN c.evidence_kind
                        ELSE $evidence_kind
                    END,
                    c.metadata = $metadata,
                    c.metadata_json = $metadata_json,
                    c.embedding = coalesce($embedding, c.embedding),
                    c.updated_at = datetime(),
                    c.last_used_at = datetime(),
                    c.last_reinforced_at = datetime(),
                    c.support_count = $support_count,
                    c.direct_statement_count = $direct_statement_count,
                    c.document_support_count = $document_support_count,
                    c.revision_count = $revision_count,
                    c.promotion_score = $promotion_score
                RETURN c {.*} AS fact
                """,
                id=existing["id"],
                value=value,
                source_ref=source_ref,
                confidence=max(_safe_float(existing.get("confidence"), confidence), confidence),
                salience=max(_safe_float(existing.get("salience"), salience), salience),
                status=status,
                time_scope=time_scope,
                stability=stability,
                evidence_kind=evidence_kind,
                metadata=merged_metadata,
                metadata_json=metadata_json,
                embedding=embedding,
                support_count=support_count,
                direct_statement_count=direct_statement_count,
                document_support_count=document_support_count,
                revision_count=revision_count,
                promotion_score=promotion_score,
            )
            record = await result.single()
            return _sanitize(dict(record["fact"])) if record else {"id": existing["id"]}

        fact_id = generate_memory_id("candidate")
        support_count = 1
        direct_statement_count = 1 if evidence_kind == "direct_statement" else 0
        document_support_count = 1 if support_kind == "document" else 0
        revision_count = 1
        promotion_score = _candidate_promotion_score(
            confidence,
            salience,
            support_count,
            direct_statement_count,
            document_support_count,
        )
        initial_metadata = {
            **base_metadata,
            "support_count": support_count,
            "direct_statement_count": direct_statement_count,
            "document_support_count": document_support_count,
            "revision_count": revision_count,
            "first_observed_at": now_iso,
            "last_observed_at": now_iso,
            "source_refs": [source_ref] if source_ref else [],
            "provenance": [provenance_item],
        }
        metadata_json = _metadata_json(initial_metadata)
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
                normalized_value: $normalized_value,
                stability: $stability,
                evidence_kind: $evidence_kind,
                metadata: $metadata,
                metadata_json: $metadata_json,
                embedding: $embedding,
                support_count: $support_count,
                direct_statement_count: $direct_statement_count,
                document_support_count: $document_support_count,
                revision_count: $revision_count,
                promotion_score: $promotion_score,
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
            normalized_value=normalized,
            stability=stability,
            evidence_kind=evidence_kind,
            metadata=initial_metadata,
            metadata_json=metadata_json,
            embedding=embedding,
            support_count=support_count,
            direct_statement_count=direct_statement_count,
            document_support_count=document_support_count,
            revision_count=revision_count,
            promotion_score=promotion_score,
        )
        record = await result.single()
        return _sanitize(dict(record["fact"])) if record else {"id": fact_id}


async def mark_candidate_fact_promoted(fact_id: str) -> dict[str, Any]:
    """Mark a candidate fact as promoted into durable profile state."""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (c:CandidateFact {id: $id})
            SET c.status = 'resolved',
                c.promotion_state = 'confirmed',
                c.promoted_at = datetime(),
                c.updated_at = datetime(),
                c.last_reinforced_at = datetime()
            RETURN c {.*} AS fact
            """,
            id=fact_id,
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


async def update_saved_recommendation_outcome(
    student_id: str,
    recommendation_id: str,
    *,
    outcome_status: str,
    outcome_notes: str | None = None,
    next_review_at: str | None = None,
    follow_up_prompt: str | None = None,
    metadata_patch: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Update outcome/feedback metadata for a saved recommendation."""
    driver = await get_driver()
    async with driver.session() as session:
        existing_result = await session.run(
            """
            MATCH (s:Student {id: $student_id})-[:HAS_MEMORY]->(m:MemoryItem {id: $recommendation_id})
            WHERE m.memory_type IN ['saved_plan', 'saved_recommendation']
            RETURN m {.*} AS memory
            """,
            student_id=student_id,
            recommendation_id=recommendation_id,
        )
        existing_record = await existing_result.single()
        if not existing_record:
            return None
        existing_memory = _sanitize(dict(existing_record["memory"]))
        merged_metadata = {
            **(existing_memory.get("metadata", {}) or {}),
            **(metadata_patch or {}),
            "outcome_status": outcome_status,
            "outcome_notes": outcome_notes,
            "outcome_updated_at": _iso_utc(_utc_now()),
        }
        if next_review_at:
            merged_metadata["next_review_at"] = next_review_at
        if follow_up_prompt:
            merged_metadata["follow_up_prompt"] = follow_up_prompt
        result = await session.run(
            """
            MATCH (s:Student {id: $student_id})-[:HAS_MEMORY]->(m:MemoryItem {id: $recommendation_id})
            WHERE m.memory_type IN ['saved_plan', 'saved_recommendation']
            SET m.metadata = $metadata,
                m.metadata_json = $metadata_json,
                m.updated_at = datetime($now),
                m.last_used_at = datetime($now)
            RETURN m {.*} AS memory
            """,
            student_id=student_id,
            recommendation_id=recommendation_id,
            metadata=merged_metadata,
            metadata_json=_metadata_json(merged_metadata),
            now=_iso_utc(_utc_now()),
        )
        record = await result.single()
        return _sanitize(dict(record["memory"])) if record else None


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


async def get_full_profile(student_id: str) -> dict[str, Any]:
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
    profile_facts: list[dict[str, Any]] = []
    for personal_key in ("name", "email", "university", "program", "semester", "gpa"):
        fact = _profile_fact_from_personal(personal_key, student.get(personal_key))
        if fact:
            profile_facts.append(fact)
    for label in ("Course", "Skill", "Goal", "Interest", "Company", "Project", "Constraint", "Preference"):
        for entity in entities_by_label.get(label, []):
            fact = _profile_fact_from_entity(label, entity)
            if fact:
                profile_facts.append(fact)

    candidate_fact_ledger = []
    for fact in entities_by_label.get("CandidateFact", []):
        ledger_item = {
            "id": fact.get("id", ""),
            "fact_type": fact.get("fact_type", "generic"),
            "value": fact.get("value", ""),
            "normalized_value": fact.get("normalized_value") or str(fact.get("value", "")).casefold(),
            "confidence": float(fact.get("confidence", 0.0) or 0.0),
            "salience": float(fact.get("salience", 0.0) or 0.0),
            "status": fact.get("status", "candidate"),
            "time_scope": fact.get("time_scope", "long_term"),
            "stability": fact.get("stability", "evolving"),
            "evidence_kind": fact.get("evidence_kind", "inference"),
            "support_count": int(fact.get("support_count", 0) or 0),
            "direct_statement_count": int(fact.get("direct_statement_count", 0) or 0),
            "document_support_count": int(fact.get("document_support_count", 0) or 0),
            "revision_count": int(fact.get("revision_count", 0) or 0),
            "promotion_score": _safe_float(fact.get("promotion_score"), 0.0),
            "created_at": fact.get("created_at"),
            "updated_at": fact.get("updated_at"),
            "metadata": fact.get("metadata", {}) or {},
        }
        ledger_item["confirmation_state"] = _candidate_confirmation_state(ledger_item)
        candidate_fact_ledger.append(ledger_item)
    completeness_breakdown = _profile_completeness_breakdown(student, entities_by_label, candidate_fact_ledger)
    fact_summary = _profile_fact_summary(profile_facts, candidate_fact_ledger)
    temporal_profile = _build_temporal_profile(profile_facts, candidate_fact_ledger)
    overall_completeness = round(
        sum(item.get("score", 0.0) for item in completeness_breakdown.values()) / max(len(completeness_breakdown), 1),
        2,
    )
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
        "candidate_fact_ledger": candidate_fact_ledger,
        "memory_items": entities_by_label.get("MemoryItem", []),
        "evidence": entities_by_label.get("Evidence", []),
        "profile_facts": profile_facts,
        "temporal_profile": temporal_profile,
        "all_entities": entities_by_label,
        "completeness": overall_completeness,
        "completeness_breakdown": completeness_breakdown,
        "fact_summary": fact_summary,
    }


async def get_graph_data(student_id: str) -> dict[str, Any]:
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


async def reset_student_data(student_id: str) -> bool:
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


async def reset_all_data() -> int:
    """Delete all student-related graph data across all profiles."""
    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (n)
            DETACH DELETE n
            RETURN count(n) AS deleted
            """
        )
        record = await result.single()
        deleted = int(record["deleted"]) if record and record.get("deleted") is not None else 0
        log.warning("Reset ALL graph data across profiles (deleted=%d)", deleted)
        return deleted
