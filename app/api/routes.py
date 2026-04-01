"""API endpoints for Pathfinder.

All routes prefixed with /api/v1 (set in main.py).
"""

from __future__ import annotations

import json
import logging
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
    store_memory_item,
    update_entity,
    update_student,
)
from app.agents.profile_manager import process_free_text
from app.config.settings import settings
from app.core.graph import get_compiled_graph
from app.core.memory import reset_checkpointer_storage
from app.core.quality import build_task_graph, infer_quality_path, summarize_trace
from app.core.state import PathfinderState
from app.services.conflict_autoresolve import (
    auto_resolve_profile_conflicts,
    list_profile_conflicts,
    resolve_conflict_choice,
)
from app.services.consolidation import maybe_consolidate_memory
from app.services.background_jobs import get_background_status
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
    SessionInfo,
    SavedRecommendationCreate,
    SavedRecommendationInfo,
    SettingsResponse,
    SettingsUpdate,
)
from app.utils.ids import generate_session_id, generate_student_id

log = logging.getLogger("pathfinder.api")

router = APIRouter()

# ── Runtime state ────────────────────────────────────────────────
_topic_guard_enabled: bool = settings.TOPIC_GUARD_ENABLED


# ── Chat (SSE Streaming) ────────────────────────────────────────


@router.post("/chat")
async def chat(
    query: str = Form(...),
    session_id: Optional[str] = Form(None),
    student_id: Optional[str] = Form(None),
    files: list[UploadFile] = File(default=[]),
    is_global_upload: bool = Form(False),
    replace_filenames: str = Form(""),
):
    """Main chat endpoint with SSE streaming."""
    resolved_student_id = await _resolve_student_id(student_id)
    if not session_id:
        session_id = generate_session_id()

    # Parse replace filenames (comma-separated list of filenames to replace)
    replace_set = set(
        name.strip() for name in replace_filenames.split(",") if name.strip()
    )

    # Delete existing documents that are being replaced
    for fname in replace_set:
        existing = await find_document_by_filename(fname, resolved_student_id)
        if existing and existing.get("id"):
            await delete_document_cascade(existing["id"], resolved_student_id)
            log.info("Chat: replaced existing document before re-upload: %s", fname)

    # Read uploaded files
    file_data = []
    for f in files:
        content = await f.read()
        if len(content) > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
            raise HTTPException(413, f"File {f.filename} exceeds {settings.MAX_FILE_SIZE_MB}MB limit")
        file_data.append({
            "filename": f.filename,
            "content": content,
            "size": len(content),
            "content_type": f.content_type,
        })

    async def event_stream():
        try:
            graph = await get_compiled_graph()
            dependency_status = await _dependency_status()

            # Reset ALL computed state fields to prevent stale data from
            # previous turns leaking via the checkpointer.
            initial_state: dict[str, Any] = {
                "messages": [("human", query)],
                "query": query,
                "files": file_data,
                "session_id": session_id,
                "student_id": resolved_student_id,
                "is_global_upload": is_global_upload,
                "topic_guard_enabled": _topic_guard_enabled,
                "step_progress": [],
                "citations": [],
                # ── Reset stale orchestrator/agent fields ──
                "plan": [],
                "next_node": "",
                "intent": "",
                "missing_info": [],
                "session_summary": {},
                "workflow": "",
                "target_entity": {},
                "source_policy": {},
                "task_graph": [],
                "working_memory": {},
                "handoff_notes": [],
                "compacted_session": {},
                "source_audit": [],
                "dependency_status": dependency_status,
                "blocked_reasons": [],
                "stop_reason": "",
                "trace_summary": {},
                "short_memory_policy": {},
                "draft_answer": "",
                "final_answer": "",
                "is_blocked": False,
                "block_reason": "",
                "confidence_score": 0.0,
                "is_grounded": True,
                "profile_updates": [],
                "extracted_entities": [],
                "retrieved_documents": [],
                "web_results": [],
                "graph_results": [],
                "profile_data": {},
                "semantic_memory": {},
                "memory_pack": {},
                "latest_ingestion_result": {},
                "conflicts": [],
                "evidence_records": [],
                "decision_payload": {},
            }

            config = {
                "configurable": {"thread_id": f"{resolved_student_id}:{session_id}"},
                "recursion_limit": 15,  # Safeguard: max 15 node executions per turn
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
            final_answer = final_state.get("final_answer", "I couldn't generate a response.")
            confidence = final_state.get("confidence_score", 0.5)
            citations = final_state.get("citations", [])
            trace_summary = final_state.get("trace_summary") or summarize_trace(final_state)

            # Stream tokens (simulate word-by-word for UX)
            words = final_answer.split(" ")
            for word in words:
                yield f"event: token\ndata: {json.dumps({'content': word + ' '})}\n\n"

            # Done event
            yield f"event: done\ndata: {json.dumps({'session_id': session_id, 'student_id': resolved_student_id, 'confidence': confidence, 'citations': citations, 'method': _determine_method(final_state), 'quality_path': infer_quality_path(final_state), 'trace_summary': trace_summary, 'blocked_reasons': final_state.get('blocked_reasons', []), 'dependency_status': final_state.get('dependency_status', dependency_status), 'stop_reason': final_state.get('stop_reason', '')})}\n\n"

        except Exception as exc:
            log.error("Chat error: %s", exc, exc_info=True)
            yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/profiles", response_model=list[ProfileInfo])
async def get_profiles():
    """List local student profiles."""
    students = await list_students()
    return [
        ProfileInfo(
            student_id=student.get("id", ""),
            name=student.get("name", "Student"),
            email=student.get("email"),
            university=student.get("university"),
            program=student.get("program"),
            created_at=student.get("created_at"),
            updated_at=student.get("updated_at"),
            completeness=float(student.get("completeness", 0.0) or 0.0),
        )
        for student in students
    ]


@router.post("/profiles", response_model=ProfileInfo)
async def create_profile(body: ProfileCreate):
    """Create a new local student profile."""
    student = await create_student(
        name=body.name,
        email=body.email,
        university=body.university,
        program=body.program,
    )
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
    import os
    resolved_student_id = await _resolve_student_id(student_id)

    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {settings.MAX_FILE_SIZE_MB}MB limit")

    if not file.filename:
        raise HTTPException(400, "Filename is required")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in settings.ALLOWED_FILE_TYPES:
        allowed = ", ".join(settings.ALLOWED_FILE_TYPES)
        raise HTTPException(400, f"Unsupported file type '{ext}'. Allowed: {allowed}")

    # If replacing, delete the existing document first
    if replace.lower() == "true":
        existing = await find_document_by_filename(file.filename, resolved_student_id)
        if existing and existing.get("id"):
            await delete_document_cascade(existing["id"], resolved_student_id)
            log.info("Replaced existing document: %s", file.filename)

    # Process through doc_analyst directly
    from app.agents.doc_analyst import doc_analyst as process_doc

    state: dict[str, Any] = {
        "files": [{"filename": file.filename, "content": content, "size": len(content), "content_type": file.content_type}],
        "session_id": session_id or "",
        "student_id": resolved_student_id,
        "is_global_upload": scope == "global",
        "step_progress": [],
        "plan": [],
    }

    result = await process_doc(state)
    await maybe_consolidate_memory(resolved_student_id, "document_upload")

    return DocumentUploadResponse(
        document_id=f"doc_uploaded",
        filename=file.filename,
        scope=scope,
        entities_extracted=len(result.get("extracted_entities", [])),
        chunks_stored=0,
    )


# ── Profile ──────────────────────────────────────────────────────


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(student_id: Optional[str] = Query(default=None)):
    """Get the student's full profile from the knowledge graph."""
    resolved_student_id = await _resolve_student_id(student_id)
    profile = await get_full_profile(resolved_student_id)
    candidate_facts = profile.get("candidate_facts", [])
    resolved_candidates = [item for item in candidate_facts if item.get("status") == "resolved"]
    confidence_values = [float(item.get("confidence", 0.0) or 0.0) for item in resolved_candidates] or [
        float(item.get("confidence", 0.0) or 0.0) for item in candidate_facts
    ]
    confidence = round(sum(confidence_values) / len(confidence_values), 2) if confidence_values else 0.0
    memory_overview = {
        "candidate_facts": len(profile.get("candidate_facts", [])),
        "memory_items": len(profile.get("memory_items", [])),
        "evidence": len(profile.get("evidence", [])),
        "conflicts": len([item for item in profile.get("candidate_facts", []) if item.get("status") == "conflicted"]),
    }
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
        all_entities=profile.get("all_entities", {}),
        completeness=float(profile.get("completeness", 0.0) or 0.0),
        confidence=confidence,
        memory_overview=memory_overview,
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


@router.get("/recommendations", response_model=list[SavedRecommendationInfo])
async def get_saved_recommendations(student_id: Optional[str] = Query(default=None)):
    """List saved plans and recommendations for the active profile."""
    resolved_student_id = await _resolve_student_id(student_id)
    items = await list_saved_recommendations(resolved_student_id)
    return [
        SavedRecommendationInfo(
            id=item.get("id", ""),
            student_id=item.get("student_id", resolved_student_id),
            title=item.get("metadata", {}).get("title") or item.get("summary", "Saved recommendation"),
            summary=item.get("summary", ""),
            recommendation_type=str(item.get("memory_type", "saved_plan")).replace("saved_", ""),
            actions=item.get("metadata", {}).get("actions", []),
            source_session_id=item.get("metadata", {}).get("source_session_id"),
            source_query=item.get("metadata", {}).get("source_query"),
            created_at=item.get("created_at"),
            status=item.get("metadata", {}).get("status", "active"),
            next_review_at=item.get("metadata", {}).get("next_review_at"),
            follow_up_prompt=item.get("metadata", {}).get("follow_up_prompt"),
            metadata=item.get("metadata", {}),
        )
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
    return SavedRecommendationInfo(
        id=stored.get("id", ""),
        student_id=stored.get("student_id", resolved_student_id),
        title=body.title,
        summary=stored.get("summary", body.summary),
        recommendation_type=body.recommendation_type,
        actions=body.actions,
        source_session_id=body.source_session_id,
        source_query=body.source_query,
        created_at=stored.get("created_at"),
        status=stored.get("metadata", {}).get("status", "active"),
        next_review_at=stored.get("metadata", {}).get("next_review_at"),
        follow_up_prompt=stored.get("metadata", {}).get("follow_up_prompt"),
        metadata=stored.get("metadata", {}),
    )


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, student_id: Optional[str] = Query(default=None)):
    """Delete a chat session and its session-scoped documents."""
    resolved_student_id = await _resolve_student_id(student_id)
    # Delete session-scoped documents from Neo4j
    await run_cypher(
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
        models={
            "text_llm": settings.LLM_MODEL,
            "vision_llm": settings.VISION_MODEL,
            "embeddings": settings.EMBEDDING_MODEL,
        },
    )


@router.put("/settings")
async def update_settings(update: SettingsUpdate):
    """Update application settings."""
    global _topic_guard_enabled
    if update.topic_guard_enabled is not None:
        _topic_guard_enabled = update.topic_guard_enabled
    return {"updated": True, "topic_guard_enabled": _topic_guard_enabled}


# ── Health ───────────────────────────────────────────────────────


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Check system health: Neo4j, LM Studio, Ollama."""
    statuses = await _dependency_status()
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


def _determine_method(state: dict[str, Any]) -> str:
    """Determine which retrieval methods were used."""
    methods = []
    if state.get("retrieved_documents"):
        methods.append("rag")
    if state.get("profile_data", {}).get("courses"):
        methods.append("graph")
    if state.get("web_results"):
        methods.append("web")
    return "+".join(methods) if methods else "direct"


async def _dependency_status() -> dict[str, str]:
    """Check live dependency health for the current turn."""
    neo4j_status = "unknown"
    llm_status = "unknown"
    embeddings_status = "unknown"
    web_search_status = "unknown"

    try:
        from app.adapters.neo4j.graph_store import get_driver
        driver = await get_driver()
        async with driver.session() as session:
            await session.run("RETURN 1")
        neo4j_status = "connected"
    except Exception:
        neo4j_status = "disconnected"

    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.LLM_BASE_URL.replace('/v1', '')}/v1/models")
            llm_status = "connected" if resp.status_code == 200 else "error"
    except Exception:
        llm_status = "disconnected"

    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.OLLAMA_URL}/api/tags")
            embeddings_status = "connected" if resp.status_code == 200 else "error"
    except Exception:
        embeddings_status = "disconnected"

    web_search_status = "configured" if any([
        settings.TAVILY_API_KEY,
        settings.GOOGLE_CSE_API_KEY,
        settings.BRAVE_API_KEY,
    ]) else "fallback_only"

    return {
        "neo4j": neo4j_status,
        "llm": llm_status,
        "embeddings": embeddings_status,
        "web_search": web_search_status,
    }


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
