"""Node 9: Interview Prep.

Helps students prepare for interviews: generates personalized questions,
provides answer feedback, and conducts mock interviews.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage

from app.adapters.llm.lmstudio import get_text_llm, strip_repetition, is_garbage_output
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.interview_prep")

_SYSTEM_PROMPT = """You are the Interview Prep agent in Pathfinder, an AI career guidance system for students.

You help students prepare for job interviews based on their background and target roles.

Capabilities:
- Generate personalized interview questions based on the student's resume and target role
- Provide STAR method answer frameworks using the student's actual experience
- Mock interview simulation with follow-up questions
- Technical question preparation (based on listed skills and skill level)
- Behavioral question preparation (based on projects and experience)
- Company-specific interview tips (from web research)
- Salary negotiation guidance

Rules:
1. Use SPECIFIC examples from the student's profile (projects, skills, coursework).
2. Tailor questions to the target role/company if mentioned.
3. Provide both the question AND a suggested answer framework using STAR method.
4. For technical questions, match the difficulty to the student's skill level.
5. Be encouraging but honest about areas that need improvement.
6. Format using markdown — use numbered lists for questions, bold for key phrases.
7. Address the student by name if available.
8. Include a "Preparation Priority" section listing what to focus on most.

Student Profile:
{profile}

Web Research Results:
{web_results}

Retrieved Document Context:
{documents}
"""


async def interview_prep(state: PathfinderState) -> PathfinderState:
    """Generate interview preparation content."""
    query = state.get("query", "")
    profile = state.get("profile_data", {})
    web_results = state.get("web_results", [])
    documents = state.get("retrieved_documents", [])

    step_progress = list(state.get("step_progress", []))
    step_progress.append("Preparing interview guidance...")

    llm = get_text_llm()

    # Format context
    profile_text = _format_profile_for_interview(profile)
    web_text = _format_web_results(web_results)
    doc_text = "\n".join(
        f"[{d.get('filename', 'doc')}]: {d.get('text', '')[:300]}"
        for d in documents[:5]
    ) if documents else "No document context available."

    response = await llm.ainvoke([
        SystemMessage(content=_SYSTEM_PROMPT.format(
            profile=profile_text,
            web_results=web_text,
            documents=doc_text,
        )),
        HumanMessage(content=query),
    ])

    answer = strip_repetition(response.content if isinstance(response.content, str) else str(response.content))

    if is_garbage_output(answer):
        log.warning("Interview prep produced garbage output (%d chars), discarding", len(answer))
        answer = ""

    step_progress.append("Interview preparation ready")
    log.info("Interview prep generated response (%d chars)", len(answer))

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


def _format_profile_for_interview(profile: dict[str, Any]) -> str:
    """Format profile for interview context."""
    parts = []
    personal = profile.get("personal", {})
    if personal.get("university"):
        parts.append(f"University: {personal['university']}")
    if personal.get("program"):
        parts.append(f"Program: {personal['program']}")

    skills = profile.get("skills", [])
    if skills:
        parts.append("Technical Skills: " + ", ".join(s.get("name", "") for s in skills))

    experience = profile.get("experience", [])
    if experience:
        parts.append("Experience:")
        for exp in experience:
            parts.append(f"  - {exp.get('role', 'Role')} at {exp.get('name', 'Company')}")

    projects = profile.get("projects", [])
    if projects:
        parts.append("Projects:")
        for proj in projects:
            techs = proj.get("technologies", "")
            parts.append(f"  - {proj.get('name', '')}: {proj.get('description', '')[:100]} [{techs}]")

    courses = profile.get("courses", [])
    if courses:
        parts.append("Relevant Courses: " + ", ".join(
            c.get("name", c.get("code", "")) for c in courses[:10]
        ))

    return "\n".join(parts) if parts else "No profile data available."
