"""Capability agent: document understanding and synthesis."""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.adapters.llm.lmstudio import get_text_llm, is_garbage_output, strip_repetition
from app.agents.capability_utils import (
    build_reasoning_context,
)
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.document_understanding")

_PROMPT = """You are Pathfinder's Document Understanding Agent.

Help the student understand what their uploaded documents say and how that affects future advice.

Rules:
- Summarize the important document evidence.
- Call out notable extracted profile signals, gaps, and uncertainties.
- If a document appears incomplete or ambiguous, say so briefly.
- Relate the document insight back to the student's question.
"""


async def document_understanding_agent(state: PathfinderState) -> PathfinderState:
    """Synthesize document-heavy questions and uploads."""
    llm = get_text_llm()
    step_progress = list(state.get("step_progress", []))
    step_progress.append("Synthesizing document understanding...")

    context = build_reasoning_context(state, include_web=False)

    response = await llm.ainvoke(
        [
            SystemMessage(content=_PROMPT),
            HumanMessage(content=f"Question:\n{state.get('query', '')}\n\nContext:\n{context}"),
        ]
    )
    draft = strip_repetition(response.content if isinstance(response.content, str) else str(response.content))
    if is_garbage_output(draft):
        log.warning("Document understanding produced unusable output")
        draft = ""

    rationale = list(state.get("answer_rationale", []))
    rationale.append("Document understanding synthesized uploaded evidence with extracted memories")

    updates = {
        **state,
        "draft_answer": draft,
        "answer_rationale": rationale,
        "step_progress": step_progress,
    }
    if state.get("answer_style") == "direct_specialist" and draft:
        updates["final_answer"] = draft
    return updates
