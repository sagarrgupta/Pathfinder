"""Node 7: Academic Advisor.

Provides academic guidance: major selection, course planning,
university comparison, and requirement matching.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage

from app.adapters.llm.lmstudio import get_text_llm, strip_repetition, is_garbage_output
from app.config.settings import settings
from app.core.state import PathfinderState
from app.prompts import Prompts

log = logging.getLogger("pathfinder.agents.academic_advisor")

# Heuristic: lines that look like transcript rows (code + title or grade)
_COURSE_LINE = re.compile(
    r"\b[A-Z]{2,10}\s*\d{3,4}[A-Z]?\b|\b\d+\s*(?:units?|credits?)\b",
    re.IGNORECASE,
)


async def academic_advisor(state: PathfinderState) -> PathfinderState:
    """Generate academic advice based on profile and research."""
    query = state.get("query", "")
    profile = state.get("profile_data", {})
    web_results = state.get("web_results", [])
    documents = state.get("retrieved_documents", [])

    step_progress = list(state.get("step_progress", []))
    step_progress.append("Preparing academic advice...")

    llm = get_text_llm()

    # Format context
    profile_text = _format_profile(profile)
    web_text = _format_web_results(web_results)
    doc_text = _format_documents(documents)

    # Check if we have enough course data for recommendations
    courses = profile.get("courses", [])
    is_course_query = _is_course_recommendation_query(query)
    min_courses = settings.ACADEMIC_COURSE_HISTORY_MIN
    coverage = _transcript_course_coverage(documents)
    has_rich_history = (
        len(courses) >= min_courses
        or coverage >= settings.ACADEMIC_COURSE_COVERAGE_THRESHOLD
    )

    if is_course_query and not has_rich_history:
        # Insufficient structured course data — ask for more info before recommending
        step_progress.append("Need more course history — asking for clarification")
        log.info(
            "Academic advisor: insufficient course signal (courses=%d coverage=%.2f), asking for more",
            len(courses),
            coverage,
        )

        response = await llm.ainvoke([
            SystemMessage(content=Prompts.ACADEMIC_INSUFFICIENT_SYSTEM.format(profile=profile_text)),
            HumanMessage(content=query),
        ])

        answer = strip_repetition(response.content if isinstance(response.content, str) else str(response.content))

        return {
            **state,
            "draft_answer": answer,
            "confidence_score": 0.9,  # High confidence in the clarification request
            "step_progress": step_progress,
            "next_node": "evaluator",
        }

    # Sufficient data — provide full advice
    response = await llm.ainvoke([
        SystemMessage(content=Prompts.ACADEMIC_ADVISOR_SYSTEM.format(
            profile=profile_text,
            web_results=web_text,
            documents=doc_text,
        )),
        HumanMessage(content=query),
    ])

    answer = strip_repetition(response.content if isinstance(response.content, str) else str(response.content))

    if is_garbage_output(answer):
        log.warning("Academic advisor produced garbage output (%d chars), discarding", len(answer))
        answer = ""

    step_progress.append("Academic advice prepared")
    log.info("Academic advisor generated response (%d chars)", len(answer))

    return {
        **state,
        "draft_answer": answer,
        "step_progress": step_progress,
        "next_node": "evaluator",
    }


def _is_course_recommendation_query(query: str) -> bool:
    """Check if the query is specifically asking for course recommendations."""
    q = query.lower()
    course_keywords = [
        "course", "class", "classes", "next semester", "should i take",
        "recommend", "enroll", "register", "schedule", "curriculum",
        "elective", "prerequisite",
    ]
    return any(kw in q for kw in course_keywords)


def _transcript_course_coverage(documents: list[dict[str, Any]]) -> float:
    """Estimate how much of retrieved doc text looks like a course listing (0–1)."""
    if not documents:
        return 0.0
    total = 0
    hits = 0
    for d in documents[:8]:
        text = d.get("text") or ""
        if not text.strip():
            continue
        for line in text.splitlines():
            line = line.strip()
            if len(line) < 8:
                continue
            total += 1
            if _COURSE_LINE.search(line):
                hits += 1
    if total == 0:
        return 0.0
    return hits / total


def _format_profile(profile: dict[str, Any]) -> str:
    """Format profile data for LLM context."""
    parts = []
    personal = profile.get("personal", {})
    if personal.get("name"):
        parts.append(f"Name: {personal['name']}")
    if personal.get("gpa"):
        parts.append(f"GPA: {personal['gpa']}")
    if personal.get("university"):
        parts.append(f"University: {personal['university']}")
    if personal.get("program"):
        parts.append(f"Program: {personal['program']}")

    courses = profile.get("courses", [])
    if courses:
        course_list = ", ".join(f"{c.get('code', c.get('name', '?'))} ({c.get('grade', '?')})" for c in courses[:10])
        parts.append(f"Courses taken ({len(courses)} recorded): {course_list}")
    else:
        parts.append("Courses taken: NONE RECORDED")

    skills = profile.get("skills", [])
    if skills:
        skill_list = ", ".join(s.get("name", "") for s in skills[:10])
        parts.append(f"Skills: {skill_list}")

    goals = profile.get("goals", [])
    if goals:
        goal_list = ", ".join(g.get("name", "") for g in goals[:5])
        parts.append(f"Goals: {goal_list}")

    return "\n".join(parts) if parts else "No profile data available."


def _format_web_results(results: list[dict[str, Any]]) -> str:
    """Format web results for LLM context.

    Direct URL fetches (source=direct_url) get much more content since
    the user explicitly asked to analyze that page.
    """
    if not results:
        return "No web results available."
    parts = []
    for r in results[:5]:
        source = r.get("source", "")
        content = r.get("content", "")
        if source == "direct_url":
            # Direct fetch — include full content (up to 8000 chars)
            parts.append(f"### [{r.get('title', 'Page')}]({r.get('url', '')})\n{content[:8000]}")
        else:
            # Search result — include a generous snippet
            parts.append(f"- [{r.get('title', 'Untitled')}]({r.get('url', '')}): {content[:500]}")
    return "\n\n".join(parts)


def _format_documents(documents: list[dict[str, Any]]) -> str:
    """Format retrieved documents for LLM context."""
    if not documents:
        return "No document context available."
    parts = []
    for d in documents[:5]:
        parts.append(f"[{d.get('filename', 'doc')} p.{d.get('page_number', '?')}]: {d.get('text', '')[:300]}")
    return "\n".join(parts)
