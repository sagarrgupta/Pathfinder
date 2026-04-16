"""LLM-powered specialist selector for the Pathfinder flow.

Uses the text LLM as a lightweight classifier to semantically rank
specialists instead of relying on brittle keyword lists.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage

from app.adapters.llm.lmstudio import get_text_llm
from app.adapters.neo4j.graphDB import GraphDB
from app.core.quality import build_session_summary
from app.core.state import PathfinderState
from app.tools.graph_tools import get_driver as get_graph_driver
from app.utils.json_extract import parse_json_object

log = logging.getLogger("pathfinder.agents.orchestrator")

_SPECIALIST_DESCRIPTIONS: dict[str, str] = {
    "academic": (
        "Academic records, degree progress, institutional policies, "
        "academic deadlines, courses, grades, graduation requirements, "
        "enrollment, and eligibility."
    ),
    "career": (
        "Career planning, job search, professional development, "
        "skill assessment, market-oriented advice, resume and interview help."
    ),
    "general": (
        "Profile management, uploaded documents, cross-domain requests, "
        "greetings, follow-ups, memory-aware questions, and anything "
        "that does not clearly belong to a single specialist."
    ),
}

_ROUTING_PROMPT = """You are a query classifier. Given a student's query and optional context, score how relevant each specialist is on a scale of 0 to 10.

Specialists:
{specialists}

Student query: "{query}"
{context_line}

Return ONLY a JSON object with scores, nothing else:
{{"academic": <0-10>, "career": <0-10>, "general": <0-10>}}"""

_LIGHT_CONVERSATION_RE = re.compile(
    r"^\s*(hi|hello|hey|yo|good morning|good afternoon|good evening|thanks|thank you|bye|goodbye|see you)\b[!. ]*$",
    re.IGNORECASE,
)


def _profile_student(profile: dict[str, Any]) -> dict[str, Any]:
    student = profile.get("student")
    if isinstance(student, dict):
        return student
    root = profile.get("root_properties")
    return dict(root) if isinstance(root, dict) else {}


def _profile_entity_groups(profile: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    if isinstance(profile.get("all_entities"), dict):
        return {
            str(label): list(items)
            for label, items in profile.get("all_entities", {}).items()
            if isinstance(items, list)
        }
    groups: dict[str, list[dict[str, Any]]] = {}
    for entity in profile.get("entities", []) if isinstance(profile.get("entities"), list) else []:
        if not isinstance(entity, dict):
            continue
        label = str(entity.get("entity_type") or "Entity")
        groups.setdefault(label, []).append(entity)
        for document in entity.get("documents", []) if isinstance(entity.get("documents"), list) else []:
            if isinstance(document, dict):
                groups.setdefault("Document", []).append(document)
        for chunk in entity.get("chunks", []) if isinstance(entity.get("chunks"), list) else []:
            if isinstance(chunk, dict):
                groups.setdefault("Chunk", []).append(chunk)
    return groups


def _build_context_hint(profile: dict[str, Any], files: list[Any]) -> str:
    """Build a one-line context hint from the profile and request."""
    parts: list[str] = []
    if files:
        parts.append(f"User attached {len(files)} file(s)")
    root = _profile_student(profile)
    if root:
        fields = [f"{k}={v}" for k, v in list(root.items())[:4] if v]
        if fields:
            parts.append(f"Profile: {', '.join(fields)}")
    return "; ".join(parts)


async def _llm_route(query: str, context_hint: str) -> dict[str, float] | None:
    """Ask the LLM to score specialist relevance. Returns None on failure."""
    specialists_block = "\n".join(
        f"- {name}: {desc}" for name, desc in _SPECIALIST_DESCRIPTIONS.items()
    )
    context_line = f"Context: {context_hint}" if context_hint else ""
    prompt = _ROUTING_PROMPT.format(
        specialists=specialists_block,
        query=query,
        context_line=context_line,
    )
    try:
        llm = get_text_llm("none")
        result = await llm.ainvoke([HumanMessage(content=prompt)])
        text = result.content if isinstance(result.content, str) else str(result.content)
        parsed = parse_json_object(text)
        if isinstance(parsed, dict):
            scores: dict[str, float] = {}
            for key in ("academic", "career", "general"):
                val = parsed.get(key, 0)
                try:
                    scores[key] = float(val)
                except (TypeError, ValueError):
                    scores[key] = 0.0
            return scores
    except Exception as exc:
        log.warning("LLM routing failed (%s), falling back to heuristic", exc)
    return None


def _heuristic_route(query: str, files: list[Any]) -> dict[str, float]:
    """Fast keyword-free heuristic as fallback when LLM routing is unavailable."""
    scores: dict[str, float] = {"academic": 0.0, "career": 0.0, "general": 0.0}
    if files:
        scores["general"] += 4.0
    lowered = query.lower()
    if "http://" in lowered or "https://" in lowered:
        scores["academic"] += 1.0
        scores["career"] += 1.0
    if _is_light_conversation(query):
        scores["general"] += 5.0
    return scores


def _durable_context(profile: dict[str, object], session_summary: dict[str, object]) -> dict[str, object]:
    personal = _profile_student(profile)
    all_entities = _profile_entity_groups(profile)
    return {
        "sections_count": len(profile.get("sections", [])) if isinstance(profile.get("sections", []), list) else 0,
        "entity_types_count": sum(
            1
            for label, items in all_entities.items()
            if label not in {"CandidateFact", "MemoryItem", "Evidence", "Section", "SchemaSection"} and isinstance(items, list) and items
        ),
        "documents_count": len(all_entities.get("Document", [])) if isinstance(all_entities.get("Document", []), list) else 0,
    }


def _is_light_conversation(query: str) -> bool:
    return bool(_LIGHT_CONVERSATION_RE.match(str(query or "").strip()))


async def orchestrator(state: PathfinderState) -> PathfinderState:
    """Score the request against the 3 specialist prompt families using the LLM."""
    query = str(state.get("query", "") or "")
    files = list(state.get("files", []))
    request_plan = state.get("request_plan", {}) if isinstance(state.get("request_plan", {}), dict) else {}
    student_id = str(state.get("student_id", "") or "")

    profile = await GraphDB(await get_graph_driver()).get_full_student(student_id=student_id)
    session_summary = build_session_summary(profile, list(state.get("messages", [])), query)
    context_hint = _build_context_hint(profile, files)

    routing_scores = await _llm_route(query, context_hint)
    routing_method = "llm"

    if routing_scores is None:
        routing_scores = _heuristic_route(query, files)
        routing_method = "heuristic"

    if files:
        routing_scores["general"] = routing_scores.get("general", 0.0) + 4.0
    if request_plan.get("workflow_hint") == "student_state_update":
        routing_scores["general"] = routing_scores.get("general", 0.0) + 2.0

    selected_specialist = max(
        routing_scores.items(),
        key=lambda item: (item[1], item[0] == "general"),
    )[0]
    top_score = float(routing_scores.get(selected_specialist, 0.0) or 0.0)

    if top_score <= 0.0 and _is_light_conversation(query):
        routing_reason = "Light conversational turn — routed to general."
    elif top_score <= 0.0:
        routing_reason = "No strong signal — routed to general as fallback."
    else:
        routing_reason = (
            f"Selected {selected_specialist} via {routing_method} routing "
            f"(score {top_score:.1f})."
        )

    step_progress = list(state.get("step_progress", []))
    step_progress.append(f"Routing ({routing_method}): {selected_specialist}")

    log.info(
        "Orchestrator selected specialist=%s method=%s scores=%s",
        selected_specialist, routing_method, routing_scores,
    )
    return {
        **state,
        "selected_specialist": selected_specialist,
        "routing_scores": routing_scores,
        "routing_reason": routing_reason,
        "profile_data": profile,
        "session_summary": session_summary,
        "durable_student_facts": _durable_context(profile, session_summary),
        "next_node": "specialist_runner",
        "step_progress": step_progress,
    }
