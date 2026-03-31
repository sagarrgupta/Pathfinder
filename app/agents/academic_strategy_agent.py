"""Capability agent: academic strategy reasoning."""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.adapters.llm.lmstudio import get_text_llm, is_garbage_output, strip_repetition
from app.agents.capability_utils import (
    build_reasoning_context,
)
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.academic_strategy")

_PROMPT = """You are Pathfinder's Academic Strategy Agent.

You are reasoning over a student's profile, semantic memory, documents, and optional web evidence.
Give personalized academic guidance, not generic advice.

Rules:
- Use only evidence actually present in context.
- If specifics like course codes are not evidenced, recommend course types or decision criteria instead.
- Explicitly use known goals, constraints, and preferences when relevant.
- If important information is missing, still answer what you can and mention the most valuable missing detail briefly.
- If there is a conflict, do not nag repeatedly; acknowledge the uncertainty only if it materially affects the answer.
- End with clear next steps.
"""


async def academic_strategy_agent(state: PathfinderState) -> PathfinderState:
    """Produce academic guidance using the new memory pack."""
    llm = get_text_llm()
    step_progress = list(state.get("step_progress", []))
    step_progress.append("Reasoning through academic context...")

    context = build_reasoning_context(state, include_web=bool(state.get("web_results")))

    response = await llm.ainvoke(
        [
            SystemMessage(content=_PROMPT),
            HumanMessage(content=f"Question:\n{state.get('query', '')}\n\nContext:\n{context}"),
        ]
    )
    draft = strip_repetition(response.content if isinstance(response.content, str) else str(response.content))
    if is_garbage_output(draft):
        log.warning("Academic strategy produced unusable output")
        draft = ""

    rationale = list(state.get("answer_rationale", []))
    rationale.append("Academic strategy used scoped profile + semantic memory + supporting evidence")

    updates = {
        **state,
        "draft_answer": draft,
        "answer_rationale": rationale,
        "step_progress": step_progress,
    }
    if state.get("answer_style") == "direct_specialist" and draft:
        updates["final_answer"] = draft
    return updates
