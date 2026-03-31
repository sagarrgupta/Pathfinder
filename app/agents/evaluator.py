"""Node 10: Evaluator.

Checks the draft answer for groundedness, assigns a confidence score,
detects hallucinations, and passively learns profile updates from the conversation.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage

from app.adapters.llm.lmstudio import get_text_llm
from app.adapters.neo4j.graph_store import store_extracted_entities, update_student
from app.core.state import PathfinderState
from app.graph.ontology import field_to_label, label_to_relationship
from app.prompts import Prompts
from app.utils.json_llm import parse_json_object

log = logging.getLogger("pathfinder.agents.evaluator")


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
        SystemMessage(content=Prompts.EVALUATION_SYSTEM),
        HumanMessage(content=Prompts.evaluation_user(
            draft=draft[:2000],
            sources=sources_text,
            query=query,
        )),
    ])

    content = response.content if isinstance(response.content, str) else str(response.content)

    # Parse evaluation
    parsed = parse_json_object(content)
    if not parsed:
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

    # ── Passively learn: persist profile updates detected from conversation ──
    student_id = state.get("student_id", "default")
    if profile_updates:
        try:
            # Separate student-level properties from entity updates
            student_props = {}
            entities = []
            for update in profile_updates:
                field = update.get("field", "")
                value = update.get("value", "")
                if not field or not value:
                    continue
                # Student-level fields (name, gpa, university, etc.)
                if field.lower() in ("name", "gpa", "university", "program", "email", "semester"):
                    student_props[field.lower()] = value
                else:
                    # Treat as entity (interest, goal, skill, etc.)
                    label = field_to_label(field)
                    entities.append({
                        "label": label,
                        "properties": {"name": value},
                        "relationship": label_to_relationship(label),
                    })

            if student_props:
                await update_student(student_id, **student_props)
                log.info("Evaluator: passively updated student props: %s", list(student_props.keys()))

            if entities:
                count = await store_extracted_entities(entities, "conversation", student_id)
                log.info("Evaluator: passively stored %d entities from conversation", count)

        except Exception as exc:
            log.warning("Evaluator: failed to persist profile updates: %s", exc)

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
