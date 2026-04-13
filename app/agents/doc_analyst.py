"""Node 4: Doc Analyst.

Processes uploaded documents through the adaptive pipeline:
  1. Extract text (pypdf -> vision fallback)
  2. Chunk the text
  3. Generate embeddings and store in Neo4j vector index
  4. Extract entities and store in Neo4j knowledge graph
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.adapters.embeddings.ollama import EmbeddingServiceError, aembed_documents
from app.adapters.neo4j.graph_store import (
    store_document_node,
    store_evidence,
)
from app.adapters.neo4j.vector_store import store_chunks
from app.adapters.pdf.extractor import get_file_type
from app.config.settings import settings
from app.core.state import PathfinderState
from app.services.execution_registry import execute_document_ingestion
from app.services.document_roles import infer_document_role
from app.services.document_ingestion import execute_document_ingestion_agent
from app.services.transcript_state import build_transcript_state
from app.services.runtime_recovery import (
    recovery_for_document_embedding_failure,
    recovery_for_document_extraction_failure,
    recovery_for_empty_document_extraction,
    recovery_for_entity_extraction_failure,
)
from app.utils.ids import generate_document_id, generate_chunk_id

log = logging.getLogger("pathfinder.agents.doc_analyst")

_EXTRACTED_TEXT_PREVIEW_LIMIT = 12000


async def doc_analyst(state: PathfinderState) -> PathfinderState:
    """Process uploaded files: extract, chunk, embed, store."""
    files = state.get("files", [])
    files = list(files) if isinstance(files, list) else []
    student_id = state.get("student_id", "")
    query = str(state.get("query", "") or "")

    step_progress = list(state.get("step_progress", []))
    all_entities: list[dict[str, Any]] = []
    all_relationships: list[dict[str, Any]] = []
    all_candidate_facts: list[dict[str, Any]] = []
    all_memory_items: list[dict[str, Any]] = []
    all_promoted_entities: list[dict[str, Any]] = []
    total_chunks = 0
    document_roles: list[dict[str, Any]] = []
    transcript_states: list[dict[str, Any]] = []
    extracted_documents: list[dict[str, Any]] = []
    patch_summaries: list[dict[str, Any]] = []
    recovery_events = list(state.get("recovery_events", []))

    if not files:
        step_progress.append("No files to process")
        return {**state, "step_progress": step_progress}

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    for file_info in files:
        if not isinstance(file_info, dict):
            continue
        filename = file_info.get("filename", "document.pdf")
        content = file_info.get("content", b"")

        step_progress.append(f"Processing {filename}...")
        doc_id = generate_document_id()

        # Step 1: Extract text (adaptive — route by file type)
        file_type = get_file_type(filename)
        if file_type in {"pdf", "image", "docx"}:
            try:
                if file_type == "image":
                    step_progress.append(f"Analyzing image with vision model...")
                pages = await execute_document_ingestion(file_type, content, filename)
            except Exception as exc:
                log.warning("Document extraction failed for %s: %s", filename, exc)
                step_progress.append(f"Could not fully extract text from {filename}; skipping this file")
                recovery_events.append(
                    recovery_for_document_extraction_failure(filename, file_type, str(exc)).as_dict()
                )
                continue
        else:
            step_progress.append(f"Unsupported file type for {filename}, skipping")
            continue

        full_text = "\n\n".join(p["text"] for p in pages if p["text"])

        if not full_text.strip():
            step_progress.append(f"Could not extract text from {filename}")
            recovery_events.append(
                recovery_for_empty_document_extraction(filename, file_type).as_dict()
            )
            continue

        inferred_role = infer_document_role(filename, full_text, file_type=file_type)
        extracted_documents.append({
            "document_id": doc_id,
            "filename": filename,
            "file_type": file_type,
            "role": inferred_role.get("role", "general_document"),
            "page_count": len(pages),
            "text_preview": full_text[:_EXTRACTED_TEXT_PREVIEW_LIMIT],
        })
        document_roles.append({
            "document_id": doc_id,
            "filename": filename,
            **inferred_role,
        })
        step_progress.append(
            f"Inferred {inferred_role.get('role', 'general_document')} role for {filename}"
        )

        if inferred_role.get("role") == "transcript":
            transcript_state = build_transcript_state(full_text, filename)
            transcript_states.append({
                "document_id": doc_id,
                "filename": filename,
                "role": "transcript",
                "state": transcript_state,
            })
            step_progress.append(
                f"Built transcript state for {filename}: "
                f"{len(transcript_state.get('completed_courses', []))} completed, "
                f"{len(transcript_state.get('planned_courses', []))} planned, "
                f"{len(transcript_state.get('milestones', []))} milestones"
            )

        # Step 2: Store document node
        await store_document_node(
            document_id=doc_id,
            filename=filename,
            student_id=student_id,
            doc_type=inferred_role.get("role", "general_document"),
            file_type=file_type,
            document_role=inferred_role.get("role", "general_document"),
            role_confidence=float(inferred_role.get("confidence", 0.0) or 0.0),
            role_signals=(
                list(inferred_role.get("signals", []) or [])
                if isinstance(inferred_role.get("signals", []), list)
                else []
            ),
        )
        if inferred_role.get("role") == "transcript":
            await store_evidence(
                student_id=student_id,
                source_type="transcript_state",
                content=json.dumps(transcript_states[-1]["state"], ensure_ascii=True),
                source_ref=f"doc:{doc_id}",
                session_id=None,
                metadata={
                    "document_id": doc_id,
                    "filename": filename,
                    "document_role": "transcript",
                    "summary": transcript_states[-1]["state"].get("summary", {}),
                },
            )

        # Step 3: Chunk and embed
        text_chunks = text_splitter.split_text(full_text)
        chunk_specs = [
            {
                "text": text,
                "chunk_index": i,
                "page_number": _page_for_chunk(text, pages),
            }
            for i, text in enumerate(text_chunks)
            if text.strip()
        ]

        if chunk_specs:
            try:
                chunk_texts = [chunk["text"] for chunk in chunk_specs]
                chunk_embeddings = await aembed_documents(chunk_texts)

                chunks_to_store = []
                for chunk_spec, embedding in zip(chunk_specs, chunk_embeddings):
                    chunks_to_store.append({
                        "id": generate_chunk_id(doc_id, int(chunk_spec["chunk_index"])),
                        "text": chunk_spec["text"],
                        "embedding": embedding,
                        "chunk_index": int(chunk_spec["chunk_index"]),
                        "page_number": chunk_spec.get("page_number"),
                    })

                stored = await store_chunks(chunks_to_store, doc_id)
                total_chunks += stored
                step_progress.append(f"Stored {stored} text chunks from {filename}")
            except EmbeddingServiceError as exc:
                log.warning("Chunk embedding/storage failed for %s: %s", filename, exc)
                step_progress.append(f"Stored document metadata for {filename}, but chunk retrieval failed")
                recovery_events.append(
                    recovery_for_document_embedding_failure(filename, str(exc)).as_dict()
                )

        # Step 4: Rich ingestion patch extraction and application
        step_progress.append(f"Extracting structured knowledge from {filename}...")
        try:
            applied = await execute_document_ingestion_agent(
                student_id=student_id,
                session_id=None,
                document_id=doc_id,
                query=query,
                filename=filename,
                document_role=inferred_role.get("role", "general_document"),
                file_type=file_type,
                full_text=full_text,
            )
            profile_summary = applied.get("profile_summary", {}) if isinstance(applied.get("profile_summary", {}), dict) else {}
            schema_sections = list((profile_summary.get("profile_schema", {}) or {}).get("sections", []) or [])
            tool_log = list(applied.get("tool_call_log", []) or [])
            entity_count = sum(
                1
                for item in tool_log
                if isinstance(item, dict)
                and item.get("status") == "ok"
                and item.get("tool") in {"upsert_graph_node", "graph_add_node", "graph_update_node"}
            )
            relationship_count = sum(
                1
                for item in tool_log
                if isinstance(item, dict)
                and item.get("status") == "ok"
                and item.get("tool") in {"upsert_graph_relation", "graph_add_relation", "graph_update_relation"}
            )
            candidate_fact_count = sum(
                1
                for item in tool_log
                if isinstance(item, dict)
                and item.get("status") == "ok"
                and item.get("tool") == "add_or_update_fact"
            )
            support_record_count = candidate_fact_count
            schema_section_count = sum(
                1
                for item in tool_log
                if isinstance(item, dict)
                and item.get("status") == "ok"
                and item.get("tool") == "upsert_profile_schema_section"
            )
            all_entities.extend([{}] * entity_count)
            all_relationships.extend([{}] * relationship_count)
            all_candidate_facts.extend([{}] * candidate_fact_count)
            patch_summaries.append(
                {
                    "document_id": doc_id,
                    "filename": filename,
                    "tool_calls": tool_log,
                    "agent_result": applied.get("final_payload", {}),
                    "saved_items": applied.get("saved_items", []),
                    "summary": applied.get("summary", ""),
                    "stop_reason": applied.get("stop_reason", ""),
                    "profile_snapshot": profile_summary,
                    "context_updates": applied.get("context_updates", {}),
                    "schema_sections": schema_sections,
                    "schema_section_count": schema_section_count or len(schema_sections),
                    "entity_count": entity_count,
                    "relationship_count": relationship_count,
                    "support_record_count": support_record_count,
                    "candidate_fact_count": candidate_fact_count,
                    "memory_item_count": 0,
                    "promoted_entity_count": 0,
                }
            )
            step_progress.append(
                f"Applied ingestion agent for {filename}: "
                f"{schema_section_count or len(schema_sections)} schema sections, "
                f"{entity_count} nodes, {relationship_count} relationships"
            )
        except Exception as exc:
            log.warning("Structured ingestion failed for %s: %s", filename, exc)
            step_progress.append(f"Structured ingestion partially failed for {filename}")
            recovery_events.append(
                recovery_for_entity_extraction_failure(filename, str(exc)).as_dict()
            )

    step_progress.append(
        f"Document processing complete: {total_chunks} chunks, {len(all_entities)} entities, "
        f"{len(all_relationships)} relationships"
    )
    log.info(
        "Doc analyst: %d chunks, %d entities, %d relationships",
        total_chunks,
        len(all_entities),
        len(all_relationships),
    )

    return {
        **state,
        "files": [],  # Clear binary file data — no longer needed after processing
        "extracted_entities": all_entities,
        "document_roles": document_roles,
        "transcript_states": transcript_states,
        "latest_ingestion_result": {
            "documents": extracted_documents,
            "chunk_count": total_chunks,
            "entity_count": len(all_entities),
            "relationship_count": len(all_relationships),
            "support_record_count": len(all_candidate_facts) + len(all_memory_items),
            "candidate_fact_count": len(all_candidate_facts),
            "memory_item_count": len(all_memory_items),
            "promoted_entity_count": len(all_promoted_entities),
            "patch_summaries": patch_summaries,
        },
        "recovery_events": recovery_events,
        "step_progress": step_progress,
        "next_node": _determine_next(state),
    }


def _page_for_chunk(chunk_text: str, pages: list[dict]) -> int | None:
    """Find which page a chunk came from (best effort)."""
    for page in pages:
        if chunk_text[:50] in page.get("text", ""):
            return page.get("page")
    return None


def _determine_next(state: PathfinderState) -> str:
    """Document processing is now a leaf pre-ingestion step."""
    return "responder"
