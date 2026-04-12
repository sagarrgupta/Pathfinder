"""Canonical Pathfinder MCP tool registry and execution helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse


ToolHandler = Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class PathfinderTool:
    """Definition for one Pathfinder MCP tool."""

    name: str
    description: str
    input_schema: dict[str, Any]
    guidance: str
    handler: ToolHandler


def success_envelope(
    data: Any,
    *,
    citations: list[dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a successful JSON-only MCP tool envelope."""
    return {
        "ok": True,
        "data": data,
        "errors": [],
        "citations": list(citations or []),
        "meta": dict(meta or {}),
    }


def error_envelope(
    *errors: str,
    data: Any | None = None,
    citations: list[dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a failed JSON-only MCP tool envelope."""
    return {
        "ok": False,
        "data": data if data is not None else {},
        "errors": [str(error).strip() for error in errors if str(error).strip()],
        "citations": list(citations or []),
        "meta": dict(meta or {}),
    }


def list_pathfinder_tools() -> list[PathfinderTool]:
    """Return the canonical Pathfinder MCP tool registry."""
    return [
        PathfinderTool(
            name="get_student_profile",
            description="Load the student's current Pathfinder profile from the knowledge graph.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            guidance="Use first for student-specific advice, planning, or personalization.",
            handler=_handle_get_student_profile,
        ),
        PathfinderTool(
            name="search_knowledge_graph",
            description="Search the student's structured profile and knowledge graph for matching facts.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            guidance="Use when you need profile facts, courses, goals, skills, or graph-backed student context.",
            handler=_handle_search_knowledge_graph,
        ),
        PathfinderTool(
            name="list_profile_conflicts",
            description="List unresolved profile conflicts that may need student confirmation.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            guidance="Use when profile facts may conflict or when you need to explain uncertain student data.",
            handler=_handle_list_profile_conflicts,
        ),
        PathfinderTool(
            name="resolve_profile_conflict",
            description="Apply a chosen resolution to one profile conflict.",
            input_schema={
                "type": "object",
                "properties": {
                    "conflict_id": {"type": "string"},
                    "fact_type": {"type": "string"},
                    "action": {"type": "string"},
                    "selected_value": {"type": "string"},
                },
                "required": ["conflict_id", "fact_type", "action"],
                "additionalProperties": False,
            },
            guidance="Use only when the user explicitly chooses a resolution or asks Pathfinder to apply one.",
            handler=_handle_resolve_profile_conflict,
        ),
        PathfinderTool(
            name="update_student_profile",
            description="Update a controlled set of student profile fields.",
            input_schema={
                "type": "object",
                "properties": {
                    "updates": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "gpa": {"type": "string"},
                            "university": {"type": "string"},
                            "program": {"type": "string"},
                            "semester": {"type": "string"},
                            "email": {"type": "string"},
                        },
                        "additionalProperties": False,
                    }
                },
                "required": ["updates"],
                "additionalProperties": False,
            },
            guidance="Use only for explicit user-provided profile facts that should be persisted.",
            handler=_handle_update_student_profile,
        ),
        PathfinderTool(
            name="ingest_uploaded_documents",
            description="Process the current turn's uploaded files into Pathfinder document context.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            guidance="Use before document search or document-grounded reasoning when uploaded files are present.",
            handler=_handle_ingest_uploaded_documents,
        ),
        PathfinderTool(
            name="search_documents",
            description="Search uploaded student documents and indexed chunks for relevant evidence.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            guidance="Use for transcript, resume, degree plan, or uploaded-file questions.",
            handler=_handle_search_documents,
        ),
        PathfinderTool(
            name="get_document_context",
            description="Return summaries and snippets from current uploaded or previously indexed documents.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "additionalProperties": False,
            },
            guidance="Use when you need a compact document snapshot or targeted excerpts before answering.",
            handler=_handle_get_document_context,
        ),
        PathfinderTool(
            name="analyze_document_text",
            description="Analyze raw document text and derive structured hints without mutating stored data.",
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "document_type": {"type": "string"},
                    "filename": {"type": "string"},
                },
                "required": ["text"],
                "additionalProperties": False,
            },
            guidance="Use for one-off parsing of pasted resume, transcript, or other document text.",
            handler=_handle_analyze_document_text,
        ),
        PathfinderTool(
            name="search_web",
            description="Search the web for current external information using Pathfinder's provider chain.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            guidance="Use for current facts, official pages, deadlines, policies, catalogs, jobs, or market data.",
            handler=_handle_search_web,
        ),
        PathfinderTool(
            name="fetch_url",
            description="Fetch and read a specific webpage URL in detail.",
            input_schema={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
                "additionalProperties": False,
            },
            guidance="Use after search_web when you need the full page content from one promising source.",
            handler=_handle_fetch_url,
        ),
        PathfinderTool(
            name="get_official_source_candidates",
            description="Find likely official source candidates for a question and rank them conservatively.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            guidance="Use when you need official domains before citing a live fact or requirement.",
            handler=_handle_get_official_source_candidates,
        ),
        PathfinderTool(
            name="get_program_requirements",
            description="Build an official-source search context for program requirement questions.",
            input_schema={
                "type": "object",
                "properties": {
                    "focus": {"type": "string"},
                },
                "additionalProperties": False,
            },
            guidance="Use for degree requirements, prerequisite policy, graduation rules, or program comparisons.",
            handler=_handle_get_program_requirements,
        ),
        PathfinderTool(
            name="get_course_history",
            description="Return completed and planned course history from profile and transcript evidence.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            guidance="Use for course planning, eligibility, and transcript-grounded academic advice.",
            handler=_handle_get_course_history,
        ),
        PathfinderTool(
            name="get_career_alignment_context",
            description="Return a compact career-planning snapshot from the student profile and recent context.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            guidance="Use for role matching, gap analysis, and actionable career guidance.",
            handler=_handle_get_career_alignment_context,
        ),
        PathfinderTool(
            name="get_interview_context",
            description="Return interview-prep context including target role clues, experience, and projects.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            guidance="Use for interview questions, STAR stories, and company/role preparation.",
            handler=_handle_get_interview_context,
        ),
        PathfinderTool(
            name="get_execution_registry",
            description="Return runtime models, providers, and document ingestion capabilities.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            guidance="Use when you need to know what Pathfinder can currently execute.",
            handler=_handle_get_execution_registry,
        ),
        PathfinderTool(
            name="get_dependency_status",
            description="Return current runtime dependency health for Neo4j, LLM, embeddings, and web search.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            guidance="Use when a tool may be failing due to environment availability or degraded services.",
            handler=_handle_get_dependency_status,
        ),
        PathfinderTool(
            name="get_session_context",
            description="Return current query/session context, uploaded-file summary, and runtime hints.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            guidance="Use first when you need the current session picture, especially before multi-step reasoning.",
            handler=_handle_get_session_context,
        ),
    ]


def tool_index() -> dict[str, PathfinderTool]:
    """Return tool definitions keyed by name."""
    return {tool.name: tool for tool in list_pathfinder_tools()}


def list_tool_descriptors() -> list[dict[str, Any]]:
    """Return MCP-compatible JSON descriptors."""
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.input_schema,
            "guidance": tool.guidance,
        }
        for tool in list_pathfinder_tools()
    ]


async def execute_pathfinder_tool(
    name: str,
    arguments: dict[str, Any] | None,
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a Pathfinder tool using the canonical registry."""
    tool = tool_index().get(name)
    if tool is None:
        return error_envelope(f"Unknown tool: {name}", meta={"tool": name})
    try:
        return await tool.handler(arguments or {}, context or {})
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        return error_envelope(str(exc), meta={"tool": name})


def to_langchain_tool_schemas(*, include_guidance: bool = True) -> list[dict[str, Any]]:
    """Return OpenAI-style tool schemas for LangChain tool binding."""
    schemas: list[dict[str, Any]] = []
    for tool in list_pathfinder_tools():
        description = tool.description
        if include_guidance and tool.guidance:
            description = f"{description} Guidance: {tool.guidance}"
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": description,
                    "parameters": tool.input_schema,
                },
            }
        )
    return schemas


async def _handle_get_student_profile(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from app.adapters.neo4j.graph_store import ensure_student, get_full_profile

    student_id = _student_id_from_context(context)
    await ensure_student(student_id)
    profile = await get_full_profile(student_id)
    _state(context)["profile_data"] = profile
    return success_envelope(
        profile,
        meta={"student_id": student_id, "record_count": _profile_record_count(profile)},
    )


async def _handle_search_knowledge_graph(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query", "")).strip()
    if not query:
        return error_envelope("query is required")

    profile_envelope = await _handle_get_student_profile({}, context)
    profile = profile_envelope.get("data", {}) if profile_envelope.get("ok") else {}
    matches = _profile_matches(profile, query)
    return success_envelope(
        {
            "query": query,
            "matches": matches,
            "summary": {
                "match_count": len(matches),
                "profile_sections_checked": sorted(profile.keys()) if isinstance(profile, dict) else [],
            },
        },
        meta={"query": query},
    )


async def _handle_list_profile_conflicts(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from app.services.conflict_autoresolve import list_profile_conflicts

    student_id = _student_id_from_context(context)
    conflicts = await list_profile_conflicts(student_id)
    _state(context)["conflicts"] = conflicts
    return success_envelope(conflicts, meta={"student_id": student_id, "count": len(conflicts)})


async def _handle_resolve_profile_conflict(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from app.services.conflict_autoresolve import resolve_conflict_choice

    student_id = _student_id_from_context(context)
    result = await resolve_conflict_choice(
        student_id=student_id,
        conflict_id=str(arguments.get("conflict_id", "")).strip(),
        fact_type=str(arguments.get("fact_type", "")).strip(),
        action=str(arguments.get("action", "")).strip(),
        selected_value=(
            str(arguments.get("selected_value", "")).strip()
            if arguments.get("selected_value") not in (None, "")
            else None
        ),
    )
    return success_envelope(result, meta={"student_id": student_id})


async def _handle_update_student_profile(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from app.adapters.neo4j.graph_store import update_student

    updates = arguments.get("updates", {})
    if not isinstance(updates, dict):
        return error_envelope("updates must be an object")
    allowed = {"name", "gpa", "university", "program", "semester", "email"}
    clean = {key: str(value).strip() for key, value in updates.items() if key in allowed and str(value).strip()}
    if not clean:
        return error_envelope("no valid profile fields supplied")
    student_id = _student_id_from_context(context)
    updated = await update_student(student_id, **clean)
    state = _state(context)
    if isinstance(state.get("profile_data"), dict):
        state["profile_data"] = {**state["profile_data"], "personal": {**state["profile_data"].get("personal", {}), **clean}}
    return success_envelope(
        updated,
        meta={"student_id": student_id, "updated_fields": sorted(clean.keys())},
    )


async def _handle_ingest_uploaded_documents(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from app.agents.doc_analyst import doc_analyst

    state = _state(context)
    files = list(state.get("files", []) or [])
    if not files:
        return success_envelope(
            {"processed_files": [], "message": "No uploaded files available in this turn."},
            meta={"processed_count": 0},
        )
    updated_state = await doc_analyst(dict(state))
    state.update(updated_state)
    profile = state.get("profile_data", {})
    return success_envelope(
        {
            "processed_files": [item.get("filename", "") for item in files if isinstance(item, dict)],
            "document_roles": state.get("document_roles", []),
            "transcript_states": state.get("transcript_states", []),
            "entities_extracted": len(state.get("extracted_entities", [])),
            "stored_chunk_count": len(state.get("retrieved_documents", [])),
            "profile_snapshot_available": bool(profile),
        },
        citations=_document_citations_from_state(state),
        meta={"processed_count": len(files)},
    )


async def _handle_search_documents(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from app.adapters.neo4j.vector_store import similarity_search

    state = _state(context)
    query = str(arguments.get("query", "")).strip()
    if not query:
        return error_envelope("query is required")
    if state.get("files"):
        await _handle_ingest_uploaded_documents({}, context)
    top_k = max(1, min(int(arguments.get("top_k", 5) or 5), 10))
    try:
        results = await similarity_search(
            query,
            k=top_k,
            student_id=_student_id_from_context(context),
            session_id=str(state.get("session_id", "") or None),
        )
    except Exception as exc:
        return error_envelope(str(exc), meta={"query": query})

    state["retrieved_documents"] = results
    citations = [
        {
            "title": item.get("filename", "Document snippet"),
            "url": "",
            "source_type": "document",
            "snippet": str(item.get("text", ""))[:280],
        }
        for item in results[:top_k]
    ]
    return success_envelope(
        {"query": query, "matches": results[:top_k]},
        citations=citations,
        meta={"query": query, "match_count": len(results[:top_k])},
    )


async def _handle_get_document_context(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    state = _state(context)
    query = str(arguments.get("query", "")).strip()
    top_k = max(1, min(int(arguments.get("top_k", 5) or 5), 10))
    if query:
        result = await _handle_search_documents({"query": query, "top_k": top_k}, context)
        if result.get("ok"):
            return result
    summaries = []
    for item in list(state.get("document_roles", []))[:top_k]:
        summaries.append(
            {
                "filename": item.get("filename", ""),
                "role": item.get("role", ""),
                "confidence": item.get("confidence", 0.0),
                "signals": item.get("signals", []),
            }
        )
    for transcript in list(state.get("transcript_states", []))[:top_k]:
        transcript_state = transcript.get("state", {}) if isinstance(transcript, dict) else {}
        summaries.append(
            {
                "filename": transcript.get("filename", ""),
                "role": transcript.get("role", "transcript"),
                "summary": transcript_state.get("summary", {}),
            }
        )
    return success_envelope(
        {
            "documents": summaries,
            "indexed_matches": list(state.get("retrieved_documents", []))[:top_k],
        },
        citations=_document_citations_from_state(state),
        meta={"document_count": len(summaries)},
    )


async def _handle_analyze_document_text(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from app.services.transcript_state import build_transcript_state

    text = str(arguments.get("text", "")).strip()
    if not text:
        return error_envelope("text is required")
    document_type = str(arguments.get("document_type", "")).strip().lower()
    filename = str(arguments.get("filename", "")).strip()
    transcript_keywords = {"transcript", "degree_plan", "degree plan"}
    if document_type in transcript_keywords or "cumulative gpa" in text.lower():
        transcript_state = build_transcript_state(text, filename)
        return success_envelope(
            {
                "document_type": "transcript",
                "transcript_state": transcript_state,
            },
            meta={"filename": filename or "inline_text"},
        )
    return success_envelope(
        {
            "document_type": document_type or "general",
            "character_count": len(text),
            "line_count": len(text.splitlines()),
            "preview": text[:800],
        },
        meta={"filename": filename or "inline_text"},
    )


async def _handle_search_web(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from app.services.execution_registry import execute_web_search

    query = str(arguments.get("query", "")).strip()
    if not query:
        return error_envelope("query is required")
    max_results = max(1, min(int(arguments.get("max_results", 5) or 5), 10))
    results = await execute_web_search(query, max_results=max_results)
    _state(context)["web_results"] = results[:max_results]
    citations = [_web_citation(item) for item in results[:max_results]]
    return success_envelope(
        {"query": query, "results": results[:max_results]},
        citations=citations,
        meta={"query": query, "result_count": len(results[:max_results])},
    )


async def _handle_fetch_url(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from app.adapters.web_search.url_fetcher import fetch_url_content

    url = str(arguments.get("url", "")).strip()
    if not url:
        return error_envelope("url is required")
    result = await fetch_url_content(url)
    if not result:
        return error_envelope("Unable to fetch readable HTML content from the URL.", meta={"url": url})
    state = _state(context)
    web_results = list(state.get("web_results", []))
    web_results.append(result)
    state["web_results"] = web_results[-10:]
    return success_envelope(
        result,
        citations=[_web_citation(result)],
        meta={"url": url, "content_chars": len(str(result.get("content", "")))},
    )


async def _handle_get_official_source_candidates(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query", "")).strip()
    if not query:
        return error_envelope("query is required")
    max_results = max(1, min(int(arguments.get("max_results", 5) or 5), 10))
    search_result = await _handle_search_web({"query": query, "max_results": max_results * 2}, context)
    if not search_result.get("ok"):
        return search_result
    results = list((search_result.get("data", {}) or {}).get("results", []))
    ranked = sorted(results, key=lambda item: (_official_rank(item), float(item.get("score", 0.0) or 0.0)), reverse=True)
    chosen = ranked[:max_results]
    return success_envelope(
        {"query": query, "candidates": chosen},
        citations=[_web_citation(item) for item in chosen],
        meta={"candidate_count": len(chosen)},
    )


async def _handle_get_program_requirements(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    focus = str(arguments.get("focus", "")).strip() or "program requirements"
    profile_result = await _handle_get_student_profile({}, context)
    profile = profile_result.get("data", {}) if profile_result.get("ok") else {}
    personal = profile.get("personal", {}) if isinstance(profile, dict) else {}
    query_parts = [personal.get("university", ""), personal.get("program", ""), focus]
    query = " ".join(part for part in query_parts if str(part).strip())
    official = await _handle_get_official_source_candidates({"query": query or focus, "max_results": 5}, context)
    return success_envelope(
        {
            "search_query": query or focus,
            "profile_context": {
                "university": personal.get("university", ""),
                "program": personal.get("program", ""),
            },
            "official_candidates": (official.get("data", {}) or {}).get("candidates", []),
        },
        citations=list(official.get("citations", [])),
        meta={"focus": focus},
    )


async def _handle_get_course_history(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    profile_result = await _handle_get_student_profile({}, context)
    profile = profile_result.get("data", {}) if profile_result.get("ok") else {}
    state = _state(context)
    transcript_states = [item.get("state", {}) for item in list(state.get("transcript_states", [])) if isinstance(item, dict)]
    completed: list[dict[str, Any]] = []
    planned: list[dict[str, Any]] = []
    for transcript in transcript_states:
        completed.extend(list(transcript.get("completed_courses", [])))
        planned.extend(list(transcript.get("planned_courses", [])))
    return success_envelope(
        {
            "profile_courses": list(profile.get("courses", [])) if isinstance(profile, dict) else [],
            "transcript_completed_courses": completed,
            "transcript_planned_courses": planned,
        },
        meta={"completed_count": len(completed), "planned_count": len(planned)},
    )


async def _handle_get_career_alignment_context(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    profile_result = await _handle_get_student_profile({}, context)
    profile = profile_result.get("data", {}) if profile_result.get("ok") else {}
    personal = profile.get("personal", {}) if isinstance(profile, dict) else {}
    return success_envelope(
        {
            "name": personal.get("name", ""),
            "program": personal.get("program", ""),
            "goals": profile.get("goals", []),
            "skills": profile.get("skills", []),
            "experience": profile.get("experience", []),
            "preferences": profile.get("preferences", []),
        },
        meta={"goal_count": len(profile.get("goals", [])) if isinstance(profile, dict) else 0},
    )


async def _handle_get_interview_context(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    state = _state(context)
    career_context = await _handle_get_career_alignment_context(arguments, context)
    data = dict(career_context.get("data", {}))
    data["recent_query"] = str(state.get("query", "")).strip()
    data["projects"] = list((_state(context).get("profile_data", {}) or {}).get("projects", []))
    return success_envelope(data, meta={"has_recent_query": bool(data["recent_query"])})


async def _handle_get_execution_registry(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from app.services.execution_registry import get_execution_registry

    registry = get_execution_registry()
    return success_envelope(
        {
            "text_model": registry.text_model,
            "vision_model": registry.vision_model,
            "retrieval_strategy": registry.retrieval_strategy,
            "web_providers": list(registry.web_providers),
            "document_ingestors": dict(registry.document_ingestors),
        }
    )


async def _handle_get_dependency_status(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from app.services.runtime_session import get_dependency_status

    status = await get_dependency_status()
    _state(context)["dependency_status"] = status
    return success_envelope(status)


async def _handle_get_session_context(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    state = _state(context)
    runtime_snapshot = context.get("runtime_snapshot", {})
    request_plan = state.get("request_plan", {})
    files = list(state.get("files", []) or [])
    return success_envelope(
        {
            "query": state.get("query", ""),
            "session_id": state.get("session_id", ""),
            "student_id": state.get("student_id", ""),
            "advisor_mode": state.get("advisor_mode", ""),
            "uploaded_files": [item.get("filename", "") for item in files if isinstance(item, dict)],
            "uploaded_file_count": len(files),
            "request_plan": request_plan,
            "runtime_policy": state.get("runtime_policy", {}),
            "runtime_snapshot": runtime_snapshot,
            "recent_messages": _recent_messages(state.get("messages", [])),
            "session_summary": state.get("session_summary", {}),
            "session_memory": state.get("session_memory", {}),
            "compacted_session": state.get("compacted_session", {}),
            "working_memory": state.get("working_memory", {}),
            "open_blockers": list(state.get("blocked_reasons", []) or []),
            "recent_tool_calls": _recent_tool_calls(state.get("tool_call_log", [])),
            "has_profile_data": bool(state.get("profile_data")),
            "has_document_context": bool(state.get("retrieved_documents") or state.get("transcript_states")),
            "has_web_context": bool(state.get("web_results")),
        }
    )


def _student_id_from_context(context: dict[str, Any]) -> str:
    state = _state(context)
    student_id = str(state.get("student_id", "")).strip()
    if not student_id:
        from app.utils.ids import generate_student_id

        student_id = generate_student_id()
        state["student_id"] = student_id
    return student_id


def _state(context: dict[str, Any]) -> dict[str, Any]:
    state = context.get("state")
    if isinstance(state, dict):
        return state
    new_state: dict[str, Any] = {}
    context["state"] = new_state
    return new_state


def _profile_record_count(profile: dict[str, Any]) -> int:
    total = 0
    for value in profile.values():
        if isinstance(value, list):
            total += len(value)
        elif isinstance(value, dict):
            total += len([item for item in value.values() if item not in ("", None, [], {})])
    return total


def _profile_matches(profile: dict[str, Any], query: str) -> list[dict[str, Any]]:
    tokens = {token.casefold() for token in str(query).replace(",", " ").split() if token.strip()}
    matches: list[dict[str, Any]] = []
    for section, value in profile.items():
        if isinstance(value, dict):
            text = json.dumps(value, ensure_ascii=True).casefold()
            if any(token in text for token in tokens):
                matches.append({"section": section, "value": value})
        elif isinstance(value, list):
            for item in value:
                text = json.dumps(item, ensure_ascii=True, default=str).casefold()
                if any(token in text for token in tokens):
                    matches.append({"section": section, "value": item})
    return matches[:20]


def _document_citations_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for item in list(state.get("document_roles", []))[:8]:
        citations.append(
            {
                "title": item.get("filename", "Uploaded document"),
                "url": "",
                "source_type": "document",
                "snippet": f"Detected role: {item.get('role', '')}",
            }
        )
    return citations


def _web_citation(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "source_type": "web",
        "snippet": str(item.get("content", ""))[:280],
    }


def _official_rank(item: dict[str, Any]) -> int:
    host = urlparse(str(item.get("url", "")).strip()).netloc.casefold()
    if host.endswith(".edu") or host.endswith(".gov"):
        return 3
    if any(token in host for token in ("university", "college", "school", "edu")):
        return 2
    if host:
        return 1
    return 0


def _recent_messages(messages: list[Any], max_messages: int = 8) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for raw in list(messages or []):
        role = ""
        content = ""
        if isinstance(raw, tuple) and len(raw) == 2:
            role = str(raw[0] or "")
            content = str(raw[1] or "")
        elif hasattr(raw, "content"):
            role = str(getattr(raw, "type", "") or getattr(raw, "role", ""))
            content = str(getattr(raw, "content", "") or "")
        else:
            continue
        normalized_role = "user" if role in {"human", "user"} else "assistant" if role in {"assistant", "ai"} else ""
        snippet = " ".join(content.split())
        if not normalized_role or not snippet:
            continue
        items.append({"role": normalized_role, "content": snippet[:300] + ("..." if len(snippet) > 300 else "")})
    if max_messages > 0 and len(items) > max_messages:
        items = items[-max_messages:]
    return items


def _recent_tool_calls(entries: list[dict[str, Any]], max_entries: int = 6) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for item in list(entries or [])[-max_entries:]:
        if not isinstance(item, dict):
            continue
        calls.append(
            {
                "tool": str(item.get("tool", "")),
                "status": str(item.get("status", "")),
                "result_summary": item.get("result_summary", {}),
            }
        )
    return calls
