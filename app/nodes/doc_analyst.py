"""Document ingestion node for uploaded files."""

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

log = logging.getLogger("pathfinder.nodes.doc_analyst")

_EXTRACTED_TEXT_PREVIEW_LIMIT = 12000


class ProcessingIssueType(str, Enum):
    EXTRACTION_FAILED = "extraction_failed"
    EXTRACTION_EMPTY = "extraction_empty"
    EMBEDDING_FAILED = "embedding_failed"
    INGESTION_FAILED = "ingestion_failed"


async def doc_analyst(state: PathfinderState) -> PathfinderState:
    """Extract, chunk, store, and ingest uploaded files."""
    files = state.get("files", [])
    files = list(files) if isinstance(files, list) else []
    student_id = state.get("student_id", "")
    query = str(state.get("query", "") or "")

    step_progress = list(state.get("step_progress", []))
    total_chunks = 0
    documents: list[dict[str, Any]] = []
    processing_issues = list(state.get("processing_issues", []))

    if not files:
        step_progress.append("No files to process")
        return {**state, "step_progress": step_progress}

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
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

        step_progress.append(f"Processing {filename}...")
        doc_id = generate_document_id()

        file_type = get_file_type(filename)
        if file_type not in {"pdf", "image", "docx"}:
            step_progress.append(f"Unsupported file type for {filename}, skipping")
            continue

        try:
            if file_type == "image":
                step_progress.append("Analyzing image with vision model...")
            pages = await extract_document_text(file_type, content, filename)
        except Exception as exc:
            log.warning("Document extraction failed for %s: %s", filename, exc)
            step_progress.append(f"Could not fully extract text from {filename}; skipping this file")
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

        full_text = "\n\n".join(page["text"] for page in pages if page["text"])
        if not full_text.strip():
            step_progress.append(f"Could not extract text from {filename}")
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

        document_result: dict[str, Any] = {
            "document_id": doc_id,
            "filename": filename,
            "file_type": file_type,
            "page_count": len(pages),
            "text_preview": full_text[:_EXTRACTED_TEXT_PREVIEW_LIMIT],
            "chunks_stored": 0,
        }

        await graph_db.create_document(
            student_id=student_id,
            document_id=doc_id,
            filename=filename,
            file_type=file_type,
        )

        text_chunks = text_splitter.split_text(full_text)
        chunk_specs = [
            {
                "text": text,
                "chunk_index": index,
                "page_number": _page_for_chunk(text, pages),
            }
            for index, text in enumerate(text_chunks)
            if text.strip()
        ]

        prompt_chunks: list[dict[str, Any]] = []
        if chunk_specs:
            try:
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

                stored_result = await vector_db.batch_upsert_chunks(document_id=doc_id, chunks=chunks_to_store)
                stored = int(stored_result.get("stored_chunks", 0) or 0)
                total_chunks += stored
                document_result["chunks_stored"] = stored
                step_progress.append(f"Stored {stored} text chunks from {filename}")
            except EmbeddingServiceError as exc:
                log.warning("Chunk embedding/storage failed for %s: %s", filename, exc)
                prompt_chunks = []
                step_progress.append(f"Stored document metadata for {filename}, but chunk retrieval failed")
                processing_issues.append(
                    {
                        "type": ProcessingIssueType.EMBEDDING_FAILED.value,
                        "status": "degraded",
                        "reason": "Chunk embedding or storage failed, so vector retrieval is unavailable for this file.",
                        "filename": filename,
                        "error": str(exc),
                    }
                )

        step_progress.append(f"Extracting structured knowledge from {filename}...")
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
            step_progress.append(
                f"Applied ingestion agent for {filename}: "
                f"{len(list(graph_updates.get('sections_touched', []) or []))} sections, "
                f"{int(counts.get('entities_written', 0) or 0)} nodes, "
                f"{int(counts.get('relationships_written', 0) or 0)} relationships"
            )
        except Exception as exc:
            log.warning("Structured ingestion failed for %s: %s", filename, exc)
            step_progress.append(f"Structured ingestion partially failed for {filename}")
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

    step_progress.append(
        f"Document processing complete: {total_chunks} chunks across {len(documents)} document(s)"
    )
    log.info("Doc analyst: %d chunks across %d documents", total_chunks, len(documents))

    return {
        **state,
        "files": [],
        "latest_ingestion_result": {
            "documents": documents,
        },
        "processing_issues": processing_issues,
        "step_progress": step_progress,
    }


def _page_for_chunk(chunk_text: str, pages: list[dict]) -> int | None:
    """Find which page a chunk came from (best effort)."""
    for page in pages:
        if chunk_text[:50] in str(page.get("text", "") or ""):
            return page.get("page")
    return None
