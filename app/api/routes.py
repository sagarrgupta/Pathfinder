"""API endpoints for Pathfinder.

All routes prefixed with /api/v1 (set in main.py).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from app.adapters.neo4j.graphDB import GraphDB
from app.config.settings import settings
from app.core.graph import get_compiled_graph
from app.core.memory import reset_checkpointer_storage
from app.services.runtime_session import build_chat_runtime_session, get_dependency_status
from app.services.long_context import build_long_context_payload, normalize_long_context_summary
from app.services.execution_registry import get_active_retrieval_strategy, get_active_text_model
from app.services.replay_store import (
    build_replay_artifact,
    delete_all_replay_artifacts,
    delete_replay_artifacts_for_student,
    get_replay_artifact,
    list_replay_artifacts,
    save_replay_artifact,
)
from app.schemas.models import (
    ChatResponse,
    DocumentUploadResponse,
    GraphDataResponse,
    HealthResponse,
    StudentCreate,
    StudentInfo,
    StudentResponse,
    StudentUpdate,
    ReplayArtifactInfo,
    SessionInfo,
    SettingsResponse,
    SettingsUpdate,
)
from app.tools.graph_tools import get_driver as get_graph_driver
from app.utils.ids import generate_session_id, generate_student_id

log = logging.getLogger("pathfinder.api")

router = APIRouter()

def _student_info(student: dict[str, Any]) -> StudentInfo:
    """Normalize a raw student record into the API response shape."""
    extra = {
        k: v for k, v in student.items()
        if k not in {"id", "name", "created_at", "updated_at", "completeness",
                      "long_context_summary", "long_context_notes"}
        and v is not None and str(v).strip()
    }
    return StudentInfo(
        student_id=student.get("id", ""),
        name=student.get("name", "Student"),
        created_at=student.get("created_at"),
        updated_at=student.get("updated_at"),
        completeness=float(student.get("completeness", 0.0) or 0.0),
        **extra,
    )


async def _graph_db() -> GraphDB:
    return GraphDB(await get_graph_driver())


async def _ensure_student(student_id: str) -> dict[str, Any]:
    return await (await _graph_db()).update_student(student_id=student_id, updates={})



def _parse_replace_filenames(value: str) -> set[str]:
    """Parse a comma-separated replacement list into unique filenames."""
    return {name.strip() for name in value.split(",") if name.strip()}


def _validate_upload_filename(filename: str | None) -> str:
    """Validate that an uploaded filename exists and matches allowed types."""
    if not filename:
        raise HTTPException(400, "Filename is required")
    ext = os.path.splitext(filename)[1].lower()
    if ext not in settings.ALLOWED_FILE_TYPES:
        allowed = ", ".join(settings.ALLOWED_FILE_TYPES)
        raise HTTPException(400, f"Unsupported file type '{ext}'. Allowed: {allowed}")
    return filename


def _enforce_upload_size(content: bytes, *, filename: str) -> None:
    """Reject uploads larger than the configured file-size limit."""
    if len(content) > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(413, f"File {filename} exceeds {settings.MAX_FILE_SIZE_MB}MB limit")


async def _read_upload_file(file: UploadFile) -> dict[str, Any]:
    """Read and validate one FastAPI uploaded file."""
    filename = _validate_upload_filename(file.filename)
    content = await file.read()
    _enforce_upload_size(content, filename=filename)
    return {
        "filename": filename,
        "content": content,
        "size": len(content),
        "content_type": file.content_type,
    }


# ── Runtime state ────────────────────────────────────────────────
_topic_guard_enabled: bool = settings.TOPIC_GUARD_ENABLED
_reasoning: str = "medium"


# ── Chat (SSE Streaming) ────────────────────────────────────────


@router.post("/chat")
async def chat(
    query: str = Form(...),
    session_id: Optional[str] = Form(None),
    student_id: Optional[str] = Form(None),
    files: list[UploadFile] = File(default=[]),
    replace_filenames: str = Form(""),
    reasoning: str = Form("medium"),
):
    """Main chat endpoint with SSE streaming."""
    resolved_student_id = await _resolve_student_id(student_id)
    if not session_id:
        session_id = generate_session_id()
    files = list(files) if isinstance(files, list) else []

    # Parse replace filenames (comma-separated list of filenames to replace)
    replace_set = _parse_replace_filenames(replace_filenames)

    # Delete existing documents that are being replaced
    for fname in replace_set:
        existing = await (await _graph_db()).find_document_by_filename(
            student_id=resolved_student_id,
            filename=fname,
        )
        if existing and existing.get("id"):
            await (await _graph_db()).delete_document_cascade(document_id=existing["id"])
            log.info("Chat: replaced existing document before re-upload: %s", fname)

    # Read uploaded files
    file_data = [await _read_upload_file(upload) for upload in files]

    async def event_stream():
        try:
            graph = await get_compiled_graph()
            runtime_session = await build_chat_runtime_session(
                query=query,
                session_id=session_id,
                student_id=resolved_student_id,
                files=file_data,
                topic_guard_enabled=_topic_guard_enabled,
                reasoning=(reasoning if str(reasoning or "").strip() else _reasoning),
            )
            initial_state = runtime_session.build_initial_state()
            config = runtime_session.build_graph_config()

            # Stream graph execution
            last_progress_count = 0
            final_state = {}

            async for event in graph.astream(initial_state, config=config):
                # event is a dict {node_name: state_update}
                for node_name, state_update in event.items():
                    final_state.update(state_update)

                    # Emit new progress messages
                    progress = state_update.get("step_progress", [])
                    if len(progress) > last_progress_count:
                        for msg in progress[last_progress_count:]:
                            yield f"event: progress\ndata: {json.dumps({'node': node_name, 'message': msg})}\n\n"
                        last_progress_count = len(progress)

            # Emit final answer
            final_answer = final_state.get("final_answer", "I couldn't generate a response.")

            # Stream tokens (simulate word-by-word for UX)
            words = final_answer.split(" ")
            for word in words:
                yield f"event: token\ndata: {json.dumps({'content': word + ' '})}\n\n"

            # Done event
            done_payload = runtime_session.build_done_payload(final_state)
            try:
                artifact = build_replay_artifact(
                    query=query,
                    done_payload=done_payload,
                    final_state=final_state,
                    student_id=resolved_student_id,
                    session_id=session_id,
                )
                saved_artifact = save_replay_artifact(artifact)
                done_payload["replay_id"] = saved_artifact.get("id", "")
            except Exception as exc:
                log.warning("Failed to persist replay artifact for session %s: %s", session_id, exc)
            yield f"event: done\ndata: {json.dumps(done_payload)}\n\n"

        except Exception as exc:
            log.error("Chat error: %s", exc, exc_info=True)
            yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/students", response_model=list[StudentInfo])
async def get_students():
    """List local students."""
    driver = await get_graph_driver()
    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (s:Student)
            RETURN s {.*} AS student
            ORDER BY coalesce(s.updated_at, s.created_at) DESC
            """
        )
        students = [dict(record["student"]) async for record in result]
    return [_student_info(student) for student in students]


@router.post("/students", response_model=StudentInfo)
async def create_student(body: StudentCreate):
    """Create a new local student."""
    extra = body.model_extra or {}
    student_id = generate_student_id()
    await _ensure_student(student_id)
    student = await (await _graph_db()).update_student(student_id=student_id, updates={"name": body.name, **extra})
    return _student_info(student)


# ── Document Upload ──────────────────────────────────────────────


@router.get("/documents/check")
async def check_document_exists(filename: str, student_id: Optional[str] = Query(default=None)):
    """Check if a document with this filename already exists for the student."""
    resolved_student_id = await _resolve_student_id(student_id)
    existing = await (await _graph_db()).find_document_by_filename(student_id=resolved_student_id, filename=filename)
    return {"exists": existing is not None, "document": existing}


@router.post("/documents", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    student_id: Optional[str] = Form(None),
    replace: str = Form("false"),
):
    """Upload a document for the student graph."""
    resolved_student_id = await _resolve_student_id(student_id)
    upload = await _read_upload_file(file)

    # If replacing, delete the existing document first
    if replace.lower() == "true":
        existing = await (await _graph_db()).find_document_by_filename(
            student_id=resolved_student_id,
            filename=upload["filename"],
        )
        if existing and existing.get("id"):
            await (await _graph_db()).delete_document_cascade(document_id=existing["id"])
            log.info("Replaced existing document: %s", upload["filename"])

    # Process through the registered document ingestion pipeline
    from app.agents.doc_analyst import doc_analyst as process_doc

    state: dict[str, Any] = {
        "files": [upload],
        "session_id": "",
        "student_id": resolved_student_id,
        "step_progress": [],
    }

    result = await process_doc(state)
    return DocumentUploadResponse(
        document_id=f"doc_uploaded",
        filename=upload["filename"],
        entities_extracted=len(result.get("extracted_entities", [])),
        chunks_stored=int(result.get("latest_ingestion_result", {}).get("chunk_count", 0) or 0),
    )


# ── Student ──────────────────────────────────────────────────────

@router.get("/student", response_model=StudentResponse)
async def get_student(student_id: Optional[str] = Query(default=None)):
    """Get the student's full graph snapshot."""
    resolved_student_id = await _resolve_student_id(student_id)
    student_graph = await (await _graph_db()).get_full_student(student_id=resolved_student_id)
    student = dict(student_graph.get("student") or {})
    sections = list(student_graph.get("sections") or [])
    entities = list(student_graph.get("entities") or [])
    section_items: dict[str, list[dict[str, Any]]] = {}
    all_entities: dict[str, list[dict[str, Any]]] = {"Document": [], "Chunk": []}
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        section_key = str(entity.get("section_key") or "")
        if section_key:
            section_items.setdefault(section_key, []).append(entity)
        entity_type = str(entity.get("entity_type") or "Entity")
        all_entities.setdefault(entity_type, []).append(entity)
        for document in entity.get("documents", []) if isinstance(entity.get("documents"), list) else []:
            if isinstance(document, dict):
                all_entities["Document"].append(document)
        for chunk in entity.get("chunks", []) if isinstance(entity.get("chunks"), list) else []:
            if isinstance(chunk, dict):
                all_entities["Chunk"].append(chunk)
    student_snapshot = {
        "student": student,
        "root_properties": student,
        "sections": sections,
        "entities": entities,
        "section_items": section_items,
        "student_schema": {"sections": sections},
        "all_entities": all_entities,
        "completeness": float(student.get("completeness", 0.0) or 0.0),
    }
    long_context_preview = build_long_context_payload(student_snapshot, {})
    return StudentResponse(
        root_properties=student_snapshot.get("root_properties", {}),
        sections=student_snapshot.get("sections", []),
        section_items=student_snapshot.get("section_items", {}),
        long_context_preview=long_context_preview,
        student_schema=student_snapshot.get("student_schema", {}),
        all_entities=student_snapshot.get("all_entities", {}),
        completeness=float(student_snapshot.get("completeness", 0.0) or 0.0),
        confidence=0.0,
    )


@router.put("/student")
async def update_student(update: StudentUpdate):
    """Update a specific student field."""
    resolved_student_id = await _resolve_student_id(update.student_id)
    value = update.value
    if update.field == "long_context_summary":
        try:
            value = normalize_long_context_summary(str(update.value or ""))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    result = await (await _graph_db()).update_student(
        student_id=resolved_student_id,
        updates={update.field: value},
    )
    return {"updated": True, "data": result}


@router.delete("/student/reset")
async def reset_all_student_data(student_id: Optional[str] = Query(default=None)):
    """Delete all student data from the knowledge graph."""
    resolved_student_id = await _resolve_student_id(student_id)
    deleted = await (await _graph_db()).reset_student_data(student_id=resolved_student_id)
    deleted_replays = delete_replay_artifacts_for_student(resolved_student_id)
    return {
        "deleted": deleted,
        "deleted_replays": deleted_replays,
        "message": "All student data and replay artifacts for this student have been reset.",
    }


@router.delete("/settings/delete-all-data")
async def delete_all_data_everywhere():
    """Delete all students, graph data, and persisted chat sessions."""
    deleted_nodes = await (await _graph_db()).reset_all_data()
    await reset_checkpointer_storage()
    deleted_replays = delete_all_replay_artifacts()
    return {
        "deleted_nodes": deleted_nodes,
        "deleted_replays": deleted_replays,
        "message": "All students, Neo4j data, chat sessions, and replay artifacts have been deleted.",
    }


@router.get("/student/graph", response_model=GraphDataResponse)
async def get_student_graph(student_id: Optional[str] = Query(default=None)):
    """Get knowledge graph data for visualization."""
    resolved_student_id = await _resolve_student_id(student_id)
    data = await (await _graph_db()).get_graph_data(student_id=resolved_student_id)
    return GraphDataResponse(nodes=data["nodes"], relationships=data["relationships"])


# ── Sessions ─────────────────────────────────────────────────────


@router.get("/sessions")
async def list_sessions(student_id: Optional[str] = Query(default=None)):
    """List all chat sessions. Returns from SQLite checkpoint metadata."""
    # Note: In a full implementation, we'd query the SQLite checkpointer
    # For now, return an empty list — sessions are created on first chat
    resolved_student_id = await _resolve_student_id(student_id)
    return {"student_id": resolved_student_id, "sessions": []}


@router.get("/replays", response_model=list[ReplayArtifactInfo])
async def get_replays(limit: int = Query(default=25, ge=1, le=100)):
    """List recent replay artifacts for debugging and evaluation."""
    return [ReplayArtifactInfo(**item) for item in list_replay_artifacts(limit=limit)]


@router.get("/replays/{replay_id}")
async def get_replay(replay_id: str):
    """Fetch a full replay artifact by ID."""
    artifact = get_replay_artifact(replay_id)
    if artifact is None:
        raise HTTPException(404, "Replay artifact not found")
    return artifact


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, student_id: Optional[str] = Query(default=None)):
    """Acknowledge discarding a chat session id; student documents are not removed."""
    resolved_student_id = await _resolve_student_id(student_id)
    return {"deleted": True, "session_id": session_id, "student_id": resolved_student_id}


# ── Settings ─────────────────────────────────────────────────────


@router.get("/settings", response_model=SettingsResponse)
async def get_settings():
    """Get current application settings."""
    return SettingsResponse(
        topic_guard_enabled=_topic_guard_enabled,
        reasoning=_reasoning,
        models={
            "text_llm": get_active_text_model(),
            "vision_llm": settings.VISION_MODEL,
            "embeddings": settings.EMBEDDING_MODEL,
            "retrieval": get_active_retrieval_strategy(),
        },
    )


@router.put("/settings")
async def update_settings(update: SettingsUpdate):
    """Update application settings."""
    global _topic_guard_enabled, _reasoning
    if update.topic_guard_enabled is not None:
        _topic_guard_enabled = update.topic_guard_enabled
    if update.reasoning is not None:
        _reasoning = str(update.reasoning or "medium").strip().lower() or "medium"
    return {"updated": True, "topic_guard_enabled": _topic_guard_enabled, "reasoning": _reasoning}


# ── Health ───────────────────────────────────────────────────────


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Check system health for all registered dependencies."""
    statuses = await get_dependency_status()
    services = {name: str(status) for name, status in statuses.items()}
    overall = "ok" if all(s == "connected" for s in services.values()) else "degraded"
    return HealthResponse(status=overall, services=services)

# ── Helpers ──────────────────────────────────────────────────────


async def _resolve_student_id(student_id: str | None, create_if_missing: bool = True) -> str:
    """Resolve the active student id, creating a runtime id if needed."""
    if student_id:
        if create_if_missing:
            await _ensure_student(student_id)
        return student_id
    if not create_if_missing:
        return ""
    runtime_student_id = generate_student_id()
    await _ensure_student(runtime_student_id)
    return runtime_student_id
