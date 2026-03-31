"""Capability agent: career strategy reasoning."""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.adapters.llm.lmstudio import get_text_llm, is_garbage_output, strip_repetition
from app.agents.capability_utils import (
    build_reasoning_context,
)
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.career_strategy")

_PROMPT = """You are Pathfinder's Career Strategy Agent.

Give student-specific career guidance using profile facts, reusable memory, documents, and external evidence.

Rules:
- Reason in terms of fit, gaps, tradeoffs, and concrete actions.
- Mention where the student's current skills/projects/experience help or fall short.
- If web evidence contains opportunities or labor market info, use it carefully and cite it in the later final answer.
- If key information is missing, give the best partial answer now and mention only the most valuable follow-up data.
- Keep the guidance actionable and honest.
"""


async def career_strategy_agent(state: PathfinderState) -> PathfinderState:
    """Produce career guidance using layered memory and retrieval outputs."""
    llm = get_text_llm()
    step_progress = list(state.get("step_progress", []))
    step_progress.append("Reasoning through career context...")

    context = build_reasoning_context(state, include_web=bool(state.get("web_results")))

    response = await llm.ainvoke(
        [
            SystemMessage(content=_PROMPT),
            HumanMessage(content=f"Question:\n{state.get('query', '')}\n\nContext:\n{context}"),
        ]
    )
    draft = strip_repetition(response.content if isinstance(response.content, str) else str(response.content))
    if is_garbage_output(draft):
        log.warning("Career strategy produced unusable output")
        draft = ""

    rationale = list(state.get("answer_rationale", []))
    rationale.append("Career strategy compared current profile strengths/gaps against the requested goal")

    updates = {
        **state,
        "draft_answer": draft,
        "answer_rationale": rationale,
        "step_progress": step_progress,
    }
    if state.get("answer_style") == "direct_specialist" and draft:
        updates["final_answer"] = draft
    return updates
