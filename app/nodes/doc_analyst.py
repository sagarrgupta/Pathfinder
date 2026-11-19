"""Turns uploaded files (PDF / image / DOCX) into searchable graph data.

Called by `specialist_runner` when the user attaches files to a chat turn.
For each file we:
1. Extract text (and OCR images when needed) via `adapters/pdf/extractor`.
2. Split the text into overlapping chunks for vector retrieval.
3. Embed each chunk with Ollama and store chunks+embeddings in Neo4j.
4. Kick off the document ingestion agent (see `app.utils.document_ingest`)
   which reads those chunks and writes rich graph structure — sections,
   entities, fields, relations — tied back to the chunks as evidence.

Every step records any failure as a "processing_issue" instead of raising,
so a bad page or failed embed degrades gracefully (we still answer with
whatever we got) instead of aborting the whole turn.
"""

from __future__ import annotations

from enum import Enum
import logging
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.adapters.embeddings.ollama import EmbeddingServiceError, aembed_documents
from app.adapters.neo4j.graphDB import GraphDB
from app.adapters.neo4j.vectorDB import VectorDB
from app.adapters.pdf.extractor import extract_document_text, get_file_type
from app.config.settings import settings
from app.core.state import PathfinderState
from app.utils.document_ingest import ingest_document
from app.tools.graph_tools import get_driver as get_graph_driver
from app.utils.ids import generate_chunk_id, generate_document_id
from app.utils.progress import add_progress

log = logging.getLogger("pathfinder.nodes.doc_analyst")

_EXTRACTED_TEXT_PREVIEW_LIMIT = 12000

class ProcessingIssueType(str, Enum):
    """Labels for the four ways file processing can partially fail.

    Surfaced back to the UI via `state.processing_issues` so the user sees
    which file failed at which step instead of a generic error.
    """
    EXTRACTION_FAILED = "extraction_failed"
    EXTRACTION_EMPTY = "extraction_empty"
    EMBEDDING_FAILED = "embedding_failed"
    INGESTION_FAILED = "ingestion_failed"


async def doc_analyst(state: PathfinderState) -> PathfinderState:
    """Process every uploaded file end-to-end for this turn.

    Runs for each file in turn: extract -> chunk -> embed+store -> ingest
    structured knowledge. Returns the updated state with a cleared `files`
    list (so the same uploads are not reprocessed next turn) and a
    `latest_ingestion_result` summary for replay/debug.
    """
    files = state.get("files", [])
    files = list(files) if isinstance(files, list) else []
    student_id = state.get("student_id", "")
    query = str(state.get("query", "") or "")

    step_progress = list(state.get("step_progress", []))
    total_chunks = 0
    documents: list[dict[str, Any]] = []
    processing_issues = list(state.get("processing_issues", []))

    if not files:
        return {**state, "step_progress": step_progress}

    add_progress(
        step_progress,
        stage="Reading your uploaded files",
        message="Extracting details from the files you shared.",
    )

    # Splitter tries paragraph -> line -> sentence -> word boundaries so
    # chunks stop at natural breaks instead of cutting mid-sentence.
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    # One shared driver for both graph writes and vector writes — same
    # Neo4j instance hosts both.
    graph_driver = await get_graph_driver()
    graph_db = GraphDB(graph_driver)
    vector_db = VectorDB(
        graph_driver,
        index_name="chunk_embeddings",
        dimensions=int(settings.EMBEDDING_DIMENSIONS),
    )
    for file_info in files:
        if not isinstance(file_info, dict):
            continue
        filename = file_info.get("filename", "document.pdf")
        content = file_info.get("content", b"")

        doc_id = generate_document_id()

        # Reject unknown file types up front rather than halfway through.
        file_type = get_file_type(filename)
        if file_type not in {"pdf", "image", "docx"}:
            continue

        try:
            if file_type == "image":
                add_progress(
                    step_progress,
                    stage="Reading your uploaded files",
                    message="Analyzing an uploaded image for text and details.",
                )
            pages = await extract_document_text(file_type, content, filename)
        except Exception as exc:
            log.warning("Document extraction failed for %s: %s", filename, exc)
            processing_issues.append(
                {
                    "type": ProcessingIssueType.EXTRACTION_FAILED.value,
                    "status": "degraded",
                    "reason": "Document text extraction failed, so this file was skipped.",
                    "filename": filename,
                    "file_type": file_type,
                    "error": str(exc),
                }
            )
            continue

        # Flatten pages into a single document-level string. We keep page
        # boundaries tracked separately via `_build_page_locator` so each
        # chunk can still report which page it came from.
        full_text = "\n\n".join(page["text"] for page in pages if page["text"])
        if not full_text.strip():
            processing_issues.append(
                {
                    "type": ProcessingIssueType.EXTRACTION_EMPTY.value,
                    "status": "degraded",
                    "reason": "No usable text could be extracted from the file.",
                    "filename": filename,
                    "file_type": file_type,
                }
            )
            continue

        # Summary we will return per file; filled in as we make progress.
        document_result: dict[str, Any] = {
            "document_id": doc_id,
            "filename": filename,
            "file_type": file_type,
            "page_count": len(pages),
            "text_preview": full_text[:_EXTRACTED_TEXT_PREVIEW_LIMIT],
            "chunks_stored": 0,
        }
        # Register the document node first so chunks have a parent to attach to.
        await graph_db.create_document(
            student_id=student_id,
            document_id=doc_id,
            filename=filename,
            file_type=file_type,
        )
        # Chunk the text and remember which page each chunk came from.
        text_chunks = text_splitter.split_text(full_text)
        page_for_chunk = _build_page_locator(full_text, pages)
        chunk_specs = [
            {
                "text": text,
                "chunk_index": index,
                "page_number": page_for_chunk(text),
            }
            for index, text in enumerate(text_chunks)
            if text.strip()
        ]
        # `prompt_chunks` is the compact view passed to the ingestion agent
        # so it can reference chunks by id when grounding graph entities.
        prompt_chunks: list[dict[str, Any]] = []
        if chunk_specs:
            try:
                # Embed all chunks in one batched Ollama call for throughput.
                chunk_texts = [chunk["text"] for chunk in chunk_specs]
                chunk_embeddings = await aembed_documents(chunk_texts)
                chunks_to_store = []
                for chunk_spec, embedding in zip(chunk_specs, chunk_embeddings):
                    chunk_id = generate_chunk_id(doc_id, int(chunk_spec["chunk_index"]))
                    chunks_to_store.append(
                        {
                            "id": chunk_id,
                            "text": chunk_spec["text"],
                            "embedding": embedding,
                            "chunk_index": int(chunk_spec["chunk_index"]),
                            "page_number": chunk_spec.get("page_number"),
                        }
                    )
                    prompt_chunks.append(
                        {
                            "chunk_id": chunk_id,
                            "chunk_index": int(chunk_spec["chunk_index"]),
                            "page_number": chunk_spec.get("page_number"),
                            "text": chunk_spec["text"],
                        }
                    )

                # Single round-trip to Neo4j for all chunks of this doc.
                stored_result = await vector_db.batch_upsert_chunks(student_id=student_id, document_id=doc_id, chunks=chunks_to_store)
                stored = int(stored_result.get("stored_chunks", 0) or 0)
                total_chunks += stored
                document_result["chunks_stored"] = stored
            except EmbeddingServiceError as exc:
                log.warning("Chunk embedding/storage failed for %s: %s", filename, exc)
                prompt_chunks = []
                processing_issues.append(
                    {
                        "type": ProcessingIssueType.EMBEDDING_FAILED.value,
                        "status": "degraded",
                        "reason": "Chunk embedding or storage failed, so vector retrieval is unavailable for this file.",
                        "filename": filename,
                        "error": str(exc),
                    }
                )

        # Now the chunks exist and are searchable; let the ingestion agent
        # turn the document into structured graph knowledge grounded in
        # those chunks.
        try:
            applied = await ingest_document(
                student_id=student_id,
                session_id=None,
                document_id=doc_id,
                query=query,
                filename=filename,
                file_type=file_type,
                full_text=full_text,
                chunks=prompt_chunks,
                step_progress=step_progress,
            )
            ingestion_result = {
                "tool_call_log": list(applied.get("tool_call_log", []) or []),
                "model_summary": dict(applied.get("model_summary") or {}),
                "graph_updates": dict(applied.get("graph_updates") or {}),
                "graph_schema_after": dict(applied.get("graph_schema_after") or {}),
            }
            document_result["ingestion_result"] = ingestion_result
            graph_updates = dict(ingestion_result.get("graph_updates") or {})
            counts = dict(graph_updates.get("counts") or {})
        except Exception as exc:
            log.warning("Structured ingestion failed for %s: %s", filename, exc)
            processing_issues.append(
                {
                    "type": ProcessingIssueType.INGESTION_FAILED.value,
                    "status": "degraded",
                    "reason": "Structured ingestion failed, so graph enrichment was skipped for this file.",
                    "filename": filename,
                    "error": str(exc),
                }
            )

        documents.append(document_result)
    add_progress(
        step_progress,
        stage="Working on your answer",
        message="Using the extracted details to improve the response.",
    )
    log.info("Doc analyst: %d chunks across %d documents", total_chunks, len(documents))

    # Clear `files` so the same uploads aren't reprocessed on the next turn.
    return {
        **state,
        "files": [],
        "latest_ingestion_result": {
            "documents": documents,
        },
        "processing_issues": processing_issues,
        "step_progress": step_progress,
    }


def _build_page_locator(full_text: str, pages: list[dict[str, Any]]):
    """Return a closure that maps a chunk of text back to its page number.

    We precompute `(start, end, page)` offsets for each page inside the
    joined `full_text`, then search each chunk's first 80 chars inside
    that text. Using a moving cursor (`search_start`) keeps later chunks
    from accidentally matching an earlier identical phrase, which matters
    for documents that repeat headings on every page.
    """
    page_ranges: list[tuple[int, int, int | None]] = []
    cursor = 0
    separator_len = len("\n\n")
    for page in pages:
        text = str(page.get("text", "") or "")
        start = cursor
        end = start + len(text)
        page_ranges.append((start, end, page.get("page")))
        cursor = end + separator_len

    search_start = 0
    current_page_index = 0

    def locate(chunk_text: str) -> int | None:
        nonlocal search_start, current_page_index
        snippet = str(chunk_text or "").strip()[:80].strip()
        if not snippet or not page_ranges:
            return None

        position = full_text.find(snippet, search_start)
        if position == -1 and search_start > 0:
            position = full_text.find(snippet)
        if position == -1:
            return None

        search_start = max(search_start, position + len(snippet))
        while (
            current_page_index < len(page_ranges) - 1
            and position > page_ranges[current_page_index][1]
        ):
            current_page_index += 1
        return page_ranges[current_page_index][2]

    return locate
