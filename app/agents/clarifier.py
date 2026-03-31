"""Node 3: Clarifier.

Identifies missing information and asks the user for clarification.
Also suggests document uploads when personal data is needed but absent.
"""

from __future__ import annotations

import logging

from langchain_core.messages import SystemMessage, HumanMessage

from app.adapters.llm.lmstudio import get_text_llm
from app.core.state import PathfinderState
from app.prompts import Prompts

log = logging.getLogger("pathfinder.agents.clarifier")


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
        SystemMessage(content=Prompts.CLARIFIER_SYSTEM.format(
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
