"""Deterministic specialist selector for the simplified Pathfinder flow."""

from __future__ import annotations

import logging
import re

from app.adapters.neo4j.graph_store import get_full_profile
from app.core.quality import build_session_summary
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.orchestrator")

_SPECIALIST_KEYWORDS: dict[str, set[str]] = {
    "academic": {
        "academic", "admission", "catalog", "class", "classes", "course", "courses",
        "credit", "credits", "curriculum", "degree", "eligible", "eligibility",
        "graduate", "graduation", "major", "minor", "plan", "planner", "program",
        "prereq", "prerequisite", "requirements", "schedule", "semester", "transcript",
        "university",
    },
    "career": {
        "career", "company", "companies", "compensation", "cover", "interview",
        "intern", "internship", "job", "jobs", "linkedin", "market", "offer",
        "portfolio", "prep", "recruiter", "resume", "role", "salary", "skills",
        "target", "technical",
    },
    "general": {
        "change", "correct", "document", "documents", "file", "files", "goal",
        "goals", "gpa", "memory", "name", "preference", "preferences", "profile",
        "remember", "store", "student", "transcript", "update", "upload",
        "general", "question", "explain", "help", "summarize", "read", "analyze",
    },
}

_MODE_TO_SPECIALIST = {
}

_PROFILE_SIGNAL_PATTERNS = (
    "my gpa is",
    "my name is",
    "i am a",
    "i'm a",
    "i study at",
    "i prefer",
    "my goal is",
    "my goals are",
    "my skills are",
)

_LIGHT_CONVERSATION_RE = re.compile(
    r"^\s*(hi|hello|hey|yo|good morning|good afternoon|good evening|thanks|thank you|bye|goodbye|see you)\b[!. ]*$",
    re.IGNORECASE,
)


def _keyword_overlap(query: str, keywords: set[str]) -> int:
    lowered = query.lower()
    return sum(1 for keyword in keywords if keyword in lowered)


def _profile_signals(query: str) -> bool:
    lowered = query.lower()
    return any(pattern in lowered for pattern in _PROFILE_SIGNAL_PATTERNS)


def _durable_context(profile: dict[str, object], session_summary: dict[str, object]) -> dict[str, object]:
    personal = profile.get("personal", {}) if isinstance(profile.get("personal", {}), dict) else {}
    institution = str(personal.get("university", "") or ((session_summary.get("institution", {}) or {}).get("value", "")))
    program = str(personal.get("program", "") or ((session_summary.get("program", {}) or {}).get("value", "")))
    semester = str(personal.get("semester", "") or ((session_summary.get("standing", {}) or {}).get("value", "")))
    return {
        "institution": institution,
        "program": program,
        "semester": semester,
        "goals_count": len(profile.get("goals", [])),
        "skills_count": len(profile.get("skills", [])),
        "documents_count": len(profile.get("documents", [])),
    }


def _is_light_conversation(query: str) -> bool:
    return bool(_LIGHT_CONVERSATION_RE.match(str(query or "").strip()))


async def orchestrator(state: PathfinderState) -> PathfinderState:
    """Score the request against the 3 specialist prompt families."""
    query = str(state.get("query", "") or "")
    files = list(state.get("files", []))
    request_plan = state.get("request_plan", {}) if isinstance(state.get("request_plan", {}), dict) else {}
    student_id = str(state.get("student_id", "") or "")

    profile = await get_full_profile(student_id)
    session_summary = build_session_summary(profile, list(state.get("messages", [])), query)

    routing_scores: dict[str, float] = {
        name: float(_keyword_overlap(query, keywords))
        for name, keywords in _SPECIALIST_KEYWORDS.items()
    }
    lowered = query.lower()
    if files:
        routing_scores["general"] += 4.0
    if "http://" in lowered or "https://" in lowered:
        routing_scores["academic"] += 1.0
        routing_scores["career"] += 1.0
    if _profile_signals(query):
        routing_scores["general"] += 3.0
    if any(token in lowered for token in ("interview", "internship", "resume", "job", "career")):
        routing_scores["career"] += 2.0
    if any(token in lowered for token in ("course", "program", "degree", "eligible", "eligibility", "semester")):
        routing_scores["academic"] += 2.0
    if request_plan.get("workflow_hint") == "student_state_update":
        routing_scores["general"] += 2.0

    selected_specialist = max(routing_scores.items(), key=lambda item: (item[1], item[0] == "general"))[0]
    top_score = float(routing_scores.get(selected_specialist, 0.0) or 0.0)
    if top_score <= 0.0 and _is_light_conversation(query):
        routing_reason = "Selected general as the fallback specialist for a lightweight conversational turn."
    elif top_score <= 0.0 and selected_specialist == "general":
        routing_reason = "Selected general as the fallback specialist for a broad request."
    else:
        routing_reason = (
            f"Selected {selected_specialist} because its capability score "
            f"({top_score:.1f}) was highest for this request."
        )

    step_progress = list(state.get("step_progress", []))
    step_progress.append("Scoring request against specialist prompts...")
    step_progress.append(f"Selected specialist: {selected_specialist.replace('_', ' ')}")

    log.info("Orchestrator selected specialist=%s scores=%s", selected_specialist, routing_scores)
    return {
        **state,
        "selected_specialist": selected_specialist,
        "routing_scores": routing_scores,
        "routing_reason": routing_reason,
        "profile_data": profile,
        "session_summary": session_summary,
        "durable_profile_facts": _durable_context(profile, session_summary),
        "next_node": "specialist_runner",
        "step_progress": step_progress,
    }
