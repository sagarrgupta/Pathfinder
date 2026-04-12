"""API endpoints for Pathfinder.

All routes prefixed with /api/v1 (set in main.py).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi import Query
from fastapi.responses import StreamingResponse

from app.adapters.neo4j.graph_store import (
    create_student,
    delete_document_cascade,
    delete_entity_for_student,
    delete_entity,
    ensure_student,
    get_student,
    find_document_by_filename,
    get_full_profile,
    get_graph_data,
    list_students,
    list_saved_recommendations,
    promote_document_to_global,
    reset_student_data,
    reset_all_data,
    run_cypher,
    execute_cypher,
    store_memory_item,
    update_saved_recommendation_outcome,
    update_entity,
    update_student,
)
from app.agents.profile_manager import process_free_text
from app.config.settings import settings
from app.core.graph import get_compiled_graph
from app.core.memory import reset_checkpointer_storage
from app.services.runtime_session import build_chat_runtime_session, get_dependency_status
from app.services.conflict_autoresolve import (
    auto_resolve_profile_conflicts,
    list_profile_conflicts,
    resolve_conflict_choice,
)
from app.services.consolidation import maybe_consolidate_memory
from app.services.background_jobs import get_background_status
from app.services.execution_registry import get_active_retrieval_strategy, get_active_text_model
from app.services.replay_store import (
    build_replay_artifact,
    get_replay_artifact,
    list_replay_artifacts,
    save_replay_artifact,
)
from app.services.replay_eval import evaluate_recent_replays, evaluate_replay_by_id
from app.services.decision_memory import persist_decision_record
from app.services.eval_analytics import build_eval_analytics, list_benchmark_sets
from app.schemas.models import (
    ChatResponse,
    DocumentUploadResponse,
    EntityUpdate,
    GraphDataResponse,
    HealthResponse,
    ConflictChoiceRequest,
    ProfileCreate,
    ProfileInfo,
    ProfileResponse,
    ProfileTextInput,
    ProfileUpdate,
    ReplayArtifactInfo,
    EvalAnalyticsResponse,
    EvalBenchmarkInfo,
    ReplayEvaluationBatch,
    ReplayEvaluationInfo,
    SessionInfo,
    SavedRecommendationCreate,
    SavedRecommendationInfo,
    SavedRecommendationOutcomeUpdate,
    SettingsResponse,
    SettingsUpdate,
)
from app.utils.ids import generate_session_id, generate_student_id

log = logging.getLogger("pathfinder.api")

router = APIRouter()


def _metadata_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def _profile_info_from_student(student: dict[str, Any]) -> ProfileInfo:
    """Normalize a raw student record into the API response shape."""
    return ProfileInfo(
        student_id=student.get("id", ""),
        name=student.get("name", "Student"),
        email=student.get("email"),
        university=student.get("university"),
        program=student.get("program"),
        created_at=student.get("created_at"),
        updated_at=student.get("updated_at"),
        completeness=float(student.get("completeness", 0.0) or 0.0),
    )


def _saved_recommendation_info_from_record(
    record: dict[str, Any],
    *,
    fallback_student_id: str,
    default_title: str | None = None,
    default_recommendation_type: str | None = None,
    default_actions: list[str] | None = None,
    default_source_session_id: str | None = None,
    default_source_query: str | None = None,
) -> SavedRecommendationInfo:
    """Normalize a stored memory record into a saved recommendation response."""
    metadata = _metadata_dict(record.get("metadata"))
    status = metadata.get("status", "active")
    return SavedRecommendationInfo(
        id=record.get("id", ""),
        student_id=record.get("student_id", fallback_student_id),
        title=metadata.get("title") or default_title or record.get("summary", "Saved recommendation"),
        summary=record.get("summary", ""),
        recommendation_type=default_recommendation_type or str(record.get("memory_type", "saved_plan")).replace("saved_", ""),
        actions=metadata.get("actions", default_actions or []),
        source_session_id=metadata.get("source_session_id", default_source_session_id),
        source_query=metadata.get("source_query", default_source_query),
        created_at=record.get("created_at"),
        status=status,
        next_review_at=metadata.get("next_review_at"),
        follow_up_prompt=metadata.get("follow_up_prompt"),
        outcome_status=metadata.get("outcome_status", status),
        outcome_notes=metadata.get("outcome_notes"),
        outcome_updated_at=metadata.get("outcome_updated_at"),
        metadata=metadata,
    )


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


def _profile_confidence(profile: dict[str, Any]) -> float:
    """Estimate profile confidence from resolved candidate facts first."""
    candidate_facts = profile.get("candidate_facts", [])
    resolved_candidates = [item for item in candidate_facts if item.get("status") == "resolved"]
    confidence_values = [float(item.get("confidence", 0.0) or 0.0) for item in resolved_candidates] or [
        float(item.get("confidence", 0.0) or 0.0) for item in candidate_facts
    ]
    return round(sum(confidence_values) / len(confidence_values), 2) if confidence_values else 0.0


def _profile_memory_overview(profile: dict[str, Any]) -> dict[str, Any]:
    """Build the profile memory summary returned to the frontend."""
    candidate_facts = profile.get("candidate_facts", [])
    fact_summary = profile.get("fact_summary", {})
    return {
        "candidate_facts": len(candidate_facts),
        "memory_items": len(profile.get("memory_items", [])),
        "evidence": len(profile.get("evidence", [])),
        "conflicts": len([item for item in candidate_facts if item.get("status") == "conflicted"]),
        "confirmed": int(fact_summary.get("confirmed_candidate_facts", 0) or 0),
        "reinforced": int(fact_summary.get("reinforced_candidate_facts", 0) or 0),
        "inferred": int(fact_summary.get("inferred_candidate_facts", 0) or 0),
    }

# ── Runtime state ────────────────────────────────────────────────
_topic_guard_enabled: bool = settings.TOPIC_GUARD_ENABLED
_advisor_mode: str = "adaptive"


# ── Chat (SSE Streaming) ────────────────────────────────────────


@router.post("/chat")
async def chat(
    query: str = Form(...),
    session_id: Optional[str] = Form(None),
    student_id: Optional[str] = Form(None),
    files: list[UploadFile] = File(default=[]),
    is_global_upload: bool = Form(False),
    replace_filenames: str = Form(""),
    advisor_mode: str = Form("adaptive"),
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
        existing = await find_document_by_filename(fname, resolved_student_id)
        if existing and existing.get("id"):
            await delete_document_cascade(existing["id"], resolved_student_id)
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
                is_global_upload=is_global_upload,
                topic_guard_enabled=_topic_guard_enabled,
                advisor_mode=(advisor_mode if str(advisor_mode or "").strip() else _advisor_mode),
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
                await persist_decision_record(
                    query=query,
                    final_state=final_state,
                    done_payload=done_payload,
                    student_id=resolved_student_id,
                    session_id=session_id,
                )
            except Exception as exc:
                log.warning("Failed to persist decision record for session %s: %s", session_id, exc)
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


@router.get("/profiles", response_model=list[ProfileInfo])
async def get_profiles():
    """List local student profiles."""
    students = await list_students()
    return [_profile_info_from_student(student) for student in students]


@router.post("/profiles", response_model=ProfileInfo)
async def create_profile(body: ProfileCreate):
    """Create a new local student profile."""
    student = await create_student(
        name=body.name,
        email=body.email,
        university=body.university,
        program=body.program,
    )
    return _profile_info_from_student(student)


# ── Document Upload ──────────────────────────────────────────────


@router.get("/documents/check")
async def check_document_exists(filename: str, student_id: Optional[str] = Query(default=None)):
    """Check if a document with this filename already exists in the profile."""
    resolved_student_id = await _resolve_student_id(student_id)
    existing = await find_document_by_filename(filename, resolved_student_id)
    return {"exists": existing is not None, "document": existing}


@router.post("/documents", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    scope: str = Form("global"),
    session_id: Optional[str] = Form(None),
    student_id: Optional[str] = Form(None),
    replace: str = Form("false"),
):
    """Upload a document to the student profile or session."""
    resolved_student_id = await _resolve_student_id(student_id)
    upload = await _read_upload_file(file)

    # If replacing, delete the existing document first
    if replace.lower() == "true":
        existing = await find_document_by_filename(upload["filename"], resolved_student_id)
        if existing and existing.get("id"):
            await delete_document_cascade(existing["id"], resolved_student_id)
            log.info("Replaced existing document: %s", upload["filename"])

    # Process through the registered document ingestion pipeline
    from app.agents.doc_analyst import doc_analyst as process_doc

    state: dict[str, Any] = {
        "files": [upload],
        "session_id": session_id or "",
        "student_id": resolved_student_id,
        "is_global_upload": scope == "global",
        "step_progress": [],
        "plan": [],
    }

    result = await process_doc(state)
    document_roles = result.get("document_roles", []) if isinstance(result.get("document_roles", []), list) else []
    first_role = document_roles[0] if document_roles and isinstance(document_roles[0], dict) else {}
    await maybe_consolidate_memory(resolved_student_id, "document_upload")

    return DocumentUploadResponse(
        document_id=f"doc_uploaded",
        filename=upload["filename"],
        scope=scope,
        document_role=first_role.get("role", "general_document"),
        role_confidence=float(first_role.get("confidence", 0.0) or 0.0),
        entities_extracted=len(result.get("extracted_entities", [])),
        chunks_stored=0,
    )


# ── Profile ──────────────────────────────────────────────────────


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(student_id: Optional[str] = Query(default=None)):
    """Get the student's full profile from the knowledge graph."""
    resolved_student_id = await _resolve_student_id(student_id)
    profile = await get_full_profile(resolved_student_id)
    return ProfileResponse(
        personal=profile.get("personal", {}),
        academic={"courses_count": len(profile.get("courses", []))},
        skills=profile.get("skills", []),
        courses=profile.get("courses", []),
        goals=profile.get("goals", []),
        documents=profile.get("documents", []),
        interests=profile.get("interests", []),
        experience=profile.get("experience", []),
        projects=profile.get("projects", []),
        profile_facts=profile.get("profile_facts", []),
        candidate_fact_ledger=profile.get("candidate_fact_ledger", []),
        completeness_breakdown=profile.get("completeness_breakdown", {}),
        fact_summary=profile.get("fact_summary", {}),
        temporal_profile=profile.get("temporal_profile", {}),
        all_entities=profile.get("all_entities", {}),
        completeness=float(profile.get("completeness", 0.0) or 0.0),
        confidence=_profile_confidence(profile),
        memory_overview=_profile_memory_overview(profile),
    )


@router.put("/profile")
async def update_profile(update: ProfileUpdate):
    """Update a specific profile field."""
    resolved_student_id = await _resolve_student_id(update.student_id)
    result = await update_student(resolved_student_id, **{update.field: update.value})
    return {"updated": True, "data": result}


@router.delete("/profile/entity/{entity_label}/{entity_name}")
async def delete_profile_entity(entity_label: str, entity_name: str, student_id: Optional[str] = Query(default=None)):
    """Delete a specific entity from the profile."""
    resolved_student_id = await _resolve_student_id(student_id)
    if entity_label == "Document":
        # Documents use 'filename', not 'name' — also cascade-delete chunks
        records = await run_cypher(
            "MATCH (s:Student {id: $sid})-[:UPLOADED]->(d:Document {filename: $fname}) RETURN d.id AS doc_id",
            {"fname": entity_name, "sid": resolved_student_id},
        )
        if records and records[0].get("doc_id"):
            deleted = await delete_document_cascade(records[0]["doc_id"], resolved_student_id)
        else:
            deleted = await delete_entity_for_student("Document", {"filename": entity_name}, resolved_student_id)
    else:
        deleted = await delete_entity_for_student(entity_label, {"name": entity_name}, resolved_student_id)
    return {"deleted": deleted}


@router.put("/profile/entity")
async def update_profile_entity(body: EntityUpdate):
    """Update properties on a profile entity (Company, Skill, etc.)."""
    resolved_student_id = await _resolve_student_id(body.student_id)
    result = await update_entity(
        label=body.label,
        match_props={"name": body.name},
        new_props=body.properties,
        student_id=resolved_student_id,
    )
    if not result:
        raise HTTPException(404, f"{body.label} '{body.name}' not found")
    return {"updated": True, "data": result}


@router.delete("/profile/reset")
async def reset_all_profile_data(student_id: Optional[str] = Query(default=None)):
    """Delete ALL student data from the knowledge graph."""
    resolved_student_id = await _resolve_student_id(student_id)
    deleted = await reset_student_data(resolved_student_id)
    return {"deleted": deleted, "message": "All profile data has been reset."}


@router.delete("/settings/delete-all-data")
async def delete_all_data_everywhere():
    """Delete all profiles, graph data, and persisted chat sessions for all profiles."""
    deleted_nodes = await reset_all_data()
    await reset_checkpointer_storage()
    return {
        "deleted_nodes": deleted_nodes,
        "message": "All profiles, Neo4j data, and chat sessions have been deleted.",
    }


@router.post("/profile/text")
async def add_profile_text(input_data: ProfileTextInput, student_id: Optional[str] = Query(default=None)):
    """Process free-text input and add extracted entities to profile."""
    resolved_student_id = await _resolve_student_id(student_id)
    result = await process_free_text(input_data.text, resolved_student_id)
    await maybe_consolidate_memory(resolved_student_id, "profile_text")
    return result


@router.get("/profile/conflicts")
async def get_profile_conflicts(student_id: Optional[str] = Query(default=None)):
    """List unresolved profile-memory conflicts for the active student."""
    resolved_student_id = await _resolve_student_id(student_id)
    return await list_profile_conflicts(resolved_student_id)


@router.post("/profile/conflicts/self-resolve")
async def self_resolve_profile_conflicts(student_id: Optional[str] = Query(default=None)):
    """Auto-resolve obvious profile-memory conflicts for the active student."""
    resolved_student_id = await _resolve_student_id(student_id)
    result = await auto_resolve_profile_conflicts(resolved_student_id)
    return {
        "student_id": resolved_student_id,
        "resolved_count": result.get("resolved_count", 0),
        "superseded_count": result.get("superseded_count", 0),
        "resolved": result.get("resolved_count", 0),
        "superseded": result.get("superseded_count", 0),
        "decisions": result.get("decisions", []),
        "remaining_conflicts": result.get("remaining_conflicts", 0),
    }


@router.post("/profile/conflicts/resolve")
async def resolve_profile_conflict(body: ConflictChoiceRequest):
    """Apply a user-selected conflict resolution."""
    resolved_student_id = await _resolve_student_id(body.student_id)
    return await resolve_conflict_choice(
        student_id=resolved_student_id,
        conflict_id=body.conflict_id,
        fact_type=body.fact_type,
        action=body.action,
        selected_value=body.selected_value,
    )


@router.get("/profile/graph", response_model=GraphDataResponse)
async def get_profile_graph(student_id: Optional[str] = Query(default=None)):
    """Get knowledge graph data for visualization."""
    resolved_student_id = await _resolve_student_id(student_id)
    data = await get_graph_data(resolved_student_id)
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


@router.get("/replays/{replay_id}/evaluate", response_model=ReplayEvaluationInfo)
async def evaluate_replay(replay_id: str):
    """Evaluate one replay artifact with lightweight regression checks."""
    evaluation = evaluate_replay_by_id(replay_id)
    if evaluation is None:
        raise HTTPException(404, "Replay artifact not found")
    return ReplayEvaluationInfo(**evaluation)


@router.get("/replays/evaluate/recent", response_model=ReplayEvaluationBatch)
async def evaluate_recent_replay_batch(
    limit: int = Query(default=25, ge=1, le=100),
    student_id: Optional[str] = Query(default=None),
):
    """Evaluate a batch of recent replay artifacts."""
    resolved_student_id = None
    if student_id:
        resolved_student_id = await _resolve_student_id(student_id)
    evaluation = evaluate_recent_replays(limit=limit, student_id=resolved_student_id)
    return ReplayEvaluationBatch(**evaluation)


@router.get("/eval/benchmarks", response_model=list[EvalBenchmarkInfo])
async def get_eval_benchmarks():
    """List benchmark datasets available for continuous evaluation."""
    return [EvalBenchmarkInfo(**item) for item in list_benchmark_sets()]


@router.get("/eval/analytics", response_model=EvalAnalyticsResponse)
async def get_eval_analytics(
    limit: int = Query(default=50, ge=1, le=200),
    student_id: Optional[str] = Query(default=None),
):
    """Return grouped replay analytics, benchmark coverage, and trend summary."""
    resolved_student_id = None
    if student_id:
        resolved_student_id = await _resolve_student_id(student_id)
    analytics = build_eval_analytics(limit=limit, student_id=resolved_student_id)
    return EvalAnalyticsResponse(**analytics)


@router.get("/recommendations", response_model=list[SavedRecommendationInfo])
async def get_saved_recommendations(student_id: Optional[str] = Query(default=None)):
    """List saved plans and recommendations for the active profile."""
    resolved_student_id = await _resolve_student_id(student_id)
    items = await list_saved_recommendations(resolved_student_id)
    return [
        _saved_recommendation_info_from_record(item, fallback_student_id=resolved_student_id)
        for item in items
    ]


@router.post("/recommendations", response_model=SavedRecommendationInfo)
async def save_recommendation(body: SavedRecommendationCreate):
    """Save a recommendation or plan explicitly."""
    resolved_student_id = await _resolve_student_id(body.student_id)
    stored = await store_memory_item(
        resolved_student_id,
        f"saved_{body.recommendation_type}",
        body.summary,
        source_ref=body.source_session_id or "manual",
        confidence=0.8,
        salience=0.85,
        status="resolved",
        time_scope="long_term",
        tags=[body.recommendation_type, "saved"],
        metadata={
            **body.metadata,
            "title": body.title,
            "actions": body.actions,
            "source_session_id": body.source_session_id,
            "source_query": body.source_query,
        },
    )
    return _saved_recommendation_info_from_record(
        stored,
        fallback_student_id=resolved_student_id,
        default_title=body.title,
        default_recommendation_type=body.recommendation_type,
        default_actions=body.actions,
        default_source_session_id=body.source_session_id,
        default_source_query=body.source_query,
    )


@router.put("/recommendations/{recommendation_id}/outcome", response_model=SavedRecommendationInfo)
async def update_recommendation_outcome(recommendation_id: str, body: SavedRecommendationOutcomeUpdate):
    """Update outcome/feedback for a saved recommendation."""
    resolved_student_id = await _resolve_student_id(body.student_id)
    stored = await update_saved_recommendation_outcome(
        resolved_student_id,
        recommendation_id,
        outcome_status=body.outcome_status,
        outcome_notes=body.outcome_notes,
        next_review_at=body.next_review_at,
        follow_up_prompt=body.follow_up_prompt,
        metadata_patch=body.metadata,
    )
    if not stored:
        raise HTTPException(404, "Saved recommendation not found")
    return _saved_recommendation_info_from_record(stored, fallback_student_id=resolved_student_id)


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, student_id: Optional[str] = Query(default=None)):
    """Delete a chat session and its session-scoped documents."""
    resolved_student_id = await _resolve_student_id(student_id)
    # Delete session-scoped documents from Neo4j
    await execute_cypher(
        """
        MATCH (s:Student {id: $student_id})-[:UPLOADED]->(d:Document {session_id: $sid, scope: 'session'})
        OPTIONAL MATCH (c:Chunk)-[:FROM_DOCUMENT]->(d)
        DETACH DELETE c, d
        """,
        {"sid": session_id, "student_id": resolved_student_id},
    )
    return {"deleted": True, "session_id": session_id, "student_id": resolved_student_id}


@router.put("/sessions/{session_id}/promote-doc")
async def promote_session_doc(session_id: str, document_id: str = Form(...), student_id: Optional[str] = Form(default=None)):
    """Promote a session document to global scope."""
    resolved_student_id = await _resolve_student_id(student_id)
    promoted = await promote_document_to_global(document_id, resolved_student_id)
    return {"promoted": promoted, "document_id": document_id}


# ── Settings ─────────────────────────────────────────────────────


@router.get("/settings", response_model=SettingsResponse)
async def get_settings():
    """Get current application settings."""
    return SettingsResponse(
        topic_guard_enabled=_topic_guard_enabled,
        advisor_mode=_advisor_mode,
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
    global _topic_guard_enabled, _advisor_mode
    if update.topic_guard_enabled is not None:
        _topic_guard_enabled = update.topic_guard_enabled
    if update.advisor_mode is not None:
        _advisor_mode = str(update.advisor_mode or "adaptive").strip().lower() or "adaptive"
    return {"updated": True, "topic_guard_enabled": _topic_guard_enabled, "advisor_mode": _advisor_mode}


# ── Health ───────────────────────────────────────────────────────


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Check system health: Neo4j, LM Studio, Ollama."""
    statuses = await get_dependency_status()
    neo4j_status = statuses.get("neo4j", "unknown")
    lm_studio_status = statuses.get("llm", "unknown")
    ollama_status = statuses.get("embeddings", "unknown")

    overall = "ok" if all(
        s == "connected" for s in [neo4j_status, lm_studio_status, ollama_status]
    ) else "degraded"

    return HealthResponse(
        status=overall,
        neo4j=neo4j_status,
        lm_studio=lm_studio_status,
        ollama=ollama_status,
    )


@router.get("/background/status")
async def background_status():
    """Get lightweight background-job status for observability."""
    return get_background_status()


# ── Helpers ──────────────────────────────────────────────────────


async def _resolve_student_id(student_id: str | None, create_if_missing: bool = True) -> str:
    """Resolve the active student profile, creating a runtime ID if needed."""
    if student_id:
        if create_if_missing:
            await ensure_student(student_id)
        return student_id
    if not create_if_missing:
        return ""
    runtime_student_id = generate_student_id()
    await ensure_student(runtime_student_id)
    return runtime_student_id
