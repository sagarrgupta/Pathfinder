"""Capability agent: interview coaching reasoning."""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.adapters.llm.lmstudio import get_text_llm, is_garbage_output, strip_repetition
from app.agents.capability_utils import (
    build_reasoning_context,
)
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.interview_coach")

_PROMPT = """You are Pathfinder's Interview Coach Agent.

Create personalized interview preparation based on the student's actual background.

Rules:
- Use concrete student experiences, projects, or coursework where possible.
- Balance behavioral and technical preparation depending on the question.
- If the target role/company is unclear, make that explicit and give broadly useful preparation guidance.
- Provide practice priorities and answer frameworks, not just sample questions.
"""


async def interview_coach_agent(state: PathfinderState) -> PathfinderState:
    """Produce interview-focused guidance."""
    llm = get_text_llm()
    step_progress = list(state.get("step_progress", []))
    step_progress.append("Preparing interview coaching...")

    context = build_reasoning_context(state, include_web=bool(state.get("web_results")))

    response = await llm.ainvoke(
        [
            SystemMessage(content=_PROMPT),
            HumanMessage(content=f"Question:\n{state.get('query', '')}\n\nContext:\n{context}"),
        ]
    )
    draft = strip_repetition(response.content if isinstance(response.content, str) else str(response.content))
    if is_garbage_output(draft):
        log.warning("Interview coach produced unusable output")
        draft = ""

    rationale = list(state.get("answer_rationale", []))
    rationale.append("Interview coach grounded preparation in the student's profile and evidence")

    updates = {
        **state,
        "draft_answer": draft,
        "answer_rationale": rationale,
        "step_progress": step_progress,
    }
    if state.get("answer_style") == "direct_specialist" and draft:
        updates["final_answer"] = draft
    return updates
