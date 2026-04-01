"""Node 7: Academic Advisor.

Provides academic guidance: major selection, course planning,
university comparison, and requirement matching.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage

from app.adapters.llm.lmstudio import get_text_llm, strip_repetition, is_garbage_output
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.academic_advisor")

# ── Prompt when we have SUFFICIENT data ──────────────────────────
_SYSTEM_PROMPT = """You are the Academic Advisor agent in Pathfinder, an AI academic guidance system for students.

You have access to the student's profile data, web research results, and retrieved documents.
Your job is to provide personalized, actionable academic advice that stays grounded in the supplied evidence.

Capabilities:
- Major/minor selection based on strengths and interests
- Course planning and scheduling recommendations
- University comparison and admission guidance
- Program requirement matching (prerequisites, GPA requirements)
- Research opportunity identification
- Academic goal planning (PhD prep, thesis topics, etc.)
- Summarizing and analyzing web content the student shares with you

GROUNDING RULES:
1. Treat the profile, web results, and documents as the only available evidence.
2. NEVER invent course codes, course titles, prerequisites, deadlines, GPA thresholds, transfer rules, policies, faculty names, or program details.
3. Recommend a specific course only if that exact course appears in the provided web results or documents.
4. If you lack verified course/catalog data, recommend categories of courses or decision criteria instead of named courses.
5. Separate supported facts from inference. Use clear phrases like "Based on your profile..." and "I don't have enough evidence to confirm...".
6. Acknowledge important missing information before making high-stakes recommendations.
7. Cite web sources with URLs when using external information.
8. If the user asked to summarize a page or article, summarize only what appears in the provided content and do not add outside claims.
9. Be encouraging but realistic.
10. Provide actionable next steps that follow from the available evidence.
11. Format using markdown for readability.
12. Address the student by name if available.

Suggested response shape:
- Short answer
- What the evidence suggests
- Gaps or uncertainty
- Concrete next steps

Student Profile:
{profile}

Web Research Results:
{web_results}

Retrieved Document Context:
{documents}
"""

# ── Prompt when we LACK course data ──────────────────────────────
_INSUFFICIENT_DATA_PROMPT = """You are the Academic Advisor agent in Pathfinder, an AI academic guidance system.

The student is asking about course recommendations, but you do NOT have enough information about their completed coursework.

Here's what you know:
{profile}

What's MISSING:
- Full list of courses the student has already taken
- Prerequisites they've completed
- Their specific focus areas within their program

YOUR TASK:
Generate a helpful response that:
1. Acknowledges what you know about them (name, GPA, skills, goals) — be brief.
2. Explains WHY you need their full course history before recommending specific courses.
3. Asks them to do ONE of these:
   - Upload their academic transcript (PDF) using the file upload button
   - OR type out the courses they've already completed
4. Mention that once you have their course history, you can give much better, personalized recommendations.
5. Keep the tone warm, helpful, and encouraging.
6. Do NOT provide any specific course recommendations — that comes AFTER they share their history.
7. Do NOT guess likely completed courses or likely prerequisites.
8. Format using markdown.
"""


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

    if is_course_query and len(courses) < 4:
        # Insufficient data — ask for more info before recommending
        step_progress.append("Need more course history — asking for clarification")
        log.info("Academic advisor: insufficient course data (%d courses), asking for more", len(courses))

        response = await llm.ainvoke([
            SystemMessage(content=_INSUFFICIENT_DATA_PROMPT.format(profile=profile_text)),
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
        SystemMessage(content=_SYSTEM_PROMPT.format(
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
