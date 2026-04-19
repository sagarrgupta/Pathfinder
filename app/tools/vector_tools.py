"""Vector MCP tools."""

from __future__ import annotations

import logging
from typing import Any, Optional

from neo4j import AsyncDriver, AsyncGraphDatabase

from app.adapters.neo4j.vectorDB import VectorDB
from app.config.settings import settings
from app.tools.tools import ToolContext, ToolSpec, bounded_text, pick_scalar_fields

log = logging.getLogger("pathfinder.neo4j.vector")

_driver: Optional[AsyncDriver] = None
_VECTOR_INDEX_NAME = "chunk_embeddings"

JSON_VALUE_SCHEMA: dict[str, Any] = {
    "anyOf": [
        {"type": "string"},
        {"type": "number"},
        {"type": "integer"},
        {"type": "boolean"},
        {"type": "object"},
        {"type": "array"},
        {"type": "null"},
    ]
}

METADATA_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Flexible chunk metadata stored alongside the chunk text. Use this for source-specific details that should travel with the chunk.",
    "additionalProperties": JSON_VALUE_SCHEMA,
}

CHUNK_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "chunk_id": {"type": "string", "description": "Stable chunk id for the chunk being stored or updated."},
        "text": {"type": "string", "description": "Chunk text content used for storage and retrieval."},
        "metadata": METADATA_SCHEMA,
    },
    "required": ["chunk_id", "text"],
    "additionalProperties": False,
}


async def get_driver() -> AsyncDriver:
    """Return or create the singleton Neo4j async driver."""
    global _driver
    if _driver is None:
        if not str(settings.NEO4J_PASSWORD or "").strip():
            raise RuntimeError(
                "NEO4J_PASSWORD is not configured. Set Neo4j credentials before starting Pathfinder."
            )
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


async def _vector_db(context: ToolContext) -> VectorDB:
    driver = getattr(context, "driver", None) or await get_driver()
    return VectorDB(
        driver,
        index_name=_VECTOR_INDEX_NAME,
        dimensions=int(settings.EMBEDDING_DIMENSIONS),
    )


def _summarize_chunk(chunk: dict[str, Any], *, text_limit: int = 240) -> dict[str, Any]:
    if not isinstance(chunk, dict):
        return {"value": bounded_text(chunk, limit=text_limit)}
    summary: dict[str, Any] = {}
    for key in ("chunk_id", "id", "document_id", "chunk_index", "page_number", "score"):
        value = chunk.get(key)
        if value not in (None, "", [], {}):
            normalized_key = "chunk_id" if key == "id" else key
            summary[normalized_key] = value
    text = chunk.get("text") or chunk.get("content") or chunk.get("snippet") or ""
    if text:
        summary["text_preview"] = bounded_text(text, limit=text_limit)
    metadata = chunk.get("metadata")
    if isinstance(metadata, dict):
        metadata_summary = pick_scalar_fields(metadata, exclude={"embedding"}, limit=6)
        if metadata_summary:
            summary["metadata"] = metadata_summary
    return summary or {"value": bounded_text(chunk, limit=text_limit)}


def _compact_chunk_result(chunk: dict[str, Any]) -> dict[str, Any]:
    return _summarize_chunk(chunk, text_limit=220)
async def _create_vector_index(_: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    vector_db = await _vector_db(context)
    await vector_db.create_vector_index()
    return {"status": "success", "index_name": _VECTOR_INDEX_NAME}


def _compact_create_vector_index(_: dict[str, Any], result: dict[str, Any], __: ToolContext) -> dict[str, Any]:
    return {"status": str(result.get("status") or ""), "index_name": str(result.get("index_name") or "")}


async def _upsert_chunk_metadata(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    vector_db = await _vector_db(context)
    chunk = await vector_db.upsert_chunk_metadata(
        chunk_id=str(arguments.get("chunk_id", "") or "").strip(),
        document_id=str(arguments.get("document_id", "") or "").strip(),
        text=str(arguments.get("text", "") or ""),
        metadata=dict(arguments.get("metadata") or {}),
    )
    return {"chunk": chunk}


def _compact_upsert_chunk_metadata(_: dict[str, Any], result: dict[str, Any], __: ToolContext) -> dict[str, Any]:
    return {"chunk": _compact_chunk_result(dict(result.get("chunk") or {}))}


async def _upsert_chunk(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    vector_db = await _vector_db(context)
    chunk = await vector_db.upsert_chunk(
        chunk_id=str(arguments.get("chunk_id", "") or "").strip(),
        document_id=str(arguments.get("document_id", "") or "").strip(),
        text=str(arguments.get("text", "") or ""),
        metadata=dict(arguments.get("metadata") or {}),
    )
    return {"chunk": chunk}


def _compact_upsert_chunk(_: dict[str, Any], result: dict[str, Any], __: ToolContext) -> dict[str, Any]:
    return {"chunk": _compact_chunk_result(dict(result.get("chunk") or {}))}


async def _batch_upsert_chunks(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    vector_db = await _vector_db(context)
    result = await vector_db.batch_upsert_chunks(
        document_id=str(arguments.get("document_id", "") or "").strip(),
        chunks=list(arguments.get("chunks") or []),
    )
    return {"result": result}


def _compact_batch_upsert(arguments: dict[str, Any], result: dict[str, Any], __: ToolContext) -> dict[str, Any]:
    payload = dict(result.get("result") or {})
    return {
        "document_id": str(arguments.get("document_id", "") or "").strip(),
        "requested_chunks": len(list(arguments.get("chunks", []) or [])),
        "result": pick_scalar_fields(payload, limit=8),
    }


async def _delete_document_chunks(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    vector_db = await _vector_db(context)
    result = await vector_db.delete_document_chunks(
        document_id=str(arguments.get("document_id", "") or "").strip(),
    )
    return {"result": result}


def _compact_delete_document_chunks(arguments: dict[str, Any], result: dict[str, Any], __: ToolContext) -> dict[str, Any]:
    return {
        "document_id": str(arguments.get("document_id", "") or "").strip(),
        "result": pick_scalar_fields(dict(result.get("result") or {}), limit=8),
    }


async def _health_check(_: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    vector_db = await _vector_db(context)
    return await vector_db.health_check()


def _compact_health_check(_: dict[str, Any], result: dict[str, Any], __: ToolContext) -> dict[str, Any]:
    return pick_scalar_fields(result, limit=8)


async def _get_chunk(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    vector_db = await _vector_db(context)
    try:
        chunk = await vector_db.get_chunk(
            chunk_id=str(arguments.get("chunk_id", "") or "").strip(),
        )
    except ValueError as exc:
        if str(exc) == "chunk not found":
            return {"found": False, "chunk": None}
        raise
    return {"found": True, "chunk": chunk}


def _compact_get_chunk(arguments: dict[str, Any], result: dict[str, Any], __: ToolContext) -> dict[str, Any]:
    if not result.get("found"):
        return {
            "found": False,
            "chunk_id": str(arguments.get("chunk_id", "") or "").strip(),
        }
    chunk = dict(result.get("chunk") or {})
    return {"found": True, "chunk": _compact_chunk_result(dict(chunk or {}))}


async def _get_chunks_for_document(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    vector_db = await _vector_db(context)
    chunks = await vector_db.get_chunks_for_document(
        document_id=str(arguments.get("document_id", "") or "").strip(),
    )
    return {"chunks": chunks}


def _compact_get_chunks_for_document(arguments: dict[str, Any], result: dict[str, Any], __: ToolContext) -> dict[str, Any]:
    chunks = list(result.get("chunks", []) or [])
    return {
        "document_id": str(arguments.get("document_id", "") or "").strip(),
        "count": len(chunks),
        "chunks": [_compact_chunk_result(dict(chunk)) for chunk in chunks[:20] if isinstance(chunk, dict)],
    }


async def _get_chunks_for_student(_: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    vector_db = await _vector_db(context)
    chunks = await vector_db.get_chunks_for_student(student_id=str(context.student_id or "").strip())
    return {"chunks": chunks}


def _compact_get_chunks_for_student(_: dict[str, Any], result: dict[str, Any], __: ToolContext) -> dict[str, Any]:
    chunks = list(result.get("chunks", []) or [])
    return {
        "count": len(chunks),
        "chunks": [_compact_chunk_result(dict(chunk)) for chunk in chunks[:20] if isinstance(chunk, dict)],
    }


async def _delete_chunk(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    vector_db = await _vector_db(context)
    result = await vector_db.delete_chunk(
        chunk_id=str(arguments.get("chunk_id", "") or "").strip(),
    )
    return {"result": result}


def _compact_delete_chunk(arguments: dict[str, Any], result: dict[str, Any], __: ToolContext) -> dict[str, Any]:
    return {
        "chunk_id": str(arguments.get("chunk_id", "") or "").strip(),
        "result": pick_scalar_fields(dict(result.get("result") or {}), limit=8),
    }


async def _get_chunk_neighbors(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    vector_db = await _vector_db(context)
    try:
        neighbors = await vector_db.get_chunk_neighbors(
            chunk_id=str(arguments.get("chunk_id", "") or "").strip(),
        )
    except ValueError as exc:
        if str(exc) == "chunk not found":
            return {"found": False, "chunk": None, "document": None}
        raise
    return {
        "found": True,
        "chunk": dict(neighbors.get("chunk") or {}),
        "document": dict(neighbors.get("document") or {}),
    }


def _compact_chunk_neighbors(arguments: dict[str, Any], result: dict[str, Any], __: ToolContext) -> dict[str, Any]:
    if not result.get("found"):
        return {
            "found": False,
            "chunk_id": str(arguments.get("chunk_id", "") or "").strip(),
        }
    return {
        "found": True,
        "chunk": _compact_chunk_result(dict(result.get("chunk") or {})),
        "document": pick_scalar_fields(dict(result.get("document") or {}), limit=6),
    }


async def _get_document_search_context(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    vector_db = await _vector_db(context)
    chunks = await vector_db.get_document_search_context(
        document_id=str(arguments.get("document_id", "") or "").strip(),
    )
    return {"chunks": chunks}


def _compact_document_search_context(arguments: dict[str, Any], result: dict[str, Any], __: ToolContext) -> dict[str, Any]:
    chunks = list(result.get("chunks", []) or [])
    return {
        "document_id": str(arguments.get("document_id", "") or "").strip(),
        "count": len(chunks),
        "chunks": [
            {
                **_compact_chunk_result(dict(chunk)),
                "summary": bounded_text((chunk or {}).get("summary"), limit=220),
            }
            for chunk in chunks[:20]
            if isinstance(chunk, dict)
        ],
    }


def get_vector_tool_specs() -> list[ToolSpec]:
    """Return vector tool definitions for chunk storage and retrieval."""
    return [
        ToolSpec(
            name="create_vector_index",
            description="Create the Neo4j vector index used for chunk embedding retrieval. Use this when preparing a fresh database or after a reset so similarity search has the required index support.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            handler=_create_vector_index,
            compact_handler=_compact_create_vector_index,
        ),
        ToolSpec(
            name="upsert_chunk_metadata",
            description="Create or update one chunk's text and metadata without generating an embedding. Use this when chunk content must exist first but embedding generation should be deferred.",
            input_schema={
                "type": "object",
                "properties": {"document_id": {"type": "string", "description": "Document id that owns the chunk."}, **CHUNK_INPUT_SCHEMA["properties"]},
                "required": ["document_id", "chunk_id", "text"],
                "additionalProperties": False,
            },
            handler=_upsert_chunk_metadata,
            compact_handler=_compact_upsert_chunk_metadata,
        ),
        ToolSpec(
            name="upsert_chunk",
            description="Create or update one chunk, store its metadata, generate an embedding, and attach it to the owning document. Use this for the standard chunk write path when the chunk should be immediately retrievable by vector search.",
            input_schema={
                "type": "object",
                "properties": {"document_id": {"type": "string", "description": "Document id that owns the chunk."}, **CHUNK_INPUT_SCHEMA["properties"]},
                "required": ["document_id", "chunk_id", "text"],
                "additionalProperties": False,
            },
            handler=_upsert_chunk,
            compact_handler=_compact_upsert_chunk,
        ),
        ToolSpec(
            name="batch_upsert_chunks",
            description="Create or update many chunks for one document in a single call, including embeddings. Use this for ingestion or re-ingestion when chunk evidence is already prepared and should be written efficiently.",
            input_schema={
                "type": "object",
                "properties": {
                    "document_id": {"type": "string", "description": "Document id that owns all provided chunks."},
                    "chunks": {"type": "array", "description": "List of chunk payloads to write for the document.", "items": CHUNK_INPUT_SCHEMA},
                },
                "required": ["document_id", "chunks"],
                "additionalProperties": False,
            },
            handler=_batch_upsert_chunks,
            compact_handler=_compact_batch_upsert,
        ),
        ToolSpec(
            name="delete_document_chunks",
            description="Delete all chunks attached to one document. Use this during document replacement, cleanup, or re-ingestion when old chunk evidence should be removed first.",
            input_schema={
                "type": "object",
                "properties": {"document_id": {"type": "string", "description": "Document id whose chunks should be deleted."}},
                "required": ["document_id"],
                "additionalProperties": False,
            },
            handler=_delete_document_chunks,
            compact_handler=_compact_delete_document_chunks,
        ),
        ToolSpec(
            name="vector_health_check",
            description="Check Neo4j/vector connectivity and return the configured vector index metadata. Use this for diagnostics before relying on chunk retrieval.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            handler=_health_check,
            compact_handler=_compact_health_check,
        ),
        ToolSpec(
            name="get_chunk",
            description="Fetch one chunk with its text, stored metadata, and document linkage. Use this when the model needs the exact stored representation of a specific chunk.",
            input_schema={
                "type": "object",
                "properties": {"chunk_id": {"type": "string", "description": "Chunk id to fetch."}},
                "required": ["chunk_id"],
                "additionalProperties": False,
            },
            handler=_get_chunk,
            compact_handler=_compact_get_chunk,
        ),
        ToolSpec(
            name="get_chunks_for_document",
            description="Return every stored chunk for one document. Use this when ingestion or retrieval logic needs to inspect all evidence attached to a document.",
            input_schema={
                "type": "object",
                "properties": {"document_id": {"type": "string", "description": "Document id whose chunks should be returned."}},
                "required": ["document_id"],
                "additionalProperties": False,
            },
            handler=_get_chunks_for_document,
            compact_handler=_compact_get_chunks_for_document,
        ),
        ToolSpec(
            name="get_chunks_for_student",
            description="Return stored chunks across every document owned by the active student. Use this for broader evidence inspection, debugging, or student-wide retrieval context.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            handler=_get_chunks_for_student,
            compact_handler=_compact_get_chunks_for_student,
        ),
        ToolSpec(
            name="delete_chunk",
            description="Delete one stored chunk safely. Use this during targeted cleanup or when one chunk must be removed without deleting the rest of the document evidence.",
            input_schema={
                "type": "object",
                "properties": {"chunk_id": {"type": "string", "description": "Chunk id to delete."}},
                "required": ["chunk_id"],
                "additionalProperties": False,
            },
            handler=_delete_chunk,
            compact_handler=_compact_delete_chunk,
        ),
        ToolSpec(
            name="get_chunk_neighbors",
            description="Return one chunk together with its immediate document context. Use this when the model needs the owning document for a chunk before deciding how to relate chunk evidence back to the graph.",
            input_schema={
                "type": "object",
                "properties": {"chunk_id": {"type": "string", "description": "Chunk id whose immediate context should be returned."}},
                "required": ["chunk_id"],
                "additionalProperties": False,
            },
            handler=_get_chunk_neighbors,
            compact_handler=_compact_chunk_neighbors,
        ),
        ToolSpec(
            name="get_document_search_context",
            description="Return chunk summaries for one document in a retrieval-friendly shape. Use this when the model needs to review document evidence without running vector search first.",
            input_schema={
                "type": "object",
                "properties": {"document_id": {"type": "string", "description": "Document id whose chunk summaries should be returned."}},
                "required": ["document_id"],
                "additionalProperties": False,
            },
            handler=_get_document_search_context,
            compact_handler=_compact_document_search_context,
        ),
    ]
