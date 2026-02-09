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

        # Step 2: Store document node
        await store_document_node(
            document_id=doc_id,
            filename=filename,
            scope=scope,
            student_id=student_id,
            session_id=session_id if scope == "session" else None,
        )

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
            # Use string concatenation (NOT .format()) to avoid crashes
            # when the resume text contains curly braces like {Python, Java}
            user_content = _ENTITY_EXTRACTION_USER + full_text[:4000] + "\n--- DOCUMENT END ---"
            response = await llm.ainvoke([
                SystemMessage(content=_ENTITY_EXTRACTION_SYSTEM),
                HumanMessage(content=user_content),
            ])

            content_text = response.content if isinstance(response.content, str) else str(response.content)

            json_start = content_text.find("{")
            json_end = content_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                parsed = json.loads(content_text[json_start:json_end])
                entities = parsed.get("entities", [])
                student_props = parsed.get("student_properties", {})

                # Store entities in KG
                count = await store_extracted_entities(entities, doc_id, student_id)
                all_entities.extend(entities)
                step_progress.append(f"Extracted {count} entities from {filename}")

                # Update student properties if found
                if student_props:
                    from app.adapters.neo4j.graph_store import update_student
                    await update_student(student_id, **{k: v for k, v in student_props.items() if v})
            else:
                step_progress.append(f"Could not parse entities from {filename}")

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
