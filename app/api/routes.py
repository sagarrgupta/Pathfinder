"""API endpoints for Pathfinder."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from app.adapters.neo4j.graph_store import (
    apply_conflict_choice,
    create_student,
    delete_document_cascade,
    delete_entity,
    ensure_student,
    get_student,
    find_document_by_filename,
    get_full_profile,
    get_graph_data,
    list_saved_recommendations,
    list_students,
    promote_document_to_global,
    reset_student_data,
    run_cypher,
    store_memory_item,
    update_entity,
    update_student,
)
from app.config.settings import settings
from app.core.graph import get_compiled_graph
from app.schemas.models import (
    ConflictAutoResolveResponse,
    ConflictChoiceRequest,
    ConflictOption,
    DocumentUploadResponse,
    EntityUpdate,
    GraphDataResponse,
    HealthResponse,
    ProfileConflictInfo,
    ProfileCreate,
    ProfileInfo,
    ProfileResponse,
    ProfileTextInput,
    ProfileUpdate,
    SavedRecommendationCreate,
    SavedRecommendationInfo,
    SettingsResponse,
    SettingsUpdate,
)
from app.services.consolidation import maybe_consolidate_memory
from app.services.conflict_autoresolve import auto_resolve_profile_conflicts, list_profile_conflicts
from app.services.background_jobs import get_background_status
from app.services.memory_ingestion import ingest_memory
from app.utils.ids import generate_session_id

log = logging.getLogger("pathfinder.api")

router = APIRouter()
_topic_guard_enabled: bool = settings.TOPIC_GUARD_ENABLED


def _infer_confidence_score(state: dict[str, Any]) -> float:
    """Provide a conservative fallback confidence when a path skips explicit scoring."""
    raw = state.get("confidence_score")
    try:
        confidence = float(raw)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence > 0:
        return max(0.0, min(1.0, confidence))

    profile_data = state.get("profile_data") or {}
    personal = profile_data.get("personal") or {}
    memory_pack = state.get("memory_pack") or {}
    retrieval_summary = state.get("retrieval_summary") or {}
    has_personal = any(personal.get(key) for key in ("name", "program", "university", "gpa", "semester", "email"))
    has_candidate_facts = bool((state.get("semantic_memory") or {}).get("candidate_facts")) or bool(
        retrieval_summary.get("candidate_facts")
    )
    has_documents = bool(state.get("retrieved_documents")) or bool(retrieval_summary.get("documents"))
    has_citations = bool(state.get("citations"))
    grounded = bool(state.get("is_grounded", True))
    intent = str(state.get("intent") or "").lower()
    task_type = str(state.get("task_type") or "").lower()

    if intent == "profile" and task_type == "summarize" and ("gpa" in str(state.get("query", "")).lower()):
        if personal.get("gpa"):
            return 0.95 if has_documents or has_citations else 0.88

    score = 0.35
    if grounded:
        score += 0.1
    if has_personal:
        score += 0.15
    if has_candidate_facts:
        score += 0.15
    if has_documents:
        score += 0.15
    if has_citations:
        score += 0.1
    if memory_pack.get("conflicts"):
        score -= 0.1
    if state.get("missing_info"):
        score -= 0.08
    return round(max(0.35, min(0.92, score)), 2)


async def _resolve_student_id(student_id: str | None, create_if_missing: bool = True) -> str:
    """Resolve active student profile, creating one if needed on first run."""
    if student_id:
        if create_if_missing:
            await ensure_student(student_id)
        return student_id
    students = await list_students()
    if students:
        resolved = students[0]["id"]
        if create_if_missing:
            await ensure_student(resolved)
        return resolved
    if not create_if_missing:
        return ""
    created = await create_student("Student")
    return created["id"]


@router.get("/profiles", response_model=list[ProfileInfo])
async def get_profiles():
    """List local student profiles."""
    students = await list_students()
    return [
        ProfileInfo(
            student_id=student["id"],
            name=student.get("name", "Student"),
            email=student.get("email"),
            university=student.get("university"),
            program=student.get("program"),
            created_at=student.get("created_at"),
            updated_at=student.get("updated_at"),
            completeness=student.get("completeness", 0.0),
        )
        for student in students
    ]


@router.post("/profiles", response_model=ProfileInfo)
async def create_profile(body: ProfileCreate):
    """Create a new local profile."""
    student = await create_student(body.name, body.email, body.university, body.program)
    return ProfileInfo(
        student_id=student["id"],
        name=student.get("name", body.name),
        email=student.get("email"),
        university=student.get("university"),
        program=student.get("program"),
        created_at=student.get("created_at"),
        updated_at=student.get("updated_at"),
        completeness=0.0,
    )


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

    replace_set = set(name.strip() for name in replace_filenames.split(",") if name.strip())
    for fname in replace_set:
        existing = await find_document_by_filename(fname, resolved_student_id)
        if existing and existing.get("id"):
            await delete_document_cascade(existing["id"], resolved_student_id)

    file_data = []
    for f in files:
        content = await f.read()
        if len(content) > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
            raise HTTPException(413, f"File {f.filename} exceeds {settings.MAX_FILE_SIZE_MB}MB limit")
        file_data.append(
            {
                "filename": f.filename,
                "content": content,
                "size": len(content),
                "content_type": f.content_type,
            }
        )

    async def event_stream():
        try:
            graph = await get_compiled_graph()
            initial_state: dict[str, Any] = {
                "messages": [("human", query)],
                "query": query,
                "files": file_data,
                "session_id": session_id,
                "student_id": resolved_student_id,
                "is_global_upload": is_global_upload,
                "topic_guard_enabled": _topic_guard_enabled,
                "interpreted_query": "",
                "interpreted_goal": "",
                "interpreted_constraints": [],
                "interpreted_search_brief": "",
                "interpretation_notes": "",
                "step_progress": [],
                "citations": [],
                "plan": [],
                "next_node": "",
                "intent": "",
                "task_type": "",
                "reasoning_depth": "standard",
                "needs_web": False,
                "needs_documents": False,
                "needs_profile": True,
                "planner_trace": [],
                "active_capabilities": [],
                "answer_style": "composed",
                "missing_info": [],
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
                "web_search_hint": "",
                "graph_results": [],
                "profile_data": {},
                "semantic_memory": {},
                "memory_pack": {},
                "conflicts": [],
                "recommended_actions": [],
                "retrieval_sources": [],
                "retrieval_summary": {},
                "answer_rationale": [],
                "consolidation_summary": {},
                "conflict_nudges": [],
                "execution_trace": [],
            }
            config = {"configurable": {"thread_id": f"{resolved_student_id}:{session_id}"}, "recursion_limit": 40}

            last_progress_count = 0
            final_state = {}
            async for event in graph.astream(initial_state, config=config):
                for node_name, state_update in event.items():
                    final_state.update(state_update)
                    progress = state_update.get("step_progress", [])
                    if len(progress) > last_progress_count:
                        for msg in progress[last_progress_count:]:
                            yield f"event: progress\ndata: {json.dumps({'node': node_name, 'message': msg})}\n\n"
                        last_progress_count = len(progress)

            final_answer = final_state.get("final_answer", "I couldn't generate a response.")
            confidence = _infer_confidence_score(final_state)
            citations = final_state.get("citations", [])
            metadata = {
                "method": _determine_method(final_state),
                "rationale": final_state.get("answer_rationale", []),
                "sources": final_state.get("retrieval_sources", []),
                "student_id": resolved_student_id,
                "recommended_actions": final_state.get("recommended_actions", []),
                "planner_trace": final_state.get("planner_trace", []),
                "missing_info": final_state.get("missing_info", []),
                "conflicts": final_state.get("conflicts", []),
                "conflict_nudges": final_state.get("conflict_nudges", []),
                "retrieval_summary": final_state.get("retrieval_summary", {}),
                "consolidation_summary": final_state.get("consolidation_summary", {}),
                "execution_trace": final_state.get("execution_trace", []),
            }
            for word in final_answer.split(" "):
                yield f"event: token\ndata: {json.dumps({'content': word + ' '})}\n\n"
            yield (
                "event: done\ndata: "
                + json.dumps(
                    {
                        "session_id": session_id,
                        "student_id": resolved_student_id,
                        "confidence": confidence,
                        "citations": citations,
                        "metadata": metadata,
                        "method": metadata["method"],
                    }
                )
                + "\n\n"
            )
        except Exception as exc:
            log.error("Chat error: %s", exc, exc_info=True)
            yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/conflicts/resolve")
async def resolve_conflict(body: ConflictChoiceRequest):
    """Apply a user-selected action to a conflict nudge."""
    resolved_student_id = await _resolve_student_id(body.student_id)
    if body.action not in {"choose_value", "keep_both", "ask_later"}:
        raise HTTPException(400, "Unsupported conflict action")
    if body.action == "choose_value" and not (body.selected_value or "").strip():
        raise HTTPException(400, "selected_value is required for choose_value")

    result = await apply_conflict_choice(
        student_id=resolved_student_id,
        conflict_id=body.conflict_id,
        fact_type=body.fact_type,
        action=body.action,
        selected_value=body.selected_value,
    )
    return {"ok": True, "student_id": resolved_student_id, **result}


@router.get("/profile/conflicts", response_model=list[ProfileConflictInfo])
async def get_profile_conflicts(student_id: Optional[str] = Query(default=None)):
    """List grouped unresolved profile conflicts for the active student."""
    resolved_student_id = await _resolve_student_id(student_id, create_if_missing=not bool(student_id))
    if not resolved_student_id:
        return []

    existing_student = await get_student(resolved_student_id)
    if not existing_student:
        return []

    grouped = await list_profile_conflicts(resolved_student_id)
    return [
        ProfileConflictInfo(
            id=item.get("id") or "",
            fact_type=item.get("fact_type", "profile_detail"),
            message=item.get("message", ""),
            current_option=item.get("summary", {}).get("current_option", item.get("value", "")),
            other_options=item.get("summary", {}).get("other_options", []),
            question=item.get("summary", {}).get("question", ""),
            options=[
                ConflictOption(
                    action=option.get("action", ""),
                    label=option.get("label", ""),
                    value=option.get("value"),
                )
                for option in item.get("options", [])
            ],
            confidence=float(item.get("confidence", 0.0) or 0.0),
        )
        for item in grouped
        if item.get("id")
    ]


@router.post("/profile/conflicts/self-resolve", response_model=ConflictAutoResolveResponse)
async def self_resolve_profile_conflicts(student_id: Optional[str] = Query(default=None)):
    """Attempt conservative self-resolution for grouped profile conflicts."""
    resolved_student_id = await _resolve_student_id(student_id, create_if_missing=not bool(student_id))
    if not resolved_student_id:
        return ConflictAutoResolveResponse(student_id="", resolved_count=0, unresolved_count=0)

    existing_student = await get_student(resolved_student_id)
    if not existing_student:
        return ConflictAutoResolveResponse(student_id=resolved_student_id, resolved_count=0, unresolved_count=0)

    result = await auto_resolve_profile_conflicts(resolved_student_id)
    return ConflictAutoResolveResponse(**result)


@router.get("/documents/check")
async def check_document_exists(filename: str, student_id: Optional[str] = Query(default=None)):
    """Check whether a document exists for the active profile."""
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
    """Upload a document to the active profile."""
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

    if replace.lower() == "true":
        existing = await find_document_by_filename(file.filename, resolved_student_id)
        if existing and existing.get("id"):
            await delete_document_cascade(existing["id"], resolved_student_id)

    from app.agents.doc_analyst import doc_analyst as process_doc

    state: dict[str, Any] = {
        "files": [
            {
                "filename": file.filename,
                "content": content,
                "size": len(content),
                "content_type": file.content_type,
            }
        ],
        "session_id": session_id or "",
        "student_id": resolved_student_id,
        "is_global_upload": scope == "global",
        "step_progress": [],
        "plan": [],
        "retrieval_sources": [],
    }
    result = await process_doc(state)
    await maybe_consolidate_memory(resolved_student_id, "document_upload")
    return DocumentUploadResponse(
        document_id="doc_uploaded",
        filename=file.filename,
        scope=scope,
        entities_extracted=len(result.get("extracted_entities", [])),
        chunks_stored=len(result.get("retrieved_documents", [])),
    )


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(student_id: Optional[str] = Query(default=None)):
    """Get the active student's full profile."""
    resolved_student_id = await _resolve_student_id(student_id, create_if_missing=not bool(student_id))
    if not resolved_student_id:
        profile = {
            "personal": {},
            "courses": [],
            "skills": [],
            "goals": [],
            "documents": [],
            "interests": [],
            "experience": [],
            "projects": [],
            "all_entities": {},
            "candidate_facts": [],
            "memory_items": [],
            "evidence": [],
        }
    else:
        existing_student = await get_student(resolved_student_id)
        if not existing_student:
            profile = {
                "personal": {},
                "courses": [],
                "skills": [],
                "goals": [],
                "documents": [],
                "interests": [],
                "experience": [],
                "projects": [],
                "all_entities": {},
                "candidate_facts": [],
                "memory_items": [],
                "evidence": [],
            }
        else:
            profile = await get_full_profile(resolved_student_id)
    completeness_fields = [
        profile.get("personal", {}).get("name"),
        profile.get("personal", {}).get("university"),
        profile.get("personal", {}).get("program"),
        profile.get("personal", {}).get("gpa"),
        profile.get("personal", {}).get("semester"),
        profile.get("personal", {}).get("email"),
        bool(profile.get("skills")),
        bool(profile.get("goals")),
        bool(profile.get("documents")),
    ]
    completeness = round(sum(1 for field in completeness_fields if field) / len(completeness_fields), 2)
    candidate_facts = profile.get("candidate_facts", [])
    resolved_candidates = [item for item in candidate_facts if item.get("status") == "resolved"]
    confidence_values = [float(item.get("confidence", 0.0)) for item in resolved_candidates] or [
        float(item.get("confidence", 0.0)) for item in candidate_facts
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
        completeness=completeness,
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
async def delete_profile_entity(
    entity_label: str, entity_name: str, student_id: Optional[str] = Query(default=None)
):
    """Delete a specific entity from the active profile."""
    resolved_student_id = await _resolve_student_id(student_id)
    if entity_label == "Document":
        records = await run_cypher(
            """
            MATCH (s:Student {id: $sid})-[:UPLOADED]->(d:Document {filename: $fname})
            RETURN d.id AS doc_id
            LIMIT 1
            """,
            {"sid": resolved_student_id, "fname": entity_name},
        )
        if records and records[0].get("doc_id"):
            deleted = await delete_document_cascade(records[0]["doc_id"], resolved_student_id)
        else:
            deleted = False
    else:
        deleted = await delete_entity(entity_label, {"name": entity_name}, resolved_student_id)
    return {"deleted": deleted}


@router.put("/profile/entity")
async def update_profile_entity(body: EntityUpdate):
    """Update properties on a profile entity."""
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
    """Delete all data for the active profile."""
    resolved_student_id = await _resolve_student_id(student_id)
    deleted = await reset_student_data(resolved_student_id)
    return {"deleted": deleted, "message": "All profile data has been reset."}


@router.post("/profile/text")
async def add_profile_text(
    input_data: ProfileTextInput, student_id: Optional[str] = Query(default=None)
):
    """Process free-text input through the shared memory-ingestion service."""
    resolved_student_id = await _resolve_student_id(student_id)
    result = await ingest_memory(
        student_id=resolved_student_id,
        source_type="profile_text",
        content=input_data.text,
        metadata={"entrypoint": "profile_text"},
    )
    await maybe_consolidate_memory(resolved_student_id, "profile_text")
    return {
        "entities_extracted": len(result.get("candidate_facts", []))
        + len(result.get("promoted_entities", [])),
        "student_properties_updated": bool(result.get("student_updates")),
        "memory_items_created": len(result.get("memory_items", [])),
    }


@router.get("/profile/graph", response_model=GraphDataResponse)
async def get_profile_graph(student_id: Optional[str] = Query(default=None)):
    """Get knowledge graph data for visualization."""
    resolved_student_id = await _resolve_student_id(student_id)
    data = await get_graph_data(resolved_student_id)
    return GraphDataResponse(nodes=data["nodes"], relationships=data["relationships"])


@router.get("/sessions")
async def list_sessions(student_id: Optional[str] = Query(default=None)):
    """List sessions for an active profile.

    Session metadata remains frontend-local in v1, so this endpoint is advisory.
    """
    resolved_student_id = await _resolve_student_id(student_id)
    return {"student_id": resolved_student_id, "sessions": []}


@router.get("/recommendations", response_model=list[SavedRecommendationInfo])
async def get_saved_recommendations(student_id: Optional[str] = Query(default=None)):
    """List saved plans and recommendations for the active profile."""
    resolved_student_id = await _resolve_student_id(student_id)
    items = await list_saved_recommendations(resolved_student_id)
    return [
        SavedRecommendationInfo(
            id=item["id"],
            student_id=item["student_id"],
            title=item.get("metadata", {}).get("title") or item.get("summary", "Saved recommendation"),
            summary=item.get("summary", ""),
            recommendation_type=item.get("memory_type", "saved_plan").replace("saved_", ""),
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
        id=stored["id"],
        student_id=stored["student_id"],
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
    """Delete a chat session's session-scoped documents."""
    resolved_student_id = await _resolve_student_id(student_id)
    await run_cypher(
        """
        MATCH (s:Student {id: $sid})-[:UPLOADED]->(d:Document {session_id: $session_id, scope: 'session'})
        OPTIONAL MATCH (c:Chunk)-[:FROM_DOCUMENT]->(d)
        DETACH DELETE c, d
        """,
        {"sid": resolved_student_id, "session_id": session_id},
    )
    return {"deleted": True, "session_id": session_id, "student_id": resolved_student_id}


@router.put("/sessions/{session_id}/promote-doc")
async def promote_session_doc(
    session_id: str,
    document_id: str = Form(...),
    student_id: Optional[str] = Form(default=None),
):
    """Promote a session document to global scope."""
    resolved_student_id = await _resolve_student_id(student_id)
    promoted = await promote_document_to_global(document_id, resolved_student_id)
    return {"promoted": promoted, "document_id": document_id, "session_id": session_id}


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


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Check system health and basic profile availability."""
    import httpx
    from app.adapters.neo4j.graph_store import get_driver

    statuses = {"neo4j": "unknown", "lm_studio": "unknown", "ollama": "unknown"}

    try:
        driver = await get_driver()
        async with driver.session() as session:
            await session.run("RETURN 1")
        statuses["neo4j"] = "connected"
    except Exception:
        statuses["neo4j"] = "disconnected"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.LLM_BASE_URL.replace('/v1', '')}/v1/models")
            statuses["lm_studio"] = "connected" if resp.status_code == 200 else "error"
    except Exception:
        statuses["lm_studio"] = "disconnected"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.OLLAMA_URL}/api/tags")
            statuses["ollama"] = "connected" if resp.status_code == 200 else "error"
    except Exception:
        statuses["ollama"] = "disconnected"

    overall = "ok" if all(v == "connected" for v in statuses.values()) else "degraded"
    return HealthResponse(
        status=overall,
        **statuses,
        version=settings.API_VERSION,
        background_jobs=get_background_status(),
    )


def _determine_method(state: dict[str, Any]) -> str:
    """Summarize which source categories influenced the answer."""
    methods = []
    if state.get("retrieval_sources"):
        methods.extend(state["retrieval_sources"])
    if state.get("retrieved_documents") and "documents" not in methods:
        methods.append("documents")
    if state.get("web_results") and "web" not in methods:
        methods.append("web")
    return "+".join(dict.fromkeys(methods)) if methods else "direct"
