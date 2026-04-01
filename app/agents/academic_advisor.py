"""Node 7: Academic Advisor.

Provides academic guidance: major selection, course planning,
university comparison, and requirement matching.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage

from app.adapters.llm.lmstudio import get_text_llm, strip_repetition, is_garbage_output
from app.core.prompts import (
    ACADEMIC_ADVISOR_INSUFFICIENT_DATA_PROMPT,
    ACADEMIC_ADVISOR_SYSTEM_PROMPT,
)
from app.core.quality import classify_web_source
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.academic_advisor")


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
    recent_messages = _format_recent_messages(state.get("messages", []))
    web_text = _format_web_results(web_results)
    doc_text = _format_documents(documents)

    # Check if we have enough course data for recommendations
    courses = profile.get("courses", [])
    is_course_query = _is_course_recommendation_query(query)

    has_verified_course_sources = _has_verified_course_sources(web_results, documents)

    if is_course_query and len(courses) < 4 and not has_verified_course_sources:
        # Insufficient data — ask for more info before recommending
        step_progress.append("Need more course history — asking for clarification")
        log.info("Academic advisor: insufficient course data (%d courses), asking for more", len(courses))

        response = await llm.ainvoke([
            SystemMessage(content=ACADEMIC_ADVISOR_INSUFFICIENT_DATA_PROMPT.format(
                profile=profile_text,
                recent_messages=recent_messages,
            )),
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
    has_live_schedule = _has_live_schedule_sources(web_results)

    response = await llm.ainvoke([
        SystemMessage(content=ACADEMIC_ADVISOR_SYSTEM_PROMPT.format(
            profile=profile_text,
            recent_messages=recent_messages,
            web_results=web_text,
            has_live_schedule="yes" if has_live_schedule else "no",
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


def _format_recent_messages(messages: list[Any]) -> str:
    """Format recent conversation turns for follow-up awareness."""
    if not messages:
        return "No recent conversation available."

    history_lines = []
    for msg in messages[:-1]:
        if isinstance(msg, tuple) and len(msg) == 2:
            role, content = msg
            history_lines.append(f"{role}: {str(content)[:200]}")
        elif hasattr(msg, "content"):
            role = getattr(msg, "type", "unknown")
            history_lines.append(f"{role}: {str(msg.content)[:200]}")

    return "\n".join(history_lines[-6:]) if history_lines else "No recent conversation available."


def _has_verified_course_sources(
    web_results: list[dict[str, Any]], documents: list[dict[str, Any]]
) -> bool:
    """Return True when we have sources strong enough to answer a course question."""
    if documents:
        return True

    for result in web_results:
        source_type, _ = classify_web_source(
            result.get("url", ""),
            result.get("title", ""),
            result.get("content", ""),
        )
        combined = f"{result.get('title', '')} {result.get('content', '')}".lower()

        if source_type in {"degree_page", "schedule_page", "certificate_page"} and any(
            keyword in combined for keyword in ("course", "catalog", "curriculum", "section", "requirements")
        ):
            return True

    return False


def _has_live_schedule_sources(web_results: list[dict[str, Any]]) -> bool:
    """Detect whether current-term schedule pages appear in retrieved web sources."""
    for result in web_results:
        _, time_scope = classify_web_source(
            result.get("url", ""),
            result.get("title", ""),
            result.get("content", ""),
        )
        combined = f"{result.get('title', '')} {result.get('content', '')}".lower()

        if time_scope == "live_schedule" and any(
            keyword in combined for keyword in ("section", "open seats", "registration", "class schedule")
        ):
            return True

    return False
