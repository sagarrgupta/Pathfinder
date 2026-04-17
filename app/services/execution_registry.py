"""Central registry for runtime-selectable execution capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.config.settings import settings


DocumentIngestor = Callable[[bytes, str], Awaitable[list[dict[str, Any]]]]
_WEB_PROVIDER_NAMES = ("Tavily", "Google CSE", "Brave", "DuckDuckGo")
_DOCUMENT_INGESTOR_NAMES = {
    "pdf": "extract_text_from_pdf",
    "image": "extract_text_from_image",
    "docx": "extract_text_from_docx",
}


@dataclass(frozen=True)
class ExecutionRegistry:
    """Resolved execution capabilities for the current runtime."""

    text_model: str
    retrieval_strategy: str
    web_providers: tuple[str, ...]
    document_ingestors: dict[str, str]


def get_execution_registry() -> ExecutionRegistry:
    """Return the current execution capability registry."""
    return ExecutionRegistry(
        text_model=settings.LLM_MODEL,
        retrieval_strategy="memory_pack",
        web_providers=_WEB_PROVIDER_NAMES,
        document_ingestors=dict(_DOCUMENT_INGESTOR_NAMES),
    )


def get_active_text_model() -> str:
    return get_execution_registry().text_model


def get_active_retrieval_strategy() -> str:
    return get_execution_registry().retrieval_strategy


async def execute_document_ingestion(file_type: str, content: bytes, filename: str) -> list[dict[str, Any]]:
    """Dispatch document extraction by file type."""
    ingestor = _document_ingestors().get(file_type)
    if ingestor is None:
        raise ValueError(f"Unsupported file type for ingestion: {file_type}")
    return await ingestor(content, filename)


def _document_ingestors() -> dict[str, DocumentIngestor]:
    from app.adapters.pdf.extractor import (
        extract_text_from_docx,
        extract_text_from_image,
        extract_text_from_pdf,
    )

    return {
        "pdf": extract_text_from_pdf,
        "image": extract_text_from_image,
        "docx": extract_text_from_docx,
    }
