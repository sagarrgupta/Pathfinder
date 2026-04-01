"""Retrieval strategy selection and benchmarking."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from app.adapters.neo4j.graph_store import get_student_documents, update_document
from app.adapters.neo4j.vector_store import hybrid_search, similarity_search
from app.config.settings import settings

log = logging.getLogger("pathfinder.services.retrieval")

RETRIEVAL_EMBEDDING = "embedding"
RETRIEVAL_HYBRID = "hybrid"
RETRIEVAL_PAGEINDEX = "pageindex"
RETRIEVAL_MODES = [RETRIEVAL_EMBEDDING, RETRIEVAL_HYBRID, RETRIEVAL_PAGEINDEX]


def normalize_retrieval_mode(mode: str | None) -> str:
    """Normalize a retrieval mode to a supported value."""
    candidate = (mode or settings.DEFAULT_RETRIEVAL_MODE or RETRIEVAL_HYBRID).strip().lower()
    aliases = {
        "embedding_only": RETRIEVAL_EMBEDDING,
        "vector": RETRIEVAL_EMBEDDING,
        "vector_only": RETRIEVAL_EMBEDDING,
        "semantic": RETRIEVAL_EMBEDDING,
        "pageindex_hybrid": RETRIEVAL_PAGEINDEX,
        "pageindex+graph+web": RETRIEVAL_PAGEINDEX,
        "current": RETRIEVAL_HYBRID,
    }
    candidate = aliases.get(candidate, candidate)
    return candidate if candidate in RETRIEVAL_MODES else RETRIEVAL_HYBRID


async def retrieve_documents(
    query: str,
    student_id: str = "default",
    session_id: str | None = None,
    mode: str | None = None,
    top_k: int | None = None,
) -> dict[str, Any]:
    """Run the selected retrieval strategy."""
    mode = normalize_retrieval_mode(mode)
    top_k = top_k or settings.TOP_K

    if mode == RETRIEVAL_EMBEDDING:
        documents, stats = await _run_embedding_search(query, student_id, session_id, top_k)
    elif mode == RETRIEVAL_PAGEINDEX:
        documents, stats = await _run_pageindex_search(query, student_id, session_id, top_k)
    else:
        documents, stats = await _run_hybrid_search(query, student_id, session_id, top_k)

    return {"mode": mode, "documents": documents, "stats": stats}


async def compare_retrieval_methods(
    query: str,
    student_id: str = "default",
    session_id: str | None = None,
    top_k: int | None = None,
) -> dict[str, Any]:
    """Run all retrieval modes and return side-by-side stats."""
    comparisons: list[dict[str, Any]] = []
    for mode in RETRIEVAL_MODES:
        try:
            result = await retrieve_documents(
                query=query,
                student_id=student_id,
                session_id=session_id,
                mode=mode,
                top_k=top_k,
            )
            comparisons.append({
                "mode": mode,
                "ok": True,
                "stats": result["stats"],
                "sample_results": _preview_results(result["documents"]),
            })
        except Exception as exc:
            log.warning("Retrieval comparison failed for %s: %s", mode, exc)
            comparisons.append({
                "mode": mode,
                "ok": False,
                "error": str(exc),
                "stats": {"mode": mode, "elapsed_ms": 0, "result_count": 0},
                "sample_results": [],
            })
    return {"query": query, "comparisons": comparisons}


async def _run_embedding_search(
    query: str,
    student_id: str,
    session_id: str | None,
    top_k: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    start = time.perf_counter()
    results = await similarity_search(
        query=query,
        k=top_k,
        student_id=student_id,
        session_id=session_id,
    )
    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
    scores = [r.get("score", 0.0) for r in results if isinstance(r.get("score"), (int, float))]
    stats = {
        "mode": RETRIEVAL_EMBEDDING,
        "elapsed_ms": elapsed_ms,
        "result_count": len(results),
        "document_count": len({r.get("document_id") for r in results if r.get("document_id")}),
        "top_score": max(scores) if scores else None,
        "avg_score": round(sum(scores) / len(scores), 4) if scores else None,
    }
    return results, stats


async def _run_hybrid_search(
    query: str,
    student_id: str,
    session_id: str | None,
    top_k: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    start = time.perf_counter()
    results = await hybrid_search(
        query=query,
        k=top_k,
        student_id=student_id,
        session_id=session_id,
    )
    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
    scores = [r.get("score", 0.0) for r in results if isinstance(r.get("score"), (int, float))]
    related_entities = sum(len(r.get("related_entities", [])) for r in results)
    stats = {
        "mode": RETRIEVAL_HYBRID,
        "elapsed_ms": elapsed_ms,
        "result_count": len(results),
        "document_count": len({r.get("document_id") for r in results if r.get("document_id")}),
        "top_score": max(scores) if scores else None,
        "avg_score": round(sum(scores) / len(scores), 4) if scores else None,
        "related_entity_count": related_entities,
    }
    return results, stats


async def _run_pageindex_search(
    query: str,
    student_id: str,
    session_id: str | None,
    top_k: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    client = get_pageindex_client(student_id)
    documents = await get_student_documents(student_id=student_id, session_id=session_id)
    start = time.perf_counter()

    if not documents:
        return [], {
            "mode": RETRIEVAL_PAGEINDEX,
            "elapsed_ms": round((time.perf_counter() - start) * 1000, 1),
            "result_count": 0,
            "document_count": 0,
            "documents_selected": 0,
            "pages_returned": 0,
        }

    indexed_docs = await _ensure_pageindex_documents(client, documents)
    if not indexed_docs:
        return [], {
            "mode": RETRIEVAL_PAGEINDEX,
            "elapsed_ms": round((time.perf_counter() - start) * 1000, 1),
            "result_count": 0,
            "document_count": len(documents),
            "documents_selected": 0,
            "pages_returned": 0,
        }

    selected_docs = _select_pageindex_documents(query, indexed_docs, top_k=min(3, len(indexed_docs)))
    results: list[dict[str, Any]] = []
    page_fetch_count = 0

    for rank, doc in enumerate(selected_docs, start=1):
        page_ranges = _select_page_ranges(query, client, doc)
        for page_range in page_ranges:
            raw_content = client.get_page_content(doc["pageindex_doc_id"], page_range)
            pages = _safe_json_loads(raw_content, default=[])
            if not isinstance(pages, list) or not pages:
                continue
            page_fetch_count += 1
            text = "\n\n".join(
                f"[Page {page.get('page', '?')}] {page.get('content', '').strip()}"
                for page in pages
                if page.get("content")
            ).strip()
            if not text:
                continue
            results.append({
                "id": f"{doc['id']}:{page_range}",
                "document_id": doc["id"],
                "filename": doc.get("filename", ""),
                "text": text[:6000],
                "page_range": page_range,
                "page_numbers": [page.get("page") for page in pages if page.get("page") is not None],
                "score": round(max(0.0, 1.0 - (rank - 1) * 0.15), 3),
                "scope": doc.get("scope"),
                "retrieval_method": RETRIEVAL_PAGEINDEX,
            })
            if len(results) >= top_k:
                break
        if len(results) >= top_k:
            break

    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
    stats = {
        "mode": RETRIEVAL_PAGEINDEX,
        "elapsed_ms": elapsed_ms,
        "result_count": len(results),
        "document_count": len(indexed_docs),
        "documents_selected": len(selected_docs),
        "page_fetches": page_fetch_count,
        "pages_returned": sum(len(r.get("page_numbers", [])) for r in results),
    }
    return results, stats


def get_pageindex_client(student_id: str):
    """Create a PageIndex client for the student workspace."""
    try:
        from pageindex import PageIndexClient
    except Exception as exc:
        raise RuntimeError(
            "PageIndex is not available. Install the PageIndex dependencies to use this retrieval mode."
        ) from exc

    os.environ.setdefault("OPENAI_API_KEY", settings.LLM_API_KEY)
    os.environ.setdefault("OPENAI_BASE_URL", settings.LLM_BASE_URL)
    os.environ.setdefault("OPENAI_API_BASE", settings.LLM_BASE_URL)

    workspace = Path(settings.PAGEINDEX_WORKSPACE_DIR).expanduser() / student_id
    workspace.mkdir(parents=True, exist_ok=True)
    model = settings.PAGEINDEX_MODEL or settings.LLM_MODEL
    retrieve_model = settings.PAGEINDEX_RETRIEVE_MODEL or settings.LLM_MODEL
    return PageIndexClient(model=model, retrieve_model=retrieve_model, workspace=str(workspace))


async def _ensure_pageindex_documents(client: Any, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only PDF documents that already have a PageIndex document id."""
    indexed_docs: list[dict[str, Any]] = []
    for doc in documents:
        file_path = doc.get("file_path")
        if doc.get("type") != "pdf" or not file_path or not os.path.exists(file_path):
            continue
        pageindex_doc_id = doc.get("pageindex_doc_id")
        if pageindex_doc_id and pageindex_doc_id in client.documents:
            indexed_docs.append(doc)
    return indexed_docs


def _select_pageindex_documents(
    query: str,
    documents: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    """Pick the most promising documents using keyword overlap, not another LLM call."""
    if len(documents) <= top_k:
        return documents

    query_terms = _query_terms(query)
    ranked = sorted(
        documents,
        key=lambda doc: _document_keyword_score(doc, query_terms),
        reverse=True,
    )
    return ranked[:top_k]


def _select_page_ranges(
    query: str,
    client: Any,
    document: dict[str, Any],
) -> list[str]:
    """Use the PageIndex tree to identify likely pages with simple scoring."""
    structure_raw = client.get_document_structure(document["pageindex_doc_id"])
    structure = _safe_json_loads(structure_raw, default=[])
    if not isinstance(structure, list):
        return ["1-2"]

    query_terms = _query_terms(query)
    candidates = _collect_structure_ranges(structure, query_terms)
    if not candidates:
        return ["1-2"]

    page_ranges = []
    for candidate in candidates[:2]:
        page_range = candidate["page_range"]
        if page_range not in page_ranges:
            page_ranges.append(page_range)
    return page_ranges or ["1-2"]


def _safe_json_loads(content: str, default: Any) -> Any:
    """Parse a JSON object or array from model output."""
    content = content.strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        start = content.find(opener)
        end = content.rfind(closer)
        if start >= 0 and end > start:
            try:
                return json.loads(content[start:end + 1])
            except json.JSONDecodeError:
                continue
    return default


def _preview_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create compact previews for benchmark responses."""
    previews = []
    for item in results[:3]:
        previews.append({
            "filename": item.get("filename", ""),
            "score": item.get("score"),
            "page_range": item.get("page_range"),
            "text_preview": item.get("text", "")[:220],
        })
    return previews


def _query_terms(query: str) -> set[str]:
    """Extract lightweight keywords from a query."""
    return {term for term in re.findall(r"[a-zA-Z0-9]+", query.lower()) if len(term) >= 3}


def _document_keyword_score(doc: dict[str, Any], query_terms: set[str]) -> tuple[int, int]:
    """Score a document by keyword overlap in filename and metadata."""
    haystack = " ".join(
        str(doc.get(key, "")).lower()
        for key in ("filename", "type", "scope")
    )
    overlap = sum(1 for term in query_terms if term in haystack)
    return overlap, -len(doc.get("filename", ""))


def _collect_structure_ranges(nodes: list[dict[str, Any]], query_terms: set[str]) -> list[dict[str, Any]]:
    """Flatten structure nodes into ranked page-range candidates."""
    candidates: list[dict[str, Any]] = []

    def visit(items: list[dict[str, Any]]) -> None:
        for node in items:
            start = node.get("start_index")
            end = node.get("end_index") or start
            if isinstance(start, int):
                title = str(node.get("title", "")).lower()
                summary = str(node.get("summary", "")).lower()
                text = f"{title} {summary}"
                score = sum(1 for term in query_terms if term in text)
                page_range = str(start) if start == end or not isinstance(end, int) else f"{start}-{end}"
                candidates.append({
                    "page_range": page_range,
                    "score": score,
                    "span": (end - start) if isinstance(end, int) else 0,
                })
            child_nodes = node.get("nodes", [])
            if isinstance(child_nodes, list) and child_nodes:
                visit(child_nodes)

    visit(nodes)
    return sorted(candidates, key=lambda item: (item["score"], -item["span"]), reverse=True)
