"""Central registry for runtime-selectable execution capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.adapters.llm.lmstudio import get_active_lmstudio_text_model
from app.config.settings import settings


WebSearchProvider = Callable[[str, int], Awaitable[list[dict[str, Any]]]]
DocumentIngestor = Callable[[bytes, str], Awaitable[list[dict[str, Any]]]]


@dataclass(frozen=True)
class ExecutionRegistry:
    """Resolved execution capabilities for the current runtime."""

    text_model: str
    vision_model: str
    retrieval_strategy: str
    web_providers: tuple[str, ...]
    document_ingestors: dict[str, str]


def get_execution_registry() -> ExecutionRegistry:
    """Return the current execution capability registry."""
    return ExecutionRegistry(
        text_model=get_active_lmstudio_text_model(),
        vision_model=settings.VISION_MODEL,
        retrieval_strategy="memory_pack",
        web_providers=tuple(name for name, _ in _web_provider_entries()),
        document_ingestors={
            "pdf": "extract_text_from_pdf",
            "image": "extract_text_from_image",
            "docx": "extract_text_from_docx",
        },
    )


def get_active_text_model() -> str:
    return get_execution_registry().text_model


def get_active_vision_model() -> str:
    return get_execution_registry().vision_model


def get_active_retrieval_strategy() -> str:
    return get_execution_registry().retrieval_strategy


def get_web_provider_names() -> list[str]:
    return list(get_execution_registry().web_providers)


async def execute_web_search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Run web search through the configured provider chain."""
    errors: list[str] = []
    aggregated: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for name, provider in _web_provider_entries():
        try:
            results = await provider(query, max_results=max_results)
            if results:
                for result in results:
                    url = result.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        aggregated.append(result)
                    if len(aggregated) >= max_results:
                        break
            if len(aggregated) >= max_results:
                break
        except Exception as exc:
            errors.append(f"{name}: {exc}")

    if aggregated:
        return aggregated[:max_results]

    if errors:
        raise RuntimeError("; ".join(errors))
    return []


async def execute_document_ingestion(file_type: str, content: bytes, filename: str) -> list[dict[str, Any]]:
    """Dispatch document extraction by file type."""
    ingestor = _document_ingestors().get(file_type)
    if ingestor is None:
        raise ValueError(f"Unsupported file type for ingestion: {file_type}")
    return await ingestor(content, filename)


def _web_provider_entries() -> list[tuple[str, WebSearchProvider]]:
    from app.adapters.web_search import tavily, google_cse, brave, duckduckgo

    return [
        ("Tavily", tavily.search),
        ("Google CSE", google_cse.search),
        ("Brave", brave.search),
        ("DuckDuckGo", duckduckgo.search),
    ]


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
