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

from app.adapters.neo4j._sanitize import sanitize_neo4j_value
from app.adapters.neo4j.graphDB import GraphDB
from app.config.settings import settings
from app.core.checkpointer import reset_checkpointer_storage
from app.core.workflow import get_compiled_workflow
from app.services.replay_store import (
    build_replay_artifact,
    delete_all_replay_artifacts,
    delete_replay_artifacts_for_student,
    get_replay_artifact,
    list_replay_artifacts,
    save_replay_artifact,
)
from app.schemas.models import (
    DocumentUploadResponse,
    GraphDataResponse,
    HealthResponse,
    StudentCreate,
    StudentInfo,
    StudentResponse,
    StudentUpdate,
    ReplayArtifactInfo,
    SettingsResponse,
    SettingsUpdate,
)
from app.tools.graph_tools import get_driver as get_graph_driver
from app.utils.ids import generate_session_id, generate_student_id
from app.utils.runtime_utils import infer_method

log = logging.getLogger("pathfinder.api")

router = APIRouter()
_TOKEN_CHUNK_SIZE = 120

def _student_info(student: dict[str, Any]) -> StudentInfo:
    """Normalize a raw student record into the API response shape."""
    extra = {
        k: v for k, v in student.items()
        if k not in {"id", "name", "created_at", "updated_at",
                      "long_context_summary", "long_context_notes"}
        and v is not None and str(v).strip()
    }
    return StudentInfo(
        student_id=student.get("id", ""),
        name=student.get("name", "Student"),
        created_at=student.get("created_at"),
        updated_at=student.get("updated_at"),
        **extra,
    )


async def _graph_db() -> GraphDB:
    return GraphDB(await get_graph_driver())


async def _ensure_student(student_id: str) -> dict[str, Any]:
    return await (await _graph_db()).update_student(student_id=student_id, updates={})


async def _read_upload_file(file: UploadFile) -> dict[str, Any]:
    """Read and validate one FastAPI uploaded file."""
    filename = str(file.filename or "").strip()
    if not filename:
        raise HTTPException(400, "Filename is required")
    ext = os.path.splitext(filename)[1].lower()
    if ext not in settings.ALLOWED_FILE_TYPES:
        allowed = ", ".join(settings.ALLOWED_FILE_TYPES)
        raise HTTPException(400, f"Unsupported file type '{ext}'. Allowed: {allowed}")
    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(413, f"File {filename} exceeds {settings.MAX_FILE_SIZE_MB}MB limit")
    return {
        "filename": filename,
        "content": content,
        "size": len(content),
        "content_type": file.content_type,
    }


# ── Runtime state ────────────────────────────────────────────────
_topic_guard_enabled: bool = settings.TOPIC_GUARD_ENABLED
_reasoning: str = "medium"


def _normalize_reasoning(reasoning: str) -> str:
    """Normalize the requested reasoning label."""
    return str(reasoning or "medium").strip().lower() or "medium"


async def _get_dependency_status() -> dict[str, str]:
    """Check live dependency health for the current turn."""
    neo4j_status = "unknown"
    llm_status = "unknown"
    embeddings_status = "unknown"

    try:
        driver = await get_graph_driver()
        async with driver.session() as session:
            await session.run("RETURN 1")
        neo4j_status = "connected"
    except Exception:
        neo4j_status = "disconnected"

    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                resp = await client.get(f"{settings.LLM_BASE_URL.replace('/v1', '')}/v1/models")
                if resp.status_code == 200:
                    payload = resp.json() if resp.content else {}
                    models = payload.get("data", []) if isinstance(payload, dict) else []
                    llm_status = "connected" if models else "no_model_loaded"
                else:
                    llm_status = "error"
            except Exception:
                llm_status = "disconnected"

            try:
                resp = await client.get(f"{settings.OLLAMA_URL}/api/tags")
                embeddings_status = "connected" if resp.status_code == 200 else "error"
            except Exception:
                embeddings_status = "disconnected"
    except Exception:
        llm_status = "disconnected"
        embeddings_status = "disconnected"

    web_search_status = "configured" if any(
        [
            settings.TAVILY_API_KEY,
            settings.GOOGLE_CSE_API_KEY,
            settings.BRAVE_API_KEY,
        ]
    ) else "fallback_only"

    return {
        "neo4j": neo4j_status,
        "llm": llm_status,
        "embeddings": embeddings_status,
        "web_search": web_search_status,
    }


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
    replace_set = {name.strip() for name in replace_filenames.split(",") if name.strip()}

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
            graph = await get_compiled_workflow()
            turn_reasoning = _normalize_reasoning(reasoning if str(reasoning or "").strip() else _reasoning)
            dependency_status = await _get_dependency_status()
            runtime_snapshot = {
                "session_id": session_id,
                "student_id": resolved_student_id,
                "selected_text_model": settings.LLM_MODEL,
                "reasoning": turn_reasoning,
                "dependency_status": dependency_status,
            }
            initial_state = {
                "messages": [("human", query)],
                "query": query,
                "files": file_data,
                "session_id": session_id,
                "student_id": resolved_student_id,
                "topic_guard_enabled": _topic_guard_enabled,
                "reasoning": turn_reasoning,
            }
            config = {
                "configurable": {"thread_id": f"{resolved_student_id}:{session_id}"},
                "recursion_limit": 15,
            }

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
            final_answer = str(final_state.get("final_answer", "") or "I couldn't generate a response.")

            # Stream the exact final answer in bounded chunks so markdown/newlines survive intact.
            for start in range(0, len(final_answer), _TOKEN_CHUNK_SIZE):
                chunk = final_answer[start : start + _TOKEN_CHUNK_SIZE]
                yield f"event: token\ndata: {json.dumps({'content': chunk})}\n\n"

            # Done event
            latest_ingestion = dict(final_state.get("latest_ingestion_result", {}) or {})
            done_payload = {
                "session_id": session_id,
                "student_id": resolved_student_id,
                "citations": final_state.get("citations", []),
                "method": infer_method(final_state),
                "dependency_status": dependency_status,
                "processing_issues": final_state.get("processing_issues", []),
                "stop_reason": final_state.get("stop_reason", ""),
                "selected_specialist": final_state.get("selected_specialist", ""),
                "routing_scores": final_state.get("routing_scores", {}),
                "routing_reason": final_state.get("routing_reason", ""),
                "tool_call_log": final_state.get("tool_call_log", []),
                "specialist_output": final_state.get("specialist_output", {}),
                "session_context": str(final_state.get("session_context", "") or ""),
                "long_context": str(final_state.get("long_context", "") or ""),
                "document_ingestion": latest_ingestion,
                "runtime_snapshot": runtime_snapshot,
            }
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
        students = [sanitize_neo4j_value(dict(record["student"])) async for record in result]
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
    from app.nodes.doc_analyst import doc_analyst as process_doc

    state: dict[str, Any] = {
        "files": [upload],
        "session_id": "",
        "student_id": resolved_student_id,
        "step_progress": [],
    }

    result = await process_doc(state)
    ingestion = result.get("latest_ingestion_result", {}) if isinstance(result.get("latest_ingestion_result", {}), dict) else {}
    documents = list(ingestion.get("documents", []) or [])
    first_document = documents[0] if documents else {}
    if not first_document or not str(first_document.get("document_id", "") or "").strip():
        raise HTTPException(422, f"Document {upload['filename']} could not be processed.")
    graph_updates = dict((first_document.get("ingestion_result") or {}).get("graph_updates") or {})
    counts = dict(graph_updates.get("counts") or {})
    return DocumentUploadResponse(
        document_id=str(first_document.get("document_id", "") or ""),
        filename=upload["filename"],
        entities_extracted=int(counts.get("entities_written", 0) or 0),
        chunks_stored=int(first_document.get("chunks_stored", 0) or 0),
    )


# ── Student ──────────────────────────────────────────────────────

@router.get("/student", response_model=StudentResponse)
async def get_student(student_id: Optional[str] = Query(default=None)):
    """Get the student's profile view plus canonical graph schema."""
    resolved_student_id = await _resolve_student_id(student_id)
    graph_db = await _graph_db()
    student_graph = await graph_db.get_full_student(student_id=resolved_student_id)
    student_schema = await graph_db.get_student_schema(student_id=resolved_student_id)
    student = dict(student_graph.get("student") or {})
    sections = list(student_schema.get("sections") or [])
    entities = list(student_graph.get("entities") or [])
    section_items: dict[str, list[dict[str, Any]]] = {}
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        section_key = str(entity.get("section_key") or "")
        if section_key:
            section_items.setdefault(section_key, []).append(entity)
    return StudentResponse(
        root_properties=student,
        sections=sections,
        section_items=section_items,
        long_context=str(student.get("long_context_summary", "") or ""),
        student_schema=student_schema,
    )


@router.put("/student")
async def update_student(update: StudentUpdate):
    """Update a specific student field."""
    resolved_student_id = await _resolve_student_id(update.student_id)
    value = update.value
    if update.field == "long_context_summary":
        value = str(update.value or "")
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

# ── Settings ─────────────────────────────────────────────────────


@router.get("/settings", response_model=SettingsResponse)
async def get_settings():
    """Get current application settings."""
    return SettingsResponse(
        topic_guard_enabled=_topic_guard_enabled,
        reasoning=_reasoning,
        models={
            "text_llm": settings.LLM_MODEL,
            "vision_llm": settings.VISION_MODEL,
            "embeddings": settings.EMBEDDING_MODEL,
        },
    )


@router.put("/settings")
async def update_settings(update: SettingsUpdate):
    """Update application settings."""
    global _topic_guard_enabled, _reasoning
    if update.topic_guard_enabled is not None:
        _topic_guard_enabled = update.topic_guard_enabled
    if update.reasoning is not None:
        _reasoning = _normalize_reasoning(update.reasoning)
    return {"updated": True, "topic_guard_enabled": _topic_guard_enabled, "reasoning": _reasoning}


# ── Health ───────────────────────────────────────────────────────


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Check system health for all registered dependencies."""
    statuses = await _get_dependency_status()
    services = {name: str(status) for name, status in statuses.items()}
    healthy_statuses = {"connected", "configured", "fallback_only"}
    overall = "ok" if all(status in healthy_statuses for status in services.values()) else "degraded"
    return HealthResponse(status=overall, services=services)

# ── Helpers ──────────────────────────────────────────────────────


async def _resolve_student_id(student_id: str | None) -> str:
    """Resolve the active student id, creating a runtime id if needed."""
    if student_id:
        await _ensure_student(student_id)
        return student_id
    runtime_student_id = generate_student_id()
    await _ensure_student(runtime_student_id)
    return runtime_student_id
