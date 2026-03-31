"""Capability agent: comparison and decision-support reasoning."""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.adapters.llm.lmstudio import get_text_llm, is_garbage_output, strip_repetition
from app.agents.capability_utils import (
    build_reasoning_context,
)
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.decision_comparison")

_PROMPT = """You are Pathfinder's Decision Comparison Agent.

Help the student compare options or make a decision using the known profile, memories, documents, and any web evidence.

Rules:
- Organize reasoning as options, fit, tradeoffs, and recommendation.
- Explicitly incorporate the student's goals, constraints, and preferences when available.
- If evidence is thin, say so and compare using criteria instead of pretending certainty.
- Make the recommendation personalized, not generic.
"""


async def decision_comparison_agent(state: PathfinderState) -> PathfinderState:
    """Provide general decision-support when no narrower specialist is a better fit."""
    llm = get_text_llm()
    step_progress = list(state.get("step_progress", []))
    step_progress.append("Comparing options against your profile...")

    context = build_reasoning_context(state, include_web=bool(state.get("web_results")))

    response = await llm.ainvoke(
        [
            SystemMessage(content=_PROMPT),
            HumanMessage(content=f"Question:\n{state.get('query', '')}\n\nContext:\n{context}"),
        ]
    )
    draft = strip_repetition(response.content if isinstance(response.content, str) else str(response.content))
    if is_garbage_output(draft):
        log.warning("Decision comparison produced unusable output")
        draft = ""

    rationale = list(state.get("answer_rationale", []))
    rationale.append("Decision comparison weighed options against the student's context and constraints")

    updates = {
        **state,
        "draft_answer": draft,
        "answer_rationale": rationale,
        "step_progress": step_progress,
    }
    if state.get("answer_style") == "direct_specialist" and draft:
        updates["final_answer"] = draft
    return updates
