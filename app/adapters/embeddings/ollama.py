"""Ollama-backed embedding adapter.

Turns text into vectors using a locally-hosted Ollama model. Every
vector operation in Pathfinder goes through this module:
- `doc_analyst` calls `aembed_documents` to embed new chunks before
  upserting them into the `chunk_embeddings` Neo4j index, and
- the hybrid retriever / vector tools call `aembed_query` to embed the
  user's query and similarity-search against those chunks.

The model (and therefore the vector dimensions) is controlled by
`settings.EMBEDDING_MODEL` and must stay in sync with the dimensions
the Neo4j vector index was created with at startup — if they drift,
inserts will be rejected.

Errors are wrapped in `EmbeddingServiceError` so calling code can show
one clean message ("Ollama isn't reachable / model isn't installed")
instead of leaking provider-specific exceptions.
"""

import asyncio
import logging

from langchain_ollama import OllamaEmbeddings
from app.config.settings import settings

log = logging.getLogger("pathfinder.embeddings.ollama")

# Soft cap on each blocking embedding call — Ollama can hang if the
# model isn't loaded, so we'd rather error fast and show a clear message.
_EMBEDDING_TIMEOUT_SECONDS = 6.0

# One client per (Ollama URL, model name) pair, reused across calls so
# we don't rebuild the HTTP session on every request.
_embeddings_cache: dict[tuple[str, str], OllamaEmbeddings] = {}


class EmbeddingServiceError(RuntimeError):
    """Raised when Ollama is unreachable, the model is missing, or the
    response payload is malformed. Callers catch this to show a single
    user-friendly error instead of vendor-specific traces."""


def get_embeddings_client() -> OllamaEmbeddings:
    """Return a cached Ollama client for the currently-configured model.

    Cached on (URL, model) so switching either at runtime still builds
    a fresh client instead of reusing one pointed at the old target.
    """
    cache_key = (settings.OLLAMA_URL, settings.EMBEDDING_MODEL)
    client = _embeddings_cache.get(cache_key)
    if client is None:
        client = OllamaEmbeddings(
            model=settings.EMBEDDING_MODEL,
            base_url=settings.OLLAMA_URL,
        )
        _embeddings_cache[cache_key] = client
    return client

async def aembed_query(text: str, *, timeout_seconds: float = _EMBEDDING_TIMEOUT_SECONDS) -> list[float]:
    """Async embed a single query string — safe to call from LangGraph nodes.

    The underlying LangChain client is blocking, so we offload to a
    thread and enforce a timeout so a stuck Ollama doesn't freeze the
    event loop.
    """
    return _coerce_embedding(
        await _run_async_embedding_call(
            get_embeddings_client().embed_query,
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
    """Async batch embed — the ingestion path uses this for new chunks."""
    raw = await _run_async_embedding_call(
        get_embeddings_client().embed_documents,
        texts,
        operation="embed_documents",
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(raw, list):
        raise EmbeddingServiceError("Embedding service returned a non-list response for embed_documents.")
    return [_coerce_embedding(item) for item in raw]

async def _run_async_embedding_call(fn, payload, *, operation: str, timeout_seconds: float):
    """Run the blocking LangChain fn in a thread, rewrap errors, enforce timeout.

    Rewraps any provider exception as `EmbeddingServiceError` with a clear
    operator-facing message, so upstream code doesn't need to distinguish
    "dead" from "slow" — both mean "embeddings aren't usable right now".
    """
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
    """Guarantee the return is `list[float]` — Neo4j rejects anything else."""
    if not isinstance(value, list):
        raise EmbeddingServiceError("Embedding service returned a non-list embedding vector.")
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise EmbeddingServiceError("Embedding service returned a malformed embedding vector.") from exc
