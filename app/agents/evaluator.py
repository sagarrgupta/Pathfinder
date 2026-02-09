"""Node 10: Evaluator.

Checks the draft answer for groundedness, assigns a confidence score,
detects hallucinations, and passively learns profile updates from the conversation.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage

from app.adapters.llm.lmstudio import get_text_llm
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.evaluator")

_EVALUATION_PROMPT = """You are the Evaluator agent in Pathfinder. Your job is to assess the quality of a draft answer.

Evaluate the draft answer against the available sources and respond with JSON:
{{
    "is_grounded": true/false,
    "confidence_score": 0.0 to 1.0,
    "issues": ["list of any issues found"],
    "profile_updates": [
        {{"field": "name", "value": "detected value", "source": "conversation"}}
    ],
    "needs_disclaimer": true/false,
    "disclaimer": "optional disclaimer text if the answer contains uncertain claims"
}}

Scoring guide:
- 1.0: Every claim is directly supported by sources
- 0.8-0.9: Most claims supported, minor inferences
- 0.6-0.7: Some claims supported, some reasonable inferences
- 0.4-0.5: Limited source support, significant inferences
- 0.0-0.3: Mostly unsupported or fabricated

Key checks:
- Are specific course codes/names real or fabricated?
- Are university-specific claims backed by web results?
- Does the answer acknowledge what data it lacks?
- Is the advice appropriate given the available information?

Also check for "profile_updates" — if the user's original question reveals new information
about themselves (e.g., "I'm interested in machine learning" or "I got an A in CSC 200"),
extract these as profile updates.

Draft answer:
{draft}

Available sources:
{sources}

Original user query:
{query}
"""


async def evaluator(state: PathfinderState) -> PathfinderState:
    """Evaluate the draft answer for quality and groundedness."""
    draft = state.get("draft_answer", "")
    query = state.get("query", "")
    documents = state.get("retrieved_documents", [])
    web_results = state.get("web_results", [])

    step_progress = list(state.get("step_progress", []))
    step_progress.append("Verifying answer quality...")

    if not draft:
        # No draft to evaluate — nothing to do
        return {
            **state,
            "confidence_score": 0.0,
            "is_grounded": False,
            "step_progress": step_progress,
            "next_node": "responder",
        }

    llm = get_text_llm()

    # Compile sources
    sources = []
    for d in documents[:5]:
        sources.append(f"[Document: {d.get('filename', 'unknown')}] {d.get('text', '')[:300]}")
    for w in web_results[:5]:
        sources.append(f"[Web: {w.get('title', '')}] {w.get('content', '')[:300]}")
    sources_text = "\n".join(sources) if sources else "No sources available."

    response = await llm.ainvoke([
        SystemMessage(content="You are an answer quality evaluator."),
        HumanMessage(content=_EVALUATION_PROMPT.format(
            draft=draft[:2000],
            sources=sources_text,
            query=query,
        )),
    ])

    content = response.content if isinstance(response.content, str) else str(response.content)

    # Parse evaluation
    try:
        json_start = content.find("{")
        json_end = content.rfind("}") + 1
        parsed = json.loads(content[json_start:json_end])
    except (json.JSONDecodeError, ValueError):
        parsed = {"is_grounded": True, "confidence_score": 0.5, "issues": [], "profile_updates": []}

    is_grounded = parsed.get("is_grounded", True)
    confidence = parsed.get("confidence_score", 0.5)
    profile_updates = parsed.get("profile_updates", [])
    needs_disclaimer = parsed.get("needs_disclaimer", False)
    disclaimer = parsed.get("disclaimer", "")
    issues = parsed.get("issues", [])

    # ── Handle low-confidence / ungrounded answers ──
    final_draft = draft

    if confidence < 0.4 and not is_grounded:
        # Very low confidence — prepend a strong warning
        warning = (
            "⚠️ **Important Notice:** The information below is based on general knowledge "
            "and may not reflect your university's actual course offerings. "
            "I recommend checking your university's course catalog for accurate, up-to-date information.\n\n"
        )
        final_draft = warning + draft
        log.warning("Low confidence (%.2f) — added warning disclaimer", confidence)
    elif needs_disclaimer and disclaimer:
        final_draft = f"{draft}\n\n⚠️ *{disclaimer}*"

    step_progress.append(f"Confidence: {confidence:.0%} — Grounded: {'Yes' if is_grounded else 'Needs review'}")

    log.info("Evaluator: confidence=%.2f grounded=%s updates=%d issues=%s",
             confidence, is_grounded, len(profile_updates), issues)

    return {
        **state,
        "draft_answer": final_draft,
        "confidence_score": confidence,
        "is_grounded": is_grounded,
        "profile_updates": profile_updates,
        "step_progress": step_progress,
        "next_node": "responder",
    }
