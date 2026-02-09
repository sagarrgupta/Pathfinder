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
from app.adapters.pdf.extractor import extract_text_from_pdf
from app.config.settings import settings
from app.core.state import PathfinderState
from app.utils.ids import generate_document_id, generate_chunk_id

log = logging.getLogger("pathfinder.agents.doc_analyst")

_ENTITY_EXTRACTION_PROMPT = """You are an entity extraction specialist. Extract structured entities from the following document text.

For each entity, provide:
- label: one of [Course, Skill, Company, Goal, Interest, Project, Department]
- properties: a dict with at least "name" and any other relevant fields
- relationship: one of [TOOK, HAS_SKILL, WORKED_AT, HAS_GOAL, INTERESTED_IN, COMPLETED, IN_DEPARTMENT]

Also extract student-level properties if found: name, gpa, university, program, semester.

Respond with valid JSON:
{{
    "entities": [
        {{"label": "Course", "properties": {{"name": "CSC 200", "code": "CSC200", "grade": "A"}}, "relationship": "TOOK"}},
        {{"label": "Skill", "properties": {{"name": "Python", "proficiency": "advanced"}}, "relationship": "HAS_SKILL"}}
    ],
    "student_properties": {{"name": "John", "gpa": "3.5", "university": "CSUS"}}
}}

Document text:
{text}
"""


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

        # Step 1: Extract text (adaptive)
        pages = await extract_text_from_pdf(content, filename)
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
            # #region agent log
            _log_path = "/Users/sagargupta/Library/CloudStorage/OneDrive-CaliforniaStateUniversity,Sacramento/Courses/CSC-500-Master's Project/Implementation-code copy/.cursor/debug.log"
            import json as _json, time as _time
            with open(_log_path, "a") as _f:
                _f.write(_json.dumps({"location": "doc_analyst.py:entity_extract_start", "message": "Starting entity extraction", "data": {"filename": filename, "text_length": len(full_text), "text_preview": full_text[:500]}, "hypothesisId": "C", "timestamp": _time.time()}) + "\n")
            # #endregion

            response = await llm.ainvoke([
                SystemMessage(content="You are an entity extraction specialist."),
                HumanMessage(content=_ENTITY_EXTRACTION_PROMPT.format(text=full_text[:4000])),
            ])

            content_text = response.content if isinstance(response.content, str) else str(response.content)

            # #region agent log
            with open(_log_path, "a") as _f:
                _f.write(_json.dumps({"location": "doc_analyst.py:llm_response", "message": "LLM entity extraction response", "data": {"response_length": len(content_text), "response_preview": content_text[:800]}, "hypothesisId": "C", "timestamp": _time.time()}) + "\n")
            # #endregion

            json_start = content_text.find("{")
            json_end = content_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                parsed = json.loads(content_text[json_start:json_end])
                entities = parsed.get("entities", [])
                student_props = parsed.get("student_properties", {})

                # #region agent log
                with open(_log_path, "a") as _f:
                    _f.write(_json.dumps({"location": "doc_analyst.py:parsed_entities", "message": "Parsed entities", "data": {"entity_count": len(entities), "student_props": student_props, "entities_preview": entities[:3]}, "hypothesisId": "C", "timestamp": _time.time()}) + "\n")
                # #endregion

                # Store entities in KG
                count = await store_extracted_entities(entities, doc_id, student_id)
                all_entities.extend(entities)
                step_progress.append(f"Extracted {count} entities from {filename}")

                # Update student properties if found
                if student_props:
                    from app.adapters.neo4j.graph_store import update_student
                    await update_student(student_id, **{k: v for k, v in student_props.items() if v})
            else:
                # #region agent log
                with open(_log_path, "a") as _f:
                    _f.write(_json.dumps({"location": "doc_analyst.py:no_json", "message": "No JSON found in LLM response", "data": {"response": content_text[:500]}, "hypothesisId": "C", "timestamp": _time.time()}) + "\n")
                # #endregion
                step_progress.append(f"Could not parse entities from {filename}")

        except Exception as exc:
            # #region agent log
            import traceback
            with open(_log_path, "a") as _f:
                _f.write(_json.dumps({"location": "doc_analyst.py:entity_error", "message": "Entity extraction exception", "data": {"error": str(exc), "traceback": traceback.format_exc()}, "hypothesisId": "C", "timestamp": _time.time()}) + "\n")
            # #endregion
            log.warning("Entity extraction failed for %s: %s", filename, exc)
            step_progress.append(f"Entity extraction partially failed for {filename}")

    step_progress.append(f"Document processing complete: {total_chunks} chunks, {len(all_entities)} entities")
    log.info("Doc analyst: %d chunks, %d entities", total_chunks, len(all_entities))

    return {
        **state,
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
