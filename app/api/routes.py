"""HTTP endpoints the frontend and MCP clients talk to.

All routes are mounted under `/api/v1` (see `main.py`). The endpoints
fall into five rough groups:

- `/chat`              : the big one — accepts a user message + optional
                         uploaded files and streams the whole LangGraph
                         response back as Server-Sent Events (SSE). Live
                         progress, streamed answer tokens, and the final
                         metadata payload all flow over one connection.
- `/students`          : CRUD for local student profiles.
- `/documents`         : upload + duplicate-check before ingestion.
- `/student`, `/student/graph`, `/student/reset`:
                         read/write the knowledge graph for one student.
- `/replays`           : list and fetch saved conversation replays
                         (from `app.services.replay_store`) — used by
                         the debug / evaluation views.
- `/settings`, `/health`:
                         app-level toggles and dependency status.

This module deliberately does not own any LLM or graph logic — it only
glues HTTP input to the LangGraph workflow and the graph adapters.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from app.adapters.neo4j._sanitize import sanitize_neo4j_value
from app.adapters.neo4j.graphDB import GraphDB
from app.config.settings import settings
from app.core.checkpointer import delete_student_checkpoints, reset_checkpointer_storage
from app.core.workflow import get_compiled_workflow
from app.services.llm_settings import switch_llm_provider
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
from app.utils.progress import (
    normalize_progress_entry,
    reset_live_emitter,
    set_live_emitter,
)
from app.utils.runtime_utils import infer_method

log = logging.getLogger("pathfinder.api")

router = APIRouter()

_TOKEN_CHUNK_SIZE = 120
_DEPENDENCY_STATUS_TTL_SECONDS = 15.0
_dependency_status_cache: dict[str, Any] = {"timestamp": 0.0, "payload": None}


def _student_info(student: dict[str, Any]) -> StudentInfo:
    """Convert a raw Neo4j student record into the `StudentInfo` wire shape.

    Splits out the well-known fields and lets any leftover scalar
    properties ride through as extras — `StudentInfo` is configured to
    accept them so new student attributes can appear in the list view
    without touching this code.
    """
    extra = {
        k: v for k, v in student.items()
        if k not in {"id", "name", "created_at", "updated_at",
                      "long_context"}
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
    """Build a `GraphDB` bound to the shared Neo4j driver for this process."""
    return GraphDB(await get_graph_driver())


async def _ensure_student(student_id: str) -> dict[str, Any]:
    """Make sure a `Student` node exists for this id — cheap upsert.

    Called at the top of every route that needs a student so that a
    fresh `student_id` from the client auto-creates a profile on first
    use instead of 404'ing.
    """
    return await (await _graph_db()).update_student(student_id=student_id, updates={})


async def _read_upload_file(file: UploadFile) -> dict[str, Any]:
    """Read the upload into memory and enforce size + extension limits.

    Returns a plain dict so downstream code (ingestion pipeline) doesn't
    hold onto the FastAPI `UploadFile` object beyond the request scope.
    """
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


# Process-level toggles — mutated by the /settings endpoint and read by
# /chat on every turn. They start from `settings` but can be changed at
# runtime without a restart.
_topic_guard_enabled: bool = settings.TOPIC_GUARD_ENABLED
_reasoning: str = "medium"


def _normalize_reasoning(reasoning: str) -> str:
    """Coerce a user-provided reasoning label to lowercase, default "medium"."""
    return str(reasoning or "medium").strip().lower() or "medium"


async def _get_dependency_status(*, force_refresh: bool = False) -> dict[str, str]:
    """Probe Neo4j, LM Studio, Ollama, and web search and return a status map.

    Result is cached for `_DEPENDENCY_STATUS_TTL_SECONDS` so the chat
    endpoint doesn't re-ping every backing service on each message. The
    `/health` endpoint passes `force_refresh=True` to always see live
    state.
    """
    cached_payload = _dependency_status_cache.get("payload")
    cached_at = float(_dependency_status_cache.get("timestamp", 0.0) or 0.0)
    cache_age = time.monotonic() - cached_at
    if (
        not force_refresh
        and isinstance(cached_payload, dict)
        and cache_age < _DEPENDENCY_STATUS_TTL_SECONDS
    ):
        return dict(cached_payload)

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
                resp = await client.get(
                    f"{settings.LLM_BASE_URL.rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                )
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

    payload = {
        "neo4j": neo4j_status,
        "llm": llm_status,
        "embeddings": embeddings_status,
        "web_search": web_search_status,
    }
    _dependency_status_cache["timestamp"] = time.monotonic()
    _dependency_status_cache["payload"] = dict(payload)
    return payload


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
    """Primary chat endpoint — runs the full LangGraph and streams SSE events.

    Returns a `text/event-stream` that carries three event types:
    `progress` (live status per node), `token` (chunks of the final
    answer), and `done` (the final metadata payload). On the server
    side, a background task drives LangGraph while the response
    generator drains a queue of events — that lets progress messages
    reach the browser while the graph is still executing.
    """
    resolved_student_id = await _resolve_student_id(student_id)
    if not session_id:
        session_id = generate_session_id()
    files = list(files) if isinstance(files, list) else []
    graph_db = await _graph_db()

    replace_set = {name.strip() for name in replace_filenames.split(",") if name.strip()}

    # Replaces on re-upload — deletes the old document (and its chunks)
    # so ingestion doesn't pile up duplicates for the same filename.
    for fname in replace_set:
        existing = await graph_db.find_document_by_filename(
            student_id=resolved_student_id,
            filename=fname,
        )
        if existing and existing.get("id"):
            await graph_db.delete_document_cascade(document_id=existing["id"])
            log.info("Chat: replaced existing document before re-upload: %s", fname)

    file_data = [await _read_upload_file(upload) for upload in files]

    async def event_stream():
        # One queue carries every outbound SSE event. Using a single queue
        # lets us interleave live progress (pushed from inside nodes via
        # the progress emitter) with the final token/done events (pushed
        # after the graph finishes). `None` is the close-stream sentinel.
        outbound: asyncio.Queue[tuple[str, Any] | None] = asyncio.Queue()

        def push_progress(entry: dict[str, str]) -> None:
            payload = normalize_progress_entry(entry, fallback_stage="Working")
            try:
                outbound.put_nowait(("progress", payload))
            except Exception:
                pass

        live_token = set_live_emitter(push_progress)

        async def run_graph() -> None:
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
                    "step_progress": [],
                }
                config = {
                    "configurable": {"thread_id": f"{resolved_student_id}:{session_id}"},
                    "recursion_limit": 15,
                }

                final_state: dict[str, Any] = {}

                async for event in graph.astream(initial_state, config=config):
                    for _node_name, state_update in event.items():
                        final_state.update(state_update)

                final_answer = str(final_state.get("final_answer", "") or "I couldn't generate a response.")

                for start in range(0, len(final_answer), _TOKEN_CHUNK_SIZE):
                    chunk = final_answer[start : start + _TOKEN_CHUNK_SIZE]
                    outbound.put_nowait(("token", {"content": chunk}))

                latest_ingestion = dict(final_state.get("latest_ingestion_result", {}) or {})
                latest_query_ingestion = dict(final_state.get("latest_query_ingestion_result", {}) or {})
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
                    "query_ingestion": latest_query_ingestion,
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
                    saved_artifact = await asyncio.to_thread(save_replay_artifact, artifact)
                    done_payload["replay_id"] = saved_artifact.get("id", "")
                except Exception as exc:
                    log.warning("Failed to persist replay artifact for session %s: %s", session_id, exc)
                outbound.put_nowait(("done", done_payload))

            except Exception as exc:
                log.error("Chat error: %s", exc, exc_info=True)
                outbound.put_nowait(("error", {"error": str(exc)}))
            finally:
                outbound.put_nowait(None)

        graph_task = asyncio.create_task(run_graph())
        try:
            while True:
                item = await outbound.get()
                if item is None:
                    break
                event_name, payload = item
                yield f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
        finally:
            reset_live_emitter(live_token)
            if not graph_task.done():
                graph_task.cancel()
                try:
                    await graph_task
                except (asyncio.CancelledError, Exception):
                    pass

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/students", response_model=list[StudentInfo])
async def get_students():
    """Return all local students, most-recently-updated first."""
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
    """Create a new local student and return its summary."""
    extra = body.model_extra or {}
    student_id = generate_student_id()
    await _ensure_student(student_id)
    student = await (await _graph_db()).update_student(student_id=student_id, updates={"name": body.name, **extra})
    return _student_info(student)


# ── Document Upload ──────────────────────────────────────────────


@router.get("/documents/check")
async def check_document_exists(filename: str, student_id: Optional[str] = Query(default=None)):
    """Tell the UI whether a filename would be a duplicate before upload.

    Lets the client show a "Replace existing?" prompt instead of silently
    creating a second copy of the same document.
    """
    resolved_student_id = await _resolve_student_id(student_id)
    existing = await (await _graph_db()).find_document_by_filename(student_id=resolved_student_id, filename=filename)
    return {"exists": existing is not None, "document": existing}


@router.post("/documents", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    student_id: Optional[str] = Form(None),
    replace: str = Form("false"),
):
    """Ingest a single file into the student's graph + vector store.

    This runs the same ingestion pipeline (`doc_analyst`) the chat
    endpoint uses when files are attached to a message — just without
    the surrounding chat turn.
    """
    resolved_student_id = await _resolve_student_id(student_id)
    upload = await _read_upload_file(file)
    graph_db = await _graph_db()

    if replace.lower() == "true":
        existing = await graph_db.find_document_by_filename(
            student_id=resolved_student_id,
            filename=upload["filename"],
        )
        if existing and existing.get("id"):
            await graph_db.delete_document_cascade(document_id=existing["id"])
            log.info("Replaced existing document: %s", upload["filename"])

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
    """Return everything the profile page needs in one round trip.

    Combines: root student properties, the schema of all known sections,
    the entities grouped by section, and any long-form context the AI
    has accumulated about the student.
    """
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
        long_context=str(student.get("long_context", "") or ""),
        student_schema=student_schema,
    )


@router.put("/student")
async def update_student(update: StudentUpdate):
    """Patch a single scalar field on the student (save-on-blur in the UI)."""
    resolved_student_id = await _resolve_student_id(update.student_id)
    value = update.value
    if update.field == "long_context":
        value = str(update.value or "")
    result = await (await _graph_db()).update_student(
        student_id=resolved_student_id,
        updates={update.field: value},
    )
    return {"updated": True, "data": result}


@router.delete("/student/reset")
async def reset_all_student_data(student_id: Optional[str] = Query(default=None)):
    """Wipe a single student's graph + replay artifacts. Destructive."""
    resolved_student_id = await _resolve_student_id(student_id)
    deleted = await (await _graph_db()).reset_student_data(student_id=resolved_student_id)
    deleted_replays = delete_replay_artifacts_for_student(resolved_student_id)
    return {
        "deleted": deleted,
        "deleted_replays": deleted_replays,
        "message": "All student data and replay artifacts for this student have been reset.",
    }


@router.delete("/student")
async def delete_student_profile(student_id: str = Query(min_length=1)):
    """Delete the explicitly selected profile without auto-creating a student."""
    await delete_student_checkpoints(student_id)
    deleted = await (await _graph_db()).delete_student_profile(student_id=student_id)
    deleted_replays = delete_replay_artifacts_for_student(student_id)
    return {
        **deleted,
        "deleted_replays": deleted_replays,
        "message": "Student profile and associated data have been deleted.",
    }


@router.delete("/settings/delete-all-data")
async def delete_all_data_everywhere():
    """Nuke everything: Neo4j data, chat checkpoints, and replay artifacts.

    Intended for the "reset the whole app" button. Unrecoverable.
    """
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
    """Return the nodes + edges the graph visualization view renders."""
    resolved_student_id = await _resolve_student_id(student_id)
    data = await (await _graph_db()).get_graph_data(student_id=resolved_student_id)
    return GraphDataResponse(nodes=data["nodes"], relationships=data["relationships"])


@router.get("/replays", response_model=list[ReplayArtifactInfo])
async def get_replays(
    limit: int = Query(default=25, ge=1, le=100),
):
    """Most recent replays — the debug view's index page uses this."""
    return [
        ReplayArtifactInfo(**item)
        for item in list_replay_artifacts(limit=limit)
    ]


@router.get("/replays/{replay_id}")
async def get_replay(replay_id: str):
    """Return the entire replay JSON so the debug view can reconstruct a turn."""
    artifact = get_replay_artifact(replay_id)
    if artifact is None:
        raise HTTPException(404, "Replay artifact not found")
    return artifact

# ── Settings ─────────────────────────────────────────────────────


@router.get("/settings", response_model=SettingsResponse)
async def get_settings():
    """Return the current runtime toggles + which models are configured."""
    return SettingsResponse(
        topic_guard_enabled=_topic_guard_enabled,
        reasoning=_reasoning,
        llm_provider=settings.llm_provider,
        nvidia_configured=bool(settings.NVIDIA_API_KEY or (
            settings.LLM_API_KEY and settings.LLM_API_KEY != "sk-no-key"
        )),
        models={
            "text_llm": settings.LLM_MODEL,
            "vision_llm": settings.VISION_MODEL,
            "embeddings": settings.EMBEDDING_MODEL,
        },
    )


@router.put("/settings")
async def update_settings(update: SettingsUpdate):
    """Update toggles and persist provider changes without a restart."""
    global _topic_guard_enabled, _reasoning
    if update.llm_provider is not None:
        try:
            switch_llm_provider(update.llm_provider)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except OSError as exc:
            log.error("Could not save LLM provider: %s", type(exc).__name__)
            raise HTTPException(500, "Could not save the model provider. Please try again.") from exc
        _dependency_status_cache.update(timestamp=0.0, payload=None)
    if update.topic_guard_enabled is not None:
        _topic_guard_enabled = update.topic_guard_enabled
    if update.reasoning is not None:
        _reasoning = _normalize_reasoning(update.reasoning)
    return {"updated": True, **(await get_settings()).model_dump()}


# ── Health ───────────────────────────────────────────────────────


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Live probe of Neo4j / LLM / embeddings / web search.

    Skips the status cache so the UI banner and any deploy-time probes
    always get a fresh picture.
    """
    statuses = await _get_dependency_status(force_refresh=True)
    services = {name: str(status) for name, status in statuses.items()}
    healthy_statuses = {"connected", "configured", "fallback_only"}
    overall = "ok" if all(status in healthy_statuses for status in services.values()) else "degraded"
    return HealthResponse(status=overall, services=services)

# ── Helpers ──────────────────────────────────────────────────────


async def _resolve_student_id(student_id: str | None) -> str:
    """Pick an effective student id for this request.

    If the client sent one, use it (and make sure the node exists).
    Otherwise mint a fresh id so anonymous / first-time users still get
    a well-formed profile to write into.
    """
    if student_id:
        await _ensure_student(student_id)
        return student_id
    runtime_student_id = generate_student_id()
    await _ensure_student(runtime_student_id)
    return runtime_student_id
