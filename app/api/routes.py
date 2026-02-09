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
    get_full_profile,
    get_graph_data,
    promote_document_to_global,
    reset_student_data,
    run_cypher,
    update_student,
)
from app.agents.profile_manager import process_free_text
from app.config.settings import settings
from app.core.graph import get_compiled_graph
from app.core.state import PathfinderState
from app.schemas.models import (
    ChatResponse,
    DocumentUploadResponse,
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
):
    """Main chat endpoint with SSE streaming."""
    if not session_id:
        session_id = generate_session_id()

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
            }

            config = {"configurable": {"thread_id": session_id}}

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

            # Stream tokens (simulate word-by-word for UX)
            words = final_answer.split(" ")
            for word in words:
                yield f"event: token\ndata: {json.dumps({'content': word + ' '})}\n\n"

            # Done event
            yield f"event: done\ndata: {json.dumps({'session_id': session_id, 'confidence': confidence, 'citations': citations, 'method': _determine_method(final_state)})}\n\n"

        except Exception as exc:
            log.error("Chat error: %s", exc, exc_info=True)
            yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── Document Upload ──────────────────────────────────────────────


@router.post("/documents", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    scope: str = Form("global"),
    session_id: Optional[str] = Form(None),
):
    """Upload a document to the student profile or session."""
    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {settings.MAX_FILE_SIZE_MB}MB limit")

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported")

    # Process through doc_analyst directly
    from app.agents.doc_analyst import doc_analyst as process_doc

    state: dict[str, Any] = {
        "files": [{"filename": file.filename, "content": content, "size": len(content)}],
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
    neo4j_status = "unknown"
    lm_studio_status = "unknown"
    ollama_status = "unknown"

    # Check Neo4j
    try:
        from app.adapters.neo4j.graph_store import get_driver
        driver = await get_driver()
        async with driver.session() as session:
            await session.run("RETURN 1")
        neo4j_status = "connected"
    except Exception:
        neo4j_status = "disconnected"

    # Check LM Studio
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.LLM_BASE_URL.replace('/v1', '')}/v1/models")
            lm_studio_status = "connected" if resp.status_code == 200 else "error"
    except Exception:
        lm_studio_status = "disconnected"

    # Check Ollama
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.OLLAMA_URL}/api/tags")
            ollama_status = "connected" if resp.status_code == 200 else "error"
    except Exception:
        ollama_status = "disconnected"

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
