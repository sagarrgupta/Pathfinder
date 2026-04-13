"""Ollama embeddings adapter.

Centralizes client construction plus sync/async embedding helpers so
callers get consistent timeout handling and actionable failures.
"""

from __future__ import annotations

import asyncio
import logging

from langchain_ollama import OllamaEmbeddings

from app.config.settings import settings

log = logging.getLogger("pathfinder.embeddings.ollama")

_EMBEDDING_TIMEOUT_SECONDS = 6.0
_embeddings_cache: dict[tuple[str, str], OllamaEmbeddings] = {}


class EmbeddingServiceError(RuntimeError):
    """Raised when Ollama embeddings are unavailable or malformed."""


def get_embeddings() -> OllamaEmbeddings:
    """Return the cached Ollama embeddings client for the configured model."""
    cache_key = (settings.OLLAMA_URL, settings.EMBEDDING_MODEL)
    client = _embeddings_cache.get(cache_key)
    if client is None:
        client = OllamaEmbeddings(
            model=settings.EMBEDDING_MODEL,
            base_url=settings.OLLAMA_URL,
        )
        _embeddings_cache[cache_key] = client
    return client


def embed_query(text: str) -> list[float]:
    """Embed one query string with consistent runtime error handling."""
    return _coerce_embedding(
        _run_embedding_call(get_embeddings().embed_query, text, operation="embed_query")
    )


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed many document chunks with consistent runtime error handling."""
    raw = _run_embedding_call(
        get_embeddings().embed_documents,
        texts,
        operation="embed_documents",
    )
    if not isinstance(raw, list):
        raise EmbeddingServiceError("Embedding service returned a non-list response for embed_documents.")
    return [_coerce_embedding(item) for item in raw]


async def aembed_query(text: str, *, timeout_seconds: float = _EMBEDDING_TIMEOUT_SECONDS) -> list[float]:
    """Async wrapper for embedding one query with timeout protection."""
    return _coerce_embedding(
        await _run_async_embedding_call(
            get_embeddings().embed_query,
            text,
            operation="embed_query",
            timeout_seconds=timeout_seconds,
        )
    )


async def aembed_documents(
    texts: list[str],
    *,
    timeout_seconds: float = _EMBEDDING_TIMEOUT_SECONDS,
) -> list[list[float]]:
    """Async wrapper for embedding many chunks with timeout protection."""
    raw = await _run_async_embedding_call(
        get_embeddings().embed_documents,
        texts,
        operation="embed_documents",
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(raw, list):
        raise EmbeddingServiceError("Embedding service returned a non-list response for embed_documents.")
    return [_coerce_embedding(item) for item in raw]


def _run_embedding_call(fn, payload, *, operation: str):
    """Run one synchronous embedding call and wrap provider failures."""
    try:
        return fn(payload)
    except Exception as exc:
        message = (
            "Embedding service is unavailable. Check that Ollama is running and "
            f"the embedding model '{settings.EMBEDDING_MODEL}' is installed."
        )
        log.error("%s Operation=%s original_error=%s", message, operation, exc)
        raise EmbeddingServiceError(message) from exc


async def _run_async_embedding_call(fn, payload, *, operation: str, timeout_seconds: float):
    """Run one blocking embedding call in a thread with timeout protection."""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(fn, payload),
            timeout=max(1.0, float(timeout_seconds)),
        )
    except asyncio.TimeoutError as exc:
        message = (
            f"Embedding service timed out after {timeout_seconds:.1f}s. "
            "Check that Ollama is running and responsive."
        )
        log.error("%s Operation=%s", message, operation)
        raise EmbeddingServiceError(message) from exc
    except Exception as exc:
        message = (
            "Embedding service is unavailable. Check that Ollama is running and "
            f"the embedding model '{settings.EMBEDDING_MODEL}' is installed."
        )
        log.error("%s Operation=%s original_error=%s", message, operation, exc)
        raise EmbeddingServiceError(message) from exc


def _coerce_embedding(value: object) -> list[float]:
    """Validate one embedding vector and coerce numeric values to floats."""
    if not isinstance(value, list):
        raise EmbeddingServiceError("Embedding service returned a non-list embedding vector.")
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise EmbeddingServiceError("Embedding service returned a malformed embedding vector.") from exc
