"""Neo4j vector store adapter.

Stores document chunks with embeddings and supports semantic search
via Neo4j's built-in vector index.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from neo4j import AsyncDriver

from app.adapters.neo4j.graph_store import get_driver
from app.adapters.embeddings.ollama import get_embeddings
from app.config.settings import settings

log = logging.getLogger("pathfinder.neo4j.vector")

VECTOR_INDEX_NAME = "chunk_embeddings"


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
    driver = await get_driver()
    count = 0
    async with driver.session() as session:
        for chunk in chunks:
            try:
                await session.run(
                    """
                    MATCH (d:Document {id: $doc_id})
                    CREATE (c:Chunk {
                        id: $chunk_id,
                        text: $text,
                        embedding: $embedding,
                        page_number: $page_number,
                        chunk_index: $chunk_index,
                        document_id: $doc_id
                    })-[:FROM_DOCUMENT]->(d)
                    """,
                    doc_id=document_id,
                    chunk_id=chunk["id"],
                    text=chunk["text"],
                    embedding=chunk["embedding"],
                    page_number=chunk.get("page_number"),
                    chunk_index=chunk.get("chunk_index", 0),
                )
                count += 1
            except Exception as exc:
                log.warning("Failed to store chunk %s: %s", chunk.get("id"), exc)
    log.info("Stored %d/%d chunks for document %s", count, len(chunks), document_id)
    return count


# ── Vector Similarity Search ────────────────────────────────────


async def similarity_search(
    query: str,
    k: int = 5,
    scope: str | None = None,
    session_id: str | None = None,
    student_id: str = "default",
) -> list[dict[str, Any]]:
    """Semantic similarity search over Chunk nodes.

    Parameters
    ----------
    query : str
        Natural language query.
    k : int
        Number of results.
    scope : str, optional
        ``'global'``, ``'session'``, or ``None`` (search both).
    session_id : str, optional
        If scope is session, filter by this session.
    student_id : str
        Student to scope results to.
    """
    embeddings = get_embeddings()
    query_embedding = embeddings.embed_query(query)

    driver = await get_driver()
    async with driver.session() as session:
        # Build scope filter
        where_clauses = []
        if scope == "global":
            where_clauses.append("d.scope = 'global'")
        elif scope == "session" and session_id:
            where_clauses.append("d.session_id = $filter_session_id")
        # Otherwise search all documents for this student

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        params: dict[str, Any] = {
            "index_name": VECTOR_INDEX_NAME,
            "k": k,
            "embedding": query_embedding,
            "student_id": student_id,
        }
        if scope == "session" and session_id:
            params["filter_session_id"] = session_id

        result = await session.run(
            f"""
            CALL db.index.vector.queryNodes($index_name, $k, $embedding)
            YIELD node AS chunk, score
            MATCH (chunk)-[:FROM_DOCUMENT]->(d:Document)<-[:UPLOADED]-(s:Student {{id: $student_id}})
            {where_sql}
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
            **params,
        )

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
    student_id: str = "default",
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    """Combine vector similarity with graph context.

    Returns vector search results enriched with connected graph entities.
    """
    # Step 1: vector search
    vector_results = await similarity_search(
        query=query,
        k=k,
        student_id=student_id,
        session_id=session_id,
    )

    if not vector_results:
        return []

    # Step 2: enrich with graph context for each result
    driver = await get_driver()
    enriched = []
    async with driver.session() as session:
        for vr in vector_results:
            # Find entities linked from the same document
            result = await session.run(
                """
                MATCH (d:Document {id: $doc_id})<-[:FROM_DOCUMENT]-(c:Chunk {id: $chunk_id})
                OPTIONAL MATCH (s:Student)-[r]->(e)
                WHERE e._source_document = $doc_id
                RETURN collect(DISTINCT {label: labels(e)[0], name: e.name, rel: type(r)}) AS entities
                """,
                doc_id=vr["document_id"],
                chunk_id=vr["id"],
            )
            record = await result.single()
            vr["related_entities"] = record["entities"] if record else []
            enriched.append(vr)

    return enriched
