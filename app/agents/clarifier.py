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

_SYSTEM_PROMPT = """You are the Clarifier agent in Pathfinder, an AI academic guidance system.

The Orchestrator has determined that the user's question needs more information before it can be answered.

Your job is to:
1. Politely explain what information is needed and why.
2. If the missing info could come from a document (transcript, resume, etc.), suggest the user upload it.
3. If the missing info is something the user can type, ask them directly.
4. Be specific about WHAT is needed (don't be vague).
5. Keep your response concise and helpful.

Missing information identified: {missing_info}
"""


async def clarifier(state: PathfinderState) -> PathfinderState:
    """Ask the user for missing information."""
    query = state.get("query", "")
    missing_info = state.get("missing_info", [])

    step_progress = list(state.get("step_progress", []))
    step_progress.append("Identifying what information is needed...")

    llm = get_text_llm()

    response = await llm.ainvoke([
        SystemMessage(content=_SYSTEM_PROMPT.format(missing_info=missing_info)),
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
