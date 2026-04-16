"""Legacy compatibility shim for Neo4j vector access."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.adapters.neo4j._sanitize import sanitize_neo4j_value
from app.adapters.neo4j.graphDB import GraphDB
from app.adapters.neo4j.vectorDB import VectorDB
from app.config.settings import settings
from app.adapters.neo4j.graph_store import get_driver

log = logging.getLogger("pathfinder.neo4j.vector_store")

VECTOR_INDEX_NAME = "chunk_embeddings"


async def _vector_db() -> VectorDB:
    """Return the new VectorDB adapter on the shared driver."""
    return VectorDB(
        await get_driver(),
        index_name=VECTOR_INDEX_NAME,
        dimensions=int(settings.EMBEDDING_DIMENSIONS),
    )


async def _graph_db() -> GraphDB:
    """Return the new GraphDB adapter on the shared driver."""
    return GraphDB(await get_driver())


async def ensure_vector_index() -> None:
    """Ensure the new vector index exists."""
    await (await _vector_db()).create_vector_index()


async def store_chunks(chunks: list[dict[str, Any]], document_id: str) -> int:
    """Compatibility writer for chunk storage using the new schema."""
    if not chunks:
        return 0
    rows = []
    for idx, chunk in enumerate(chunks):
        chunk_id = str(chunk.get("id") or chunk.get("chunk_id") or "").strip()
        text = str(chunk.get("text") or "").strip()
        if not chunk_id or not text:
            continue
        metadata = {
            "chunk_index": chunk.get("chunk_index", idx),
            "page_number": chunk.get("page_number"),
        }
        rows.append(
            {
                "id": chunk_id,
                "text": text,
                "metadata": metadata,
            }
        )
    if not rows:
        return 0
    result = await (await _vector_db()).batch_upsert_chunks(document_id=document_id, chunks=rows)
    return int(result.get("stored_chunks", 0) or 0)


async def similarity_search(query: str, k: int = 5, student_id: str | None = None) -> list[dict[str, Any]]:
    """Compatibility vector search via the new VectorDB."""
    if not student_id:
        return []
    return sanitize_neo4j_value(await (await _vector_db()).similarity_search(query=query, student_id=student_id, k=k))


async def hybrid_search(query: str, k: int = 5, student_id: str | None = None) -> list[dict[str, Any]]:
    """Compatibility hybrid retrieval via the new GraphDB."""
    if not student_id:
        return []
    return sanitize_neo4j_value(await (await _graph_db()).hybrid_search(student_id=student_id, query=query, k=k))
