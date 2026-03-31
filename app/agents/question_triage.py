"""Capability agent: question triage."""

from __future__ import annotations

import json
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.system_context import build_step_system_prompt
from app.adapters.llm.lmstudio import get_text_llm
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.question_triage")

_PROMPT = build_step_system_prompt(
    step_name="question_triage",
    objective=(
        "Classify the student's request into domain, task type, reasoning depth, and whether "
        "web, documents, or profile context should be used."
    ),
    relevant_capabilities=(
        "profile_memory_agent",
        "semantic_memory_agent",
        "document_evidence_agent",
        "web_researcher",
        "academic_strategy_agent",
        "career_strategy_agent",
        "interview_coach_agent",
        "document_understanding_agent",
    ),
    extra_rules=(
        "If the query includes a URL and asks to read, use, extract, review, inspect, or apply information from that page, set needs_web=true.",
        "If the query includes a URL and asks to update the student's profile from that page, classify it as domain=profile and task_type=update.",
        "If the user is asking about Pathfinder itself, what it can do, how it can help, or how to use it, classify as domain=general and task_type=clarify.",
        "For lightweight meta/help questions about Pathfinder, keep needs_profile=false unless the user explicitly asks about their own saved profile or prior recommendations.",
        "Prefer compact reasoning; the code will validate and execute the result.",
    ),
    output_schema="""
Return ONLY JSON:
{
  "domain": "academic|career|interview|document|profile|research|general|greeting",
  "task_type": "recommend|compare|plan|summarize|analyze|extract|update|clarify|general",
  "reasoning_depth": "light|standard|deep",
  "needs_web": true,
  "needs_documents": true,
  "needs_profile": true,
  "reasoning": "short explanation"
}
""",
)


def _has_url(text: str) -> bool:
    return "http://" in text or "https://" in text


def _is_external_source_request(lower: str) -> bool:
    source_markers = (
        "url",
        "link",
        "page",
        "site",
        "website",
        "web",
        "linkedin",
        "portfolio",
        "github",
    )
    action_markers = (
        "use",
        "read",
        "review",
        "inspect",
        "check",
        "go over",
        "look at",
        "extract",
        "pull",
        "analyze",
        "summarize",
        "add",
        "update",
        "fill",
    )
    apply_markers = (
        "my profile",
        "my background",
        "my information",
        "my details",
        "add the information",
        "add this",
        "update my profile",
        "use it for my profile",
    )
    has_source = any(marker in lower for marker in source_markers)
    has_action = any(marker in lower for marker in action_markers)
    has_apply = any(marker in lower for marker in apply_markers)
    return has_source and has_action and has_apply


def _heuristic_triage(query: str, has_files: bool) -> dict[str, object] | None:
    text = (query or "").strip()
    lower = text.lower()
    has_url = _has_url(lower)
    academic_tokens = (
        "semester",
        "course",
        "courses",
        "class",
        "classes",
        "curriculum",
        "catalog",
        "academic calendar",
        "registration",
        "degree",
        "program requirement",
        "graduation",
        "advisor",
    )
    planning_tokens = (
        "plan",
        "from scratch",
        "next semester",
        "should i take",
        "roadmap",
        "schedule",
        "register",
        "sequence",
    )
    is_question = "?" in text or lower.startswith(
        ("what ", "which ", "who ", "how ", "can ", "could ", "should ", "do ", "does ")
    )
    simple_identity_statement = any(
        re.match(pattern, lower)
        for pattern in [
            r"^\s*i am [a-z][a-z\s\-.']{0,80}$",
            r"^\s*i'm [a-z][a-z\s\-.']{0,80}$",
            r"^\s*my name is [a-z][a-z\s\-.']{0,80}$",
        ]
    )

    profile_signals = [
        r"\bi am\b",
        r"\bmy name is\b",
        r"\bi'm\b",
        r"\bi am a\b",
        r"\bi am an\b",
        r"\bi study\b",
        r"\bi am studying\b",
        r"\bi am .*student\b",
        r"\bmy university\b",
        r"\bmy program\b",
        r"\bmy major\b",
        r"\bi go to\b",
        r"\bmy goal is\b",
        r"\bmy current goal is\b",
        r"\bmy current main goal is\b",
        r"\bi prefer\b",
        r"\bmy preference is\b",
        r"\bi want to\b",
        r"\bi want\b",
        r"\bi am interested in\b",
        r"\bi'm interested in\b",
    ]
    has_profile_statement = any(re.search(pattern, lower) for pattern in profile_signals)
    has_profile_keywords = any(
        token in lower
        for token in [
            "student",
            "university",
            "college",
            "program",
            "major",
            "gpa",
            "resume",
            "transcript",
            "goal",
            "prefer",
            "preference",
            "interested",
            "plans",
        ]
    )

    url_profile_enrichment = has_url and _is_external_source_request(lower)

    if url_profile_enrichment:
        return {
            "domain": "profile",
            "task_type": "update",
            "reasoning_depth": "standard",
            "needs_web": True,
            "needs_documents": False,
            "needs_profile": True,
            "reasoning": "Heuristic URL-based profile enrichment detection",
        }

    if (simple_identity_statement or (has_profile_statement and has_profile_keywords and not is_question)) and not has_files:
        return {
            "domain": "profile",
            "task_type": "update",
            "reasoning_depth": "light",
            "needs_web": False,
            "needs_documents": False,
            "needs_profile": True,
            "reasoning": "Heuristic self-description/profile update detection",
        }

    if any(
        phrase in lower
        for phrase in [
            "my current goal is",
            "my current main goal is",
            "my goal is",
            "my preference is",
            "my current preference is",
            "i prefer",
        ]
    ) and not is_question and not has_files:
        return {
            "domain": "profile",
            "task_type": "update",
            "reasoning_depth": "light",
            "needs_web": False,
            "needs_documents": False,
            "needs_profile": True,
            "reasoning": "Heuristic explicit goal/preference update detection",
        }

    if any(
        phrase in lower
        for phrase in [
            "what do you know about me",
            "what do you remember about me",
            "who am i",
            "what's my name",
            "which university do i study at",
            "what is my name",
            "what is my program",
            "what is my goal",
            "what is my gpa",
            "what's my gpa",
        ]
    ):
        return {
            "domain": "profile",
            "task_type": "summarize",
            "reasoning_depth": "light",
            "needs_web": False,
            "needs_documents": False,
            "needs_profile": True,
            "reasoning": "Heuristic profile recall/introspection detection",
        }

    if has_files and any(token in lower for token in ["resume", "cv", "transcript", "attached", "based on my"]):
        is_career_resume_query = "job" in lower or "career" in lower or "resume" in lower or "roles" in lower
        return {
            "domain": "career" if is_career_resume_query else "document",
            "task_type": "analyze",
            "reasoning_depth": "light" if is_career_resume_query else "standard",
            "needs_web": False,
            "needs_documents": True,
            "needs_profile": True,
            "reasoning": "Heuristic current-turn document analysis detection",
        }

    has_academic_context = any(token in lower for token in academic_tokens)
    has_planning_request = any(token in lower for token in planning_tokens)
    if has_academic_context and has_planning_request:
        deep_planning = "from scratch" in lower or "roadmap" in lower or "step by step" in lower
        return {
            "domain": "academic",
            "task_type": "plan",
            "reasoning_depth": "deep" if deep_planning else "standard",
            "needs_web": True,
            "needs_documents": has_files,
            "needs_profile": True,
            "reasoning": "Heuristic academic planning detection",
        }

    if any(
        phrase in lower
        for phrase in [
            "what jobs can i get based on my profile",
            "what jobs can i get based on my background",
            "based on my profile",
            "based on my background",
            "suggest roles that fit me",
            "which roles fit me",
            "roles that fit me",
        ]
    ):
        return {
            "domain": "career",
            "task_type": "recommend",
            "reasoning_depth": "light",
            "needs_web": False,
            "needs_documents": has_files,
            "needs_profile": True,
            "reasoning": "Heuristic profile-based career recommendation detection",
        }

    if any(
        phrase in lower
        for phrase in [
            "given my goals",
            "based on my goals",
            "based on my profile",
            "based on my background",
            "for my goals",
            "for my profile",
            "what should i focus on next",
            "what should i do next",
        ]
    ) and any(token in lower for token in ["my goals", "my goal", "my profile", "my background"]):
        return {
            "domain": "career",
            "task_type": "recommend",
            "reasoning_depth": "standard",
            "needs_web": False,
            "needs_documents": has_files,
            "needs_profile": True,
            "reasoning": "Heuristic profile-grounded planning/recommendation detection",
        }

    return None


def _explicit_override_triage(query: str, has_files: bool) -> dict[str, object] | None:
    heuristic = _heuristic_triage(query, has_files)
    if not heuristic:
        return None
    reasoning = str(heuristic.get("reasoning", "")).lower()
    explicit_markers = (
        "url-based profile enrichment detection",
        "self-description/profile update detection",
        "explicit goal/preference update detection",
    )
    if any(marker in reasoning for marker in explicit_markers):
        return heuristic
    return None


async def question_triage(state: PathfinderState) -> PathfinderState:
    """Determine domain, task type, and reasoning depth."""
    query = state.get("query", "")
    interpreted_query = state.get("interpreted_query", "").strip()
    triage_input = interpreted_query or query
    step_progress = list(state.get("step_progress", []))
    step_progress.append("Triaging question type...")

    explicit_override = _explicit_override_triage(query, bool(state.get("files")))
    fallback_heuristic = _heuristic_triage(triage_input, bool(state.get("files")))
    if explicit_override:
        parsed = explicit_override
    else:
        llm = get_text_llm()
        parsed = {
            "domain": "general",
            "task_type": "general",
            "reasoning_depth": "standard",
            "needs_web": False,
            "needs_documents": False,
            "needs_profile": True,
            "reasoning": "Fallback classification",
        }
        try:
            response = await llm.ainvoke(
                [
                    SystemMessage(content=_PROMPT),
                    HumanMessage(
                        content=(
                            f"Original query: {query[:2000]}\n"
                            f"Interpreted helper query: {triage_input[:2000]}\n"
                            f"Interpreted goal: {state.get('interpreted_goal', '')}\n"
                            f"Interpreted constraints: {state.get('interpreted_constraints', [])}\n"
                            f"Interpretation notes: {state.get('interpretation_notes', '')}"
                        )
                    ),
                ]
            )
            content = response.content if isinstance(response.content, str) else str(response.content)
            json_start = content.find("{")
            json_end = content.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                parsed.update(json.loads(content[json_start:json_end]))
        except Exception as exc:
            log.warning("Question triage parse failed: %s", exc)
            if fallback_heuristic:
                parsed = fallback_heuristic

    planner_trace = list(state.get("planner_trace", []))
    planner_trace.append(
        f"triage:{parsed['domain']}:{parsed['task_type']}:{parsed['reasoning_depth']}"
    )
    step_progress.append(
        f"Triage: {parsed['domain']} / {parsed['task_type']} / {parsed['reasoning_depth']}"
    )
    return {
        **state,
        "intent": parsed["domain"],
        "task_type": parsed["task_type"],
        "reasoning_depth": parsed["reasoning_depth"],
        "needs_web": bool(parsed.get("needs_web", False)),
        "needs_documents": bool(parsed.get("needs_documents", False)),
        "needs_profile": bool(parsed.get("needs_profile", True)),
        "planner_trace": planner_trace,
        "step_progress": step_progress,
    }
