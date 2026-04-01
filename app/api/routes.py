"""API endpoints for Pathfinder.

All routes prefixed with /api/v1 (set in main.py).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.adapters.neo4j.graph_store import (
    delete_document_cascade,
    delete_entity,
    ensure_student,
    find_document_by_filename,
    get_full_profile,
    get_graph_data,
    promote_document_to_global,
    reset_student_data,
    run_cypher,
    update_entity,
    update_student,
)
from app.agents.profile_manager import process_free_text
from app.config.settings import settings
from app.core.graph import get_compiled_graph
from app.core.quality import build_task_graph, infer_quality_path, summarize_trace
from app.core.state import PathfinderState
from app.schemas.models import (
    ChatResponse,
    DocumentUploadResponse,
    EntityUpdate,
    GraphDataResponse,
    HealthResponse,
    ProfileResponse,
    ProfileTextInput,
    ProfileUpdate,
    SessionInfo,
    SettingsResponse,
    SettingsUpdate,
)
from app.utils.ids import generate_session_id

log = logging.getLogger("pathfinder.api")

router = APIRouter()

# ── Runtime state ────────────────────────────────────────────────
_topic_guard_enabled: bool = settings.TOPIC_GUARD_ENABLED


# ── Chat (SSE Streaming) ────────────────────────────────────────


@router.post("/chat")
async def chat(
    query: str = Form(...),
    session_id: Optional[str] = Form(None),
    files: list[UploadFile] = File(default=[]),
    is_global_upload: bool = Form(False),
    replace_filenames: str = Form(""),
):
    """Main chat endpoint with SSE streaming."""
    if not session_id:
        session_id = generate_session_id()

    # Parse replace filenames (comma-separated list of filenames to replace)
    replace_set = set(
        name.strip() for name in replace_filenames.split(",") if name.strip()
    )

    # Delete existing documents that are being replaced
    for fname in replace_set:
        existing = await find_document_by_filename(fname, "default")
        if existing and existing.get("id"):
            await delete_document_cascade(existing["id"])
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
                "student_id": "default",
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
                "compacted_session": {},
                "source_audit": [],
                "dependency_status": dependency_status,
                "blocked_reasons": [],
                "stop_reason": "",
                "trace_summary": {},
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
                "evidence_records": [],
                "decision_payload": {},
            }

            config = {
                "configurable": {"thread_id": session_id},
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
            yield f"event: done\ndata: {json.dumps({'session_id': session_id, 'confidence': confidence, 'citations': citations, 'method': _determine_method(final_state), 'quality_path': infer_quality_path(final_state), 'trace_summary': trace_summary, 'blocked_reasons': final_state.get('blocked_reasons', []), 'dependency_status': final_state.get('dependency_status', dependency_status), 'stop_reason': final_state.get('stop_reason', '')})}\n\n"

        except Exception as exc:
            log.error("Chat error: %s", exc, exc_info=True)
            yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── Document Upload ──────────────────────────────────────────────


@router.get("/documents/check")
async def check_document_exists(filename: str):
    """Check if a document with this filename already exists in the profile."""
    existing = await find_document_by_filename(filename, "default")
    return {"exists": existing is not None, "document": existing}


@router.post("/documents", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    scope: str = Form("global"),
    session_id: Optional[str] = Form(None),
    replace: str = Form("false"),
):
    """Upload a document to the student profile or session."""
    import os

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
        existing = await find_document_by_filename(file.filename, "default")
        if existing and existing.get("id"):
            await delete_document_cascade(existing["id"])
            log.info("Replaced existing document: %s", file.filename)

    # Process through doc_analyst directly
    from app.agents.doc_analyst import doc_analyst as process_doc

    state: dict[str, Any] = {
        "files": [{"filename": file.filename, "content": content, "size": len(content), "content_type": file.content_type}],
        "session_id": session_id or "",
        "student_id": "default",
        "is_global_upload": scope == "global",
        "step_progress": [],
        "plan": [],
    }

    result = await process_doc(state)

    return DocumentUploadResponse(
        document_id=f"doc_uploaded",
        filename=file.filename,
        scope=scope,
        entities_extracted=len(result.get("extracted_entities", [])),
        chunks_stored=0,
    )


# ── Profile ──────────────────────────────────────────────────────


@router.get("/profile", response_model=ProfileResponse)
async def get_profile():
    """Get the student's full profile from the knowledge graph."""
    await ensure_student("default")
    profile = await get_full_profile("default")
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
    )


@router.put("/profile")
async def update_profile(update: ProfileUpdate):
    """Update a specific profile field."""
    result = await update_student("default", **{update.field: update.value})
    return {"updated": True, "data": result}


@router.delete("/profile/entity/{entity_label}/{entity_name}")
async def delete_profile_entity(entity_label: str, entity_name: str):
    """Delete a specific entity from the profile."""
    if entity_label == "Document":
        # Documents use 'filename', not 'name' — also cascade-delete chunks
        records = await run_cypher(
            "MATCH (d:Document {filename: $fname}) RETURN d.id AS doc_id",
            {"fname": entity_name},
        )
        if records and records[0].get("doc_id"):
            deleted = await delete_document_cascade(records[0]["doc_id"])
        else:
            # Fallback: try to delete by filename directly
            deleted = await delete_entity("Document", {"filename": entity_name})
    else:
        deleted = await delete_entity(entity_label, {"name": entity_name})
    return {"deleted": deleted}


@router.put("/profile/entity")
async def update_profile_entity(body: EntityUpdate):
    """Update properties on a profile entity (Company, Skill, etc.)."""
    result = await update_entity(
        label=body.label,
        match_props={"name": body.name},
        new_props=body.properties,
    )
    if not result:
        raise HTTPException(404, f"{body.label} '{body.name}' not found")
    return {"updated": True, "data": result}


@router.delete("/profile/reset")
async def reset_all_profile_data():
    """Delete ALL student data from the knowledge graph."""
    deleted = await reset_student_data("default")
    return {"deleted": deleted, "message": "All profile data has been reset."}


@router.post("/profile/text")
async def add_profile_text(input_data: ProfileTextInput):
    """Process free-text input and add extracted entities to profile."""
    result = await process_free_text(input_data.text, "default")
    return result


@router.get("/profile/graph", response_model=GraphDataResponse)
async def get_profile_graph():
    """Get knowledge graph data for visualization."""
    data = await get_graph_data("default")
    return GraphDataResponse(nodes=data["nodes"], relationships=data["relationships"])


# ── Sessions ─────────────────────────────────────────────────────


@router.get("/sessions")
async def list_sessions():
    """List all chat sessions. Returns from SQLite checkpoint metadata."""
    # Note: In a full implementation, we'd query the SQLite checkpointer
    # For now, return an empty list — sessions are created on first chat
    return []


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a chat session and its session-scoped documents."""
    # Delete session-scoped documents from Neo4j
    await run_cypher(
        """
        MATCH (d:Document {session_id: $sid, scope: 'session'})
        OPTIONAL MATCH (c:Chunk)-[:FROM_DOCUMENT]->(d)
        DETACH DELETE c, d
        """,
        {"sid": session_id},
    )
    return {"deleted": True, "session_id": session_id}


@router.put("/sessions/{session_id}/promote-doc")
async def promote_session_doc(session_id: str, document_id: str = Form(...)):
    """Promote a session document to global scope."""
    promoted = await promote_document_to_global(document_id)
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
