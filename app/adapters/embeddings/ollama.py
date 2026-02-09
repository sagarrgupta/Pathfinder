"""Ollama embeddings adapter.

Provides a singleton OllamaEmbeddings instance for generating
text embeddings via the local Ollama server.
"""

from __future__ import annotations

from typing import Optional

from langchain_ollama import OllamaEmbeddings

from app.config.settings import settings

_embeddings: Optional[OllamaEmbeddings] = None


def get_embeddings() -> OllamaEmbeddings:
    """Return the singleton embeddings model (mxbai-embed-large)."""
    global _embeddings
    if _embeddings is None:
        _embeddings = OllamaEmbeddings(
            model=settings.EMBEDDING_MODEL,
            base_url=settings.OLLAMA_URL,
        )
    return _embeddings
