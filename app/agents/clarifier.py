"""Node 3: Clarifier.

Identifies missing information and asks the user for clarification.
Also suggests document uploads when personal data is needed but absent.
"""

from __future__ import annotations

import logging

from langchain_core.messages import SystemMessage, HumanMessage

from app.adapters.llm.lmstudio import get_text_llm
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.clarifier")

_SYSTEM_PROMPT = """You are the Clarifier agent in Pathfinder, an AI academic and career guidance system for students.

The Orchestrator has determined that the user's question needs more information before it can be answered well.

Your job is to:
1. Acknowledge what you understood from their question.
2. Politely explain what specific information is needed and why it will help you give better advice.
3. If the missing info could come from a document (transcript, resume, cover letter, etc.), suggest uploading it using the file attachment button.
4. If the missing info is something the user can type (e.g., target role, GPA, university), ask them directly with example answers.
5. Be specific — don't just say "I need more information." Say exactly what you need.
6. Keep it short — 2-3 sentences max, followed by a bullet list of what you need.
7. If the student's name is known, use it.

Student name: {student_name}
Missing information identified: {missing_info}
"""


async def clarifier(state: PathfinderState) -> PathfinderState:
    """Ask the user for missing information."""
    query = state.get("query", "")
    missing_info = state.get("missing_info", [])
    profile = state.get("profile_data", {})
    personal = profile.get("personal", {}) if profile else {}
    student_name = personal.get("name", "").split()[0] if personal.get("name") else ""

    step_progress = list(state.get("step_progress", []))
    step_progress.append("Identifying what information is needed...")

    llm = get_text_llm()

    response = await llm.ainvoke([
        SystemMessage(content=_SYSTEM_PROMPT.format(
            student_name=student_name or "the student",
            missing_info=missing_info,
        )),
        HumanMessage(content=f"User asked: {query}"),
    ])

    clarification = response.content if isinstance(response.content, str) else str(response.content)

    step_progress.append("Prepared clarification request")
    log.info("Clarifier: requesting info for %s", missing_info)

    return {
        **state,
        "final_answer": clarification,
        "next_node": "responder",
        "confidence_score": 1.0,  # We're confident we need this info
        "step_progress": step_progress,
    }
