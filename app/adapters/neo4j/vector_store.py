"""Neo4j vector store adapter.

Stores document chunks with embeddings and supports semantic search
via Neo4j's built-in vector index.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.adapters.neo4j.graph_store import get_driver
from app.adapters.embeddings.ollama import EmbeddingServiceError, aembed_query
from app.config.settings import settings

log = logging.getLogger("pathfinder.neo4j.vector")

VECTOR_INDEX_NAME = "chunk_embeddings"
_QUERY_TOKEN_RE = re.compile(r"[a-z0-9]{2,}", re.I)
_COURSE_CODE_RE = re.compile(r"\b[a-z]{2,5}\s*-?\s*\d{2,3}[a-z]?\b", re.I)

_INTENT_KEYWORDS: dict[str, set[str]] = {
    "academic_planning": {
        "academic", "catalog", "class", "classes", "course", "courses",
        "curriculum", "degree", "elective", "electives", "enroll", "enrollment",
        "finals", "graduat", "graduation", "major", "milestone", "milestones",
        "minor", "path", "pathway", "pathways", "plan", "planned", "planner",
        "planning", "prereq", "prereqs", "prerequisite", "prerequisites",
        "register", "registration", "roadmap", "schedule", "semester", "study",
        "syllabus", "term", "timeline", "track",
    },
    "career": {
        "career", "careers", "company", "companies", "employment", "hire",
        "hiring", "industry", "industries", "intern", "internship",
        "internships", "job", "jobs", "offer", "offers", "portfolio",
        "position", "positions", "profession", "professional", "recruiter",
        "recruiting", "resume", "role", "roles", "workplace",
    },
    "interview": {
        "behavioral", "coding", "dsa", "interview", "interviewing",
        "interviews", "leetcode", "mock", "onsite", "phone", "screen",
        "screening", "system", "systemdesign", "technical", "whiteboard",
    },
    "requirements": {
        "allowed", "constraint", "constraints", "credit", "credits",
        "criteria", "eligible", "eligibility", "forbidden", "gpa", "limit",
        "limits", "minimum", "policy", "policies", "qualification",
        "qualifications", "requirement", "requirements", "rule", "rules",
        "threshold", "thresholds",
    },
    "transcript": {
        "completed", "completion", "credit", "credits", "grade", "grades",
        "history", "record", "records", "taken", "term", "terms",
        "transcript", "unit", "units",
    },
}

_TEXT_SIGNAL_KEYWORDS: dict[str, set[str]] = {
    "policy_signal": {
        "appeal", "deadline", "deadlines", "eligibility", "graduation",
        "petition", "policy", "policies", "prereq", "prereqs",
        "prerequisite", "prerequisites", "requirement", "requirements",
        "restriction", "restrictions", "waiver",
    },
    "application_signal": {
        "apply", "applying", "application", "applications", "coverletter",
        "hiring", "linkedin", "portfolio", "resume", "recruiter",
    },
    "advising_signal": {
        "advisor", "advising", "checklist", "counselor", "guidance",
        "plan", "roadmap", "sequence", "step", "steps",
    },
}

_ENTITY_LABEL_TAGS: dict[str, str] = {
    "Course": "course_entity",
    "Skill": "skill_entity",
    "Goal": "goal_entity",
    "Constraint": "constraint_entity",
    "Preference": "preference_entity",
    "Program": "program_entity",
    "Experience": "experience_entity",
    "Project": "project_entity",
}


def _normalize_k(k: int) -> int:
    return max(1, int(k))


def _validated_embedding(vector: Any) -> list[float]:
    if not isinstance(vector, list) or not vector:
        raise ValueError("embedding must be a non-empty list[float]")
    if len(vector) != int(settings.EMBEDDING_DIMENSIONS):
        raise ValueError(
            f"embedding dimension mismatch: expected {settings.EMBEDDING_DIMENSIONS}, got {len(vector)}"
        )
    return [float(value) for value in vector]


def _prepared_chunk_rows(chunks: list[dict[str, Any]], document_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, chunk in enumerate(chunks):
        chunk_id = str(chunk.get("id") or "").strip()
        text = str(chunk.get("text") or "").strip()
        if not chunk_id or not text:
            log.warning("Skipping invalid chunk at position %d for document %s", idx, document_id)
            continue
        try:
            embedding = _validated_embedding(chunk.get("embedding"))
        except Exception as exc:
            log.warning("Skipping chunk %s for document %s: %s", chunk_id, document_id, exc)
            continue
        rows.append({
            "chunk_id": chunk_id,
            "text": text,
            "embedding": embedding,
            "page_number": chunk.get("page_number"),
            "chunk_index": int(chunk.get("chunk_index", idx)),
            "doc_id": document_id,
        })
    return rows


def _query_tokens(text: str) -> set[str]:
    return {match.group(0).lower() for match in _QUERY_TOKEN_RE.finditer(text or "")}


def _matching_tags(tokens: set[str], mapping: dict[str, set[str]]) -> list[str]:
    return [tag for tag, keywords in mapping.items() if tokens & keywords]


def _normalized_entity_names(related_entities: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for entity in related_entities:
        raw_name = str(entity.get("name") or "").strip().lower()
        if not raw_name:
            continue
        names.add(raw_name)
        names.update(_query_tokens(raw_name))
    return names


# ── Index Management ────────────────────────────────────────────


async def ensure_vector_index() -> None:
    """Create the vector index on Chunk.embedding if it doesn't exist."""
    driver = await get_driver()
    async with driver.session() as session:
        try:
            await session.run(
                f"""
                CREATE VECTOR INDEX {VECTOR_INDEX_NAME} IF NOT EXISTS
                FOR (c:Chunk) ON (c.embedding)
                OPTIONS {{indexConfig: {{
                    `vector.dimensions`: {settings.EMBEDDING_DIMENSIONS},
                    `vector.similarity_function`: 'cosine'
                }}}}
                """
            )
            log.info("Vector index '%s' ensured", VECTOR_INDEX_NAME)
        except Exception as exc:
            log.warning("Vector index creation note: %s", exc)


# ── Store Chunks ────────────────────────────────────────────────


async def store_chunks(
    chunks: list[dict[str, Any]],
    document_id: str,
) -> int:
    """Store document chunks with embeddings in Neo4j.

    Each item in *chunks* must have:
        - ``id``: unique chunk ID
        - ``text``: chunk content
        - ``embedding``: list[float] (1024-dim)
        - ``page_number``: (optional) int
        - ``chunk_index``: int
    """
    rows = _prepared_chunk_rows(chunks, document_id)
    if not rows:
        log.info("No valid chunks to store for document %s", document_id)
        return 0

    driver = await get_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (d:Document {id: $doc_id})
            UNWIND $rows AS row
            MERGE (c:Chunk {id: row.chunk_id})
            SET c.text = row.text,
                c.embedding = row.embedding,
                c.page_number = row.page_number,
                c.chunk_index = row.chunk_index,
                c.document_id = row.doc_id
            MERGE (c)-[:FROM_DOCUMENT]->(d)
            RETURN count(c) AS stored
            """,
            doc_id=document_id,
            rows=rows,
        )
        record = await result.single()
    stored = int(record["stored"]) if record and record["stored"] is not None else 0
    log.info("Stored %d/%d valid chunks for document %s", stored, len(rows), document_id)
    return stored


# ── Vector Similarity Search ────────────────────────────────────


async def similarity_search(
    query: str,
    k: int = 5,
    student_id: str | None = None,
) -> list[dict[str, Any]]:
    """Semantic similarity search over Chunk nodes for the student's documents."""
    if not student_id:
        raise ValueError("student_id is required for similarity_search")
    query = (query or "").strip()
    if not query:
        return []
    k = _normalize_k(k)

    try:
        query_embedding = await aembed_query(query)
    except EmbeddingServiceError as exc:
        message = f"{exc} while searching your documents."
        log.error(message)
        raise EmbeddingServiceError(message) from exc

    driver = await get_driver()
    async with driver.session() as session:
        try:
            result = await session.run(
                """
                CALL db.index.vector.queryNodes($index_name, $k, $embedding)
                YIELD node AS chunk, score
                MATCH (chunk)-[:FROM_DOCUMENT]->(d:Document)<-[:UPLOADED]-(s:Profile {id: $student_id})
                WHERE chunk.embedding IS NOT NULL
                RETURN chunk.id AS id,
                       chunk.text AS text,
                       chunk.page_number AS page_number,
                       d.filename AS filename,
                       d.id AS document_id,
                       d.scope AS scope,
                       score
                ORDER BY score DESC
                LIMIT $k
                """,
                index_name=VECTOR_INDEX_NAME,
                k=k,
                embedding=query_embedding,
                student_id=student_id,
            )
        except Exception as exc:
            message = f"Vector similarity search failed in Neo4j: {exc}"
            log.error(message)
            raise RuntimeError(message) from exc

        results = []
        async for record in result:
            results.append({
                "id": record["id"],
                "text": record["text"],
                "page_number": record["page_number"],
                "filename": record["filename"],
                "document_id": record["document_id"],
                "scope": record["scope"],
                "score": record["score"],
            })

        log.info("Vector search returned %d results for query: %s", len(results), query[:60])
        return results


# ── Hybrid Search (Graph + Vector) ──────────────────────────────


async def hybrid_search(
    query: str,
    k: int = 5,
    student_id: str | None = None,
) -> list[dict[str, Any]]:
    """Combine vector similarity with graph context.

    Returns vector search results enriched with connected graph entities.
    """
    # Step 1: vector search
    if not student_id:
        raise ValueError("student_id is required for hybrid_search")
    query = (query or "").strip()
    if not query:
        return []
    k = _normalize_k(k)

    vector_results = await similarity_search(
        query=query,
        k=k,
        student_id=student_id,
    )

    if not vector_results:
        return []

    # Step 2: enrich with graph context for each result
    driver = await get_driver()
    related_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    chunk_keys = [
        {"chunk_id": vr["id"], "doc_id": vr["document_id"]}
        for vr in vector_results
        if vr.get("id") and vr.get("document_id")
    ]
    async with driver.session() as session:
        if chunk_keys:
            result = await session.run(
                """
                UNWIND $chunk_refs AS ref
                MATCH (d:Document {id: ref.doc_id})<-[:FROM_DOCUMENT]-(c:Chunk {id: ref.chunk_id})
                OPTIONAL MATCH (:Profile {id: $student_id})-[r]->(e)
                WHERE e._source_document = ref.doc_id
                RETURN ref.chunk_id AS chunk_id,
                       ref.doc_id AS doc_id,
                       collect(DISTINCT {
                           label: labels(e)[0],
                           name: coalesce(e.name, e.code, e.value, e.id),
                           rel: type(r)
                       }) AS entities
                """,
                chunk_refs=chunk_keys,
                student_id=student_id,
            )
            async for record in result:
                related_by_key[(record["chunk_id"], record["doc_id"])] = [
                    entity for entity in (record["entities"] or []) if entity.get("label") and entity.get("name")
                ]

    enriched = []
    for vr in vector_results:
        related_entities = related_by_key.get((vr["id"], vr["document_id"]), [])
        vr["related_entities"] = related_entities
        vr["relevance_tags"] = _relevance_tags(query, vr["text"], related_entities)
        enriched.append(vr)

    return enriched


def _relevance_tags(query: str, text: str, related_entities: list[dict[str, Any]]) -> list[str]:
    """Lightweight entity-aware relevance tags for downstream planners."""
    query_text = query or ""
    chunk_text = text or ""
    query_tokens = _query_tokens(query_text)
    text_tokens = _query_tokens(chunk_text)
    combined_tokens = query_tokens | text_tokens
    entity_labels = {str(entity.get("label") or "") for entity in related_entities}
    entity_name_tokens = _normalized_entity_names(related_entities)
    query_course_codes = {match.group(0).lower().replace(" ", "") for match in _COURSE_CODE_RE.finditer(query_text)}
    text_course_codes = {match.group(0).lower().replace(" ", "") for match in _COURSE_CODE_RE.finditer(chunk_text)}

    tags: list[str] = []
    tags.extend(_matching_tags(query_tokens, _INTENT_KEYWORDS))
    tags.extend(_matching_tags(combined_tokens, _TEXT_SIGNAL_KEYWORDS))

    for label, tag in _ENTITY_LABEL_TAGS.items():
        if label in entity_labels:
            tags.append(tag)

    if text_course_codes:
        tags.append("course_text")
    if query_course_codes and text_course_codes and (query_course_codes & text_course_codes):
        tags.append("course_code_match")
    if entity_name_tokens & query_tokens:
        tags.append("entity_match")

    if {"prerequisite", "prerequisites"} & combined_tokens and "Course" in entity_labels:
        tags.append("course_requirements")
    if {"intern", "internship", "job", "career"} & combined_tokens and "Skill" in entity_labels:
        tags.append("skill_career_alignment")
    if {"graduation", "degree", "program", "major"} & combined_tokens and {"Program", "Course"} & entity_labels:
        tags.append("program_progress")

    deduped: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        if tag and tag not in seen:
            seen.add(tag)
            deduped.append(tag)
    return deduped
