"""Capability agent: partial-answer missing-info policy."""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.system_context import build_step_system_prompt
from app.adapters.llm.lmstudio import get_text_llm
from app.core.state import PathfinderState

_PROMPT = build_step_system_prompt(
    step_name="missing_info_agent",
    objective="Identify only the highest-value missing information that would improve the answer, without over-asking.",
    relevant_capabilities=("missing_info_agent", "profile_memory_agent", "semantic_memory_agent", "document_evidence_agent", "web_researcher"),
    extra_rules=(
        "Return at most 3 missing items.",
        "Do not ask for information that is unnecessary for a useful partial answer.",
        "Prefer concrete missing items such as timeline, completed courses, target role, experience, or constraints.",
        "If the answer can proceed well enough without follow-up, return an empty list.",
    ),
    output_schema="""
Return ONLY JSON:
{
  "missing_items": ["short item"],
  "reason": "short explanation"
}
""",
)


def _fallback_missing_info(state: PathfinderState) -> list[str]:
    profile = state.get("profile_data", {})
    intent = state.get("intent", "general")
    missing: list[str] = []
    if intent == "academic" and not profile.get("courses"):
        missing.append("completed courses or transcript")
    if intent in {"career", "interview"} and not (
        profile.get("skills") or profile.get("experience") or profile.get("projects")
    ):
        missing.append("skills, projects, or experience")
    if intent in {"academic", "career"} and not profile.get("goals"):
        missing.append("target goal")
    return missing[:3]


def _context(state: PathfinderState) -> str:
    profile = state.get("profile_data", {}) or {}
    return json.dumps(
        {
            "query": state.get("query", ""),
            "interpreted_query": state.get("interpreted_query", ""),
            "interpreted_goal": state.get("interpreted_goal", ""),
            "interpreted_constraints": state.get("interpreted_constraints", []),
            "intent": state.get("intent", "general"),
            "task_type": state.get("task_type", "general"),
            "reasoning_depth": state.get("reasoning_depth", "standard"),
            "has_profile_courses": bool(profile.get("courses")),
            "has_profile_goals": bool(profile.get("goals")),
            "has_skills": bool(profile.get("skills")),
            "has_experience": bool(profile.get("experience")),
            "has_projects": bool(profile.get("projects")),
            "files_attached": [item.get("filename", "unknown") for item in (state.get("files", []) or [])[:3]],
            "retrieval_sources": state.get("retrieval_sources", []),
            "retrieval_summary": state.get("retrieval_summary", {}),
        }
    )


async def missing_info_agent(state: PathfinderState) -> PathfinderState:
    """Identify only high-value missing information without blocking useful answers."""
    missing = _fallback_missing_info(state)
    llm = get_text_llm()
    try:
        response = await llm.ainvoke(
            [
                SystemMessage(content=_PROMPT),
                HumanMessage(content=_context(state)),
            ]
        )
        content = response.content if isinstance(response.content, str) else str(response.content)
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(content[start:end])
            candidates = parsed.get("missing_items", [])
            if isinstance(candidates, list):
                normalized = []
                seen = set()
                for item in candidates:
                    text = str(item).strip()
                    key = text.lower()
                    if text and key not in seen:
                        seen.add(key)
                        normalized.append(text)
                if normalized or parsed.get("reason"):
                    missing = normalized[:3]
    except Exception:
        pass

    step_progress = list(state.get("step_progress", []))
    rationale = list(state.get("answer_rationale", []))
    if missing:
        step_progress.append("Detected missing information but continuing with partial answer")
        rationale.append(f"Continuing with a partial answer despite missing: {', '.join(missing[:2])}")
    execution_trace = list(state.get("execution_trace", []))
    execution_trace.append({"agent": "missing_info_agent", "missing": missing[:3]})
    return {
        **state,
        "missing_info": missing[:3],
        "answer_rationale": rationale,
        "execution_trace": execution_trace,
        "step_progress": step_progress,
    }
