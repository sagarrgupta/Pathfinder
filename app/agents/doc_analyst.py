"""Node 4: Doc Analyst.

Processes uploaded documents through the adaptive pipeline:
  1. Extract text (pypdf → vision fallback)
  2. Chunk the text
  3. Generate embeddings and store in Neo4j vector index
  4. Extract entities and store in Neo4j knowledge graph
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.adapters.embeddings.ollama import get_embeddings
from app.adapters.llm.lmstudio import get_text_llm
from app.adapters.neo4j.graph_store import (
    store_document_node,
    store_extracted_entities,
    update_document,
)
from app.adapters.neo4j.vector_store import store_chunks
from app.adapters.pdf.extractor import (
    extract_text_from_pdf,
    extract_text_from_image,
    extract_text_from_docx,
    get_file_type,
)
from app.config.settings import settings
from app.core.state import PathfinderState
from app.services.document_store import persist_uploaded_file
from app.services.retrieval import get_pageindex_client
from app.utils.ids import generate_document_id, generate_chunk_id

log = logging.getLogger("pathfinder.agents.doc_analyst")

_ENTITY_EXTRACTION_SYSTEM = (
    "You are a JSON entity extractor. You ALWAYS respond with a single JSON object and NOTHING else. "
    "No explanations, no markdown, no commentary — ONLY valid JSON."
)

_ENTITY_EXTRACTION_USER = '''Extract entities from the document below. Return ONLY this JSON structure:

{"entities":[{"label":"LABEL","properties":{"name":"VALUE"},"relationship":"REL"}],"student_properties":{"name":"","gpa":"","university":"","program":""}}

Label must be one of: Skill, Company, Project, Course, Goal, Interest, Department
Relationship must be one of: HAS_SKILL, WORKED_AT, COMPLETED, TOOK, HAS_GOAL, INTERESTED_IN, IN_DEPARTMENT

Extract as much grounded information as possible from resumes and transcripts, including:
- skills and technologies
- companies, job titles, and dates
- project names, descriptions, and technologies
- courses, grades, GPA, university, degree/program, email, and name
- goals or interests if explicitly stated

Example for a resume:
{"entities":[{"label":"Skill","properties":{"name":"Python","proficiency":"advanced"},"relationship":"HAS_SKILL"},{"label":"Company","properties":{"name":"Google","role":"Software Engineer","start_date":"2020","end_date":"2023"},"relationship":"WORKED_AT"},{"label":"Project","properties":{"name":"Search Optimizer","description":"Improved search ranking"},"relationship":"COMPLETED"}],"student_properties":{"name":"Jane Doe","university":"Stanford"}}

IMPORTANT: Output ONLY the JSON. No other text before or after it.

--- DOCUMENT START ---
'''


async def doc_analyst(state: PathfinderState) -> PathfinderState:
    """Process uploaded files: extract, chunk, embed, store."""
    files = state.get("files", [])
    session_id = state.get("session_id", "")
    student_id = state.get("student_id", "default")
    is_global = state.get("is_global_upload", False)
    scope = "global" if is_global else "session"

    step_progress = list(state.get("step_progress", []))
    all_entities: list[dict[str, Any]] = []
    total_chunks = 0

    if not files:
        step_progress.append("No files to process")
        return {**state, "step_progress": step_progress}

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    embeddings_model = get_embeddings()
    llm = get_text_llm()

    for file_info in files:
        filename = file_info.get("filename", "document.pdf")
        content = file_info.get("content", b"")

        step_progress.append(f"Processing {filename}...")
        doc_id = generate_document_id()

        # Step 1: Extract text (adaptive — route by file type)
        file_type = get_file_type(filename)
        if file_type == "pdf":
            pages = await extract_text_from_pdf(content, filename)
        elif file_type == "image":
            step_progress.append(f"Analyzing image with vision model...")
            pages = await extract_text_from_image(content, filename)
        elif file_type == "docx":
            pages = await extract_text_from_docx(content, filename)
        else:
            step_progress.append(f"Unsupported file type for {filename}, skipping")
            continue

        full_text = "\n\n".join(p["text"] for p in pages if p["text"])

        if not full_text.strip():
            step_progress.append(f"Could not extract text from {filename}")
            continue

        stored_file_path = persist_uploaded_file(
            document_id=doc_id,
            filename=filename,
            content=content,
            student_id=student_id,
        )

        # Step 2: Store document node
        await store_document_node(
            document_id=doc_id,
            filename=filename,
            scope=scope,
            student_id=student_id,
            session_id=session_id if scope == "session" else None,
            doc_type=file_type,
            file_path=stored_file_path,
        )

        if file_type == "pdf":
            try:
                step_progress.append(f"Preparing PageIndex for {filename}...")
                pageindex_client = get_pageindex_client(student_id)
                pageindex_doc_id = pageindex_client.index(stored_file_path)
                await update_document(doc_id, pageindex_doc_id=pageindex_doc_id)
                step_progress.append(f"PageIndex ready for {filename}")
            except Exception as exc:
                log.warning("PageIndex indexing failed for %s: %s", filename, exc)
                step_progress.append(f"PageIndex indexing skipped for {filename}")

        # Step 3: Chunk and embed
        text_chunks = text_splitter.split_text(full_text)
        chunk_texts = [c for c in text_chunks if c.strip()]

        if chunk_texts:
            chunk_embeddings = embeddings_model.embed_documents(chunk_texts)

            chunks_to_store = []
            for i, (text, embedding) in enumerate(zip(chunk_texts, chunk_embeddings)):
                chunks_to_store.append({
                    "id": generate_chunk_id(doc_id, i),
                    "text": text,
                    "embedding": embedding,
                    "chunk_index": i,
                    "page_number": _page_for_chunk(text, pages),
                })

            stored = await store_chunks(chunks_to_store, doc_id)
            total_chunks += stored
            step_progress.append(f"Stored {stored} text chunks from {filename}")

        # Step 4: Entity extraction
        step_progress.append(f"Extracting knowledge from {filename}...")
        try:
            parsed = await _extract_entities_from_document(llm, full_text, pages)
            entities = parsed.get("entities", [])
            student_props = parsed.get("student_properties", {})

            count = await store_extracted_entities(entities, doc_id, student_id)
            all_entities.extend(entities)
            step_progress.append(f"Extracted {count} entities from {filename}")

            if student_props:
                from app.adapters.neo4j.graph_store import update_student
                await update_student(student_id, **{k: v for k, v in student_props.items() if v})

        except Exception as exc:
            log.warning("Entity extraction failed for %s: %s", filename, exc)
            step_progress.append(f"Entity extraction partially failed for {filename}")

    step_progress.append(f"Document processing complete: {total_chunks} chunks, {len(all_entities)} entities")
    log.info("Doc analyst: %d chunks, %d entities", total_chunks, len(all_entities))

    return {
        **state,
        "files": [],  # Clear binary file data — no longer needed after processing
        "extracted_entities": all_entities,
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
    """Determine next node after document processing."""
    plan = state.get("plan", [])
    try:
        idx = plan.index("doc_analyst")
        if idx + 1 < len(plan):
            return plan[idx + 1]
    except ValueError:
        pass
    return "profile_manager"


async def _extract_entities_from_document(llm: Any, full_text: str, pages: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract entities across the full document instead of only the first 4k chars."""
    windows = _build_extraction_windows(full_text, pages)
    merged_entities: list[dict[str, Any]] = []
    merged_props: dict[str, str] = {}

    for window in windows:
        # Use string concatenation (NOT .format()) to avoid crashes when
        # document text contains braces like {Python, Java}.
        user_content = _ENTITY_EXTRACTION_USER + window + "\n--- DOCUMENT END ---"
        response = await llm.ainvoke([
            SystemMessage(content=_ENTITY_EXTRACTION_SYSTEM),
            HumanMessage(content=user_content),
        ])

        content_text = response.content if isinstance(response.content, str) else str(response.content)
        json_start = content_text.find("{")
        json_end = content_text.rfind("}") + 1
        if json_start < 0 or json_end <= json_start:
            continue

        parsed = json.loads(content_text[json_start:json_end])
        merged_entities.extend(parsed.get("entities", []))
        for key, value in parsed.get("student_properties", {}).items():
            if value and not merged_props.get(key):
                merged_props[key] = value

    return {
        "entities": _dedupe_entities(merged_entities),
        "student_properties": merged_props,
    }


def _build_extraction_windows(full_text: str, pages: list[dict[str, Any]]) -> list[str]:
    """Build page-aware windows for extraction so later resume sections are not ignored."""
    windows: list[str] = []
    page_blocks = []
    for page in pages:
        text = page.get("text", "").strip()
        if text:
            page_blocks.append(f"[PAGE {page.get('page', '?')}]\n{text}")

    if page_blocks:
        current = ""
        for block in page_blocks:
            candidate = f"{current}\n\n{block}".strip() if current else block
            if len(candidate) <= 3500:
                current = candidate
            else:
                if current:
                    windows.append(current)
                current = block
        if current:
            windows.append(current)
    else:
        for i in range(0, len(full_text), 3200):
            window = full_text[i:i + 3600].strip()
            if window:
                windows.append(window)

    return windows[:6]


def _dedupe_entities(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate extracted entities while keeping richer property sets."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    ordered: list[dict[str, Any]] = []

    for entity in entities:
        label = entity.get("label", "").strip()
        props = dict(entity.get("properties", {}))
        name = str(props.get("name", "")).strip().lower()
        if not label or not name:
            continue

        key = (label, name)
        if key not in merged:
            merged[key] = {
                "label": label,
                "properties": props,
                "relationship": entity.get("relationship", "HAS"),
            }
            ordered.append(merged[key])
            continue

        existing_props = merged[key]["properties"]
        for prop_key, prop_value in props.items():
            if prop_value and (not existing_props.get(prop_key) or len(str(prop_value)) > len(str(existing_props.get(prop_key, "")))):
                existing_props[prop_key] = prop_value

    return ordered
