"""Node 8: Career Planner.

Provides career guidance: job matching, skill gap analysis,
career paths, and course scheduling for career goals.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage

from app.adapters.llm.lmstudio import get_text_llm, strip_repetition, is_garbage_output
from app.core.prompts import CAREER_PLANNER_SYSTEM_PROMPT
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.career_planner")


async def career_planner(state: PathfinderState) -> PathfinderState:
    """Generate career advice based on profile and research."""
    query = state.get("query", "")
    profile = state.get("profile_data", {})
    web_results = state.get("web_results", [])
    documents = state.get("retrieved_documents", [])

    step_progress = list(state.get("step_progress", []))
    step_progress.append("Analyzing career opportunities...")

    llm = get_text_llm()

    # Format context
    profile_text = _format_profile_for_career(profile)
    web_text = _format_web_results(web_results)
    doc_text = "\n".join(
        f"[{d.get('filename', 'doc')}]: {d.get('text', '')[:300]}"
        for d in documents[:5]
    ) if documents else "No document context available."

    response = await llm.ainvoke([
        SystemMessage(content=CAREER_PLANNER_SYSTEM_PROMPT.format(
            profile=profile_text,
            web_results=web_text,
            documents=doc_text,
        )),
        HumanMessage(content=query),
    ])

    answer = strip_repetition(response.content if isinstance(response.content, str) else str(response.content))

    # Guard: if the model hallucinated tool calls or produced garbage,
    # leave draft_answer empty so the responder can generate from context.
    if is_garbage_output(answer):
        log.warning("Career planner produced garbage output (%d chars), discarding", len(answer))
        answer = ""

    step_progress.append("Career analysis complete")
    log.info("Career planner generated response (%d chars)", len(answer))

    return {
        **state,
        "draft_answer": answer,
        "step_progress": step_progress,
        "next_node": "evaluator",
    }


def _format_web_results(results: list[dict[str, Any]]) -> str:
    """Format web results — direct URL fetches get full content."""
    if not results:
        return "No web results available."
    parts = []
    for r in results[:5]:
        source = r.get("source", "")
        content = r.get("content", "")
        if source == "direct_url":
            parts.append(f"### [{r.get('title', 'Page')}]({r.get('url', '')})\n{content[:8000]}")
        else:
            parts.append(f"- [{r.get('title', 'Untitled')}]({r.get('url', '')}): {content[:500]}")
    return "\n\n".join(parts)


def _format_profile_for_career(profile: dict[str, Any]) -> str:
    """Format profile data with emphasis on career-relevant info."""
    parts = []
    personal = profile.get("personal", {})
    if personal.get("name"):
        parts.append(f"Name: {personal['name']}")
    if personal.get("university"):
        parts.append(f"University: {personal['university']}")
    if personal.get("program"):
        parts.append(f"Program: {personal['program']}")
    if personal.get("gpa"):
        parts.append(f"GPA: {personal['gpa']}")

    skills = profile.get("skills", [])
    if skills:
        parts.append("Skills: " + ", ".join(
            f"{s.get('name', '')} ({s.get('proficiency', 'unknown')})" for s in skills
        ))

    experience = profile.get("experience", [])
    if experience:
        parts.append("Experience:")
        for exp in experience:
            parts.append(f"  - {exp.get('name', '')} ({exp.get('role', 'unknown role')})")

    projects = profile.get("projects", [])
    if projects:
        parts.append("Projects:")
        for proj in projects:
            parts.append(f"  - {proj.get('name', '')}: {proj.get('description', '')[:100]}")

    goals = profile.get("goals", [])
    if goals:
        parts.append("Career Goals: " + ", ".join(g.get("name", "") for g in goals))

    return "\n".join(parts) if parts else "No profile data available."
