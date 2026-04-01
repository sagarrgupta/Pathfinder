"""Node 10: Evaluator.

Checks the draft answer for groundedness, assigns a confidence score,
detects hallucinations, and passively learns profile updates from the conversation.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage

from app.adapters.llm.lmstudio import get_text_llm
from app.adapters.neo4j.graph_store import store_extracted_entities, update_student
from app.core.prompts import (
    EVALUATOR_PROMPT,
    EVALUATOR_REWRITE_PROMPT,
    EVALUATOR_REWRITE_SYSTEM_PROMPT,
    EVALUATOR_SYSTEM_PROMPT,
)
from app.core.quality import (
    DecisionPayload,
    add_handoff_note,
    add_working_memory_item,
    complete_task,
    fail_task,
    init_working_memory,
    recent_handoff_context,
    start_task,
    summarize_trace,
)
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.evaluator")


async def evaluator(state: PathfinderState) -> PathfinderState:
    """Evaluate the draft answer for quality and groundedness."""
    draft = state.get("draft_answer", "")
    query = state.get("query", "")
    documents = state.get("retrieved_documents", [])
    web_results = state.get("web_results", [])
    evidence_records = state.get("evidence_records", [])
    decision_payload = state.get("decision_payload", {})
    working_memory = init_working_memory(state.get("working_memory", {}))
    task_graph = state.get("task_graph", [])
    blocked_reasons = list(state.get("blocked_reasons", []))
    task_graph = start_task(task_graph, "render_final_answer")
    handoff_context = recent_handoff_context(working_memory, to_node="evaluator")

    step_progress = list(state.get("step_progress", []))
    step_progress.append("Verifying answer quality...")

    if not draft:
        # No draft to evaluate — nothing to do
        task_graph = fail_task(task_graph, "render_final_answer", reason="No draft answer produced by upstream planner.")
        return {
            **state,
            "confidence_score": 0.0,
            "is_grounded": False,
            "task_graph": task_graph,
            "step_progress": step_progress,
            "next_node": "responder",
        }

    llm = get_text_llm()

    # Compile sources
    sources = []
    for d in documents[:5]:
        sources.append(f"[Document: {d.get('filename', 'unknown')}] {d.get('text', '')[:1000]}")
    for w in web_results[:8]:
        title = w.get("title", "")
        url = w.get("url", "")
        content = w.get("content", "")
        sources.append(f"[Web: {title}] ({url}) {content[:1500]}")
    sources_text = "\n".join(sources) if sources else "No sources available."

    response = await llm.ainvoke([
        SystemMessage(content=EVALUATOR_SYSTEM_PROMPT),
        HumanMessage(content=EVALUATOR_PROMPT.format(
            draft=draft[:2000],
            sources=f"{sources_text}\n\nHandoff context:\n{json.dumps(handoff_context, ensure_ascii=True)}",
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
        parsed = {
            "is_grounded": False,
            "confidence_score": 0.0,
            "issues": ["Evaluator could not parse its own review output"],
            "profile_updates": [],
            "needs_disclaimer": False,
            "disclaimer": "",
        }

    is_grounded = parsed.get("is_grounded", True)
    confidence = parsed.get("confidence_score", 0.5)
    profile_updates = parsed.get("profile_updates", [])
    needs_disclaimer = parsed.get("needs_disclaimer", False)
    disclaimer = parsed.get("disclaimer", "")
    issues = parsed.get("issues", [])

    # ── Handle low-confidence / ungrounded answers ──
    final_draft = draft
    validated_payload = _validate_decision_payload(decision_payload, evidence_records)
    if validated_payload:
        original_recommendations = len(decision_payload.get("recommended_items", []))
        kept_recommendations = len(validated_payload.get("recommended_items", []))
        decision_payload = validated_payload
        dropped_count = max(0, original_recommendations - kept_recommendations)
        if dropped_count:
            working_memory = add_working_memory_item(
                working_memory,
                "dropped_claims",
                f"Dropped {dropped_count} unsupported recommendation(s) during evaluator validation.",
            )
        for item in validated_payload.get("blocked_or_uncertain_items", []):
            if item.get("kind") in {"blocked", "needs_verification"}:
                blocked_reasons.append(item.get("reason", ""))
                working_memory = add_working_memory_item(working_memory, "planner_blockers", item.get("reason", ""))

    structured_recommendations = len(decision_payload.get("recommended_items", [])) if isinstance(decision_payload, dict) else 0
    has_structured_plan = structured_recommendations > 0
    must_rewrite = ((confidence < 0.65) or (not is_grounded)) and not has_structured_plan
    if must_rewrite:
        rewrite = await _rewrite_grounded_answer(query, draft, issues, sources_text)
        if rewrite:
            final_draft = rewrite
            log.warning("Evaluator rewrote low-grounded answer (confidence %.2f)", confidence)
        elif confidence < 0.4 and not is_grounded:
            warning = (
                "I could not verify enough official information to answer this confidently. "
                "Please check the official catalog or share the specific program page you want me to analyze."
            )
            final_draft = warning
            blocked_reasons.append(warning)
    elif needs_disclaimer and disclaimer:
        final_draft = f"{draft}\n\n⚠️ *{disclaimer}*"
    elif has_structured_plan and confidence < 0.65:
        confidence = max(confidence, 0.68)

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
                    label = _field_to_label(field)
                    entities.append({
                        "label": label,
                        "properties": {"name": value},
                        "relationship": _label_to_relationship(label),
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
    task_graph = complete_task(task_graph, "render_final_answer")
    trace_summary = summarize_trace({
        **state,
        "task_graph": task_graph,
        "working_memory": working_memory,
        "blocked_reasons": [reason for reason in blocked_reasons if reason],
        "confidence_score": confidence,
        "decision_payload": decision_payload,
    })

    log.info("Evaluator: confidence=%.2f grounded=%s updates=%d issues=%s",
             confidence, is_grounded, len(profile_updates), issues)
    working_memory = add_handoff_note(
        working_memory,
        from_node="evaluator",
        to_node="responder",
        contract="validated_answer",
        summary=f"confidence={confidence:.2f}; grounded={bool(is_grounded)}; blocked={len(blocked_reasons)}",
    )

    return {
        **state,
        "draft_answer": final_draft,
        "confidence_score": confidence,
        "is_grounded": is_grounded,
        "profile_updates": profile_updates,
        "decision_payload": decision_payload,
        "working_memory": working_memory,
        "task_graph": task_graph,
        "blocked_reasons": [reason for reason in blocked_reasons if reason],
        "trace_summary": trace_summary,
        "stop_reason": state.get("stop_reason", "") or _evaluate_stop_reason(decision_payload, blocked_reasons),
        "step_progress": step_progress,
        "next_node": "responder",
    }


async def _rewrite_grounded_answer(
    query: str, draft: str, issues: list[str], sources_text: str
) -> str:
    """Attempt to repair an answer by restricting it to verified sources."""
    if not sources_text or sources_text == "No sources available.":
        return ""

    llm = get_text_llm()
    response = await llm.ainvoke([
        SystemMessage(content=EVALUATOR_REWRITE_SYSTEM_PROMPT),
        HumanMessage(content=EVALUATOR_REWRITE_PROMPT.format(
            query=query,
            draft=draft[:2500],
            issues=", ".join(issues[:8]) if issues else "None listed",
            sources=sources_text[:12000],
        )),
    ])
    content = response.content if isinstance(response.content, str) else str(response.content)
    return content.strip()


def _field_to_label(field: str) -> str:
    """Map a profile update field name to an entity label."""
    mapping = {
        "interest": "Interest", "interests": "Interest",
        "goal": "Goal", "goals": "Goal",
        "skill": "Skill", "skills": "Skill",
        "company": "Company", "experience": "Company",
        "project": "Project", "projects": "Project",
        "course": "Course", "courses": "Course",
    }
    return mapping.get(field.lower(), "Interest")


def _validate_decision_payload(
    payload: DecisionPayload, evidence_records: list[dict[str, Any]]
) -> DecisionPayload:
    """Drop unsupported recommendations from a structured planner payload."""
    if not payload:
        return {}

    supported_urls = {record.get("source_url", "") for record in evidence_records if record.get("source_url")}
    supported_codes = {
        record.get("value", {}).get("code", "")
        for record in evidence_records
        if isinstance(record.get("value"), dict)
    }

    source_refs = payload.get("source_refs", [])
    valid_refs = [ref for ref in source_refs if ref.get("url", "") in supported_urls or not ref.get("url")]
    evidence_texts = [
        " ".join(
            str(part)
            for part in (
                record.get("source_title", ""),
                record.get("excerpt", ""),
                record.get("value", {}).get("name", "") if isinstance(record.get("value"), dict) else "",
                record.get("value", {}).get("code", "") if isinstance(record.get("value"), dict) else "",
                record.get("value", {}).get("summary", "") if isinstance(record.get("value"), dict) else "",
            )
        ).lower()
        for record in evidence_records
    ]

    validated_recommendations = []
    for item in payload.get("recommended_items", []):
        codes = set(item.get("support_codes", []))
        has_code_support = bool(codes & supported_codes)
        support_refs = item.get("support_refs", []) if isinstance(item.get("support_refs"), list) else []
        has_item_ref_support = any(
            isinstance(ref, dict) and (ref.get("url", "") in supported_urls or not ref.get("url"))
            for ref in support_refs
        )
        has_ref_support = _item_has_textual_support(item, evidence_texts, valid_refs)
        if has_code_support or has_ref_support or has_item_ref_support:
            validated_recommendations.append(item)

    validated = dict(payload)
    validated["recommended_items"] = validated_recommendations
    validated["source_refs"] = valid_refs

    dropped = len(payload.get("recommended_items", [])) - len(validated_recommendations)
    if dropped > 0:
        blocked = list(validated.get("blocked_or_uncertain_items", []))
        blocked.append({
            "label": "Some recommendations were removed",
            "reason": f"{dropped} unsupported recommendation(s) were dropped during quality validation.",
            "kind": "needs_verification",
        })
        validated["blocked_or_uncertain_items"] = blocked

    return validated


def _item_has_textual_support(
    item: dict[str, Any],
    evidence_texts: list[str],
    valid_refs: list[dict[str, Any]],
) -> bool:
    """Check whether a recommendation is textually grounded in evidence."""
    label = str(item.get("label", "")).strip().lower()
    reason = str(item.get("reason", "")).strip().lower()
    if not label and not reason:
        return False

    item_tokens = _support_tokens(label)
    if len(item_tokens) < 2 and not _looks_like_course_label(label):
        return False

    ref_texts = [
        " ".join(
            str(part)
            for part in (ref.get("title", ""), ref.get("excerpt", ""), ref.get("entity_type", ""))
        ).lower()
        for ref in valid_refs
    ]

    for text in evidence_texts + ref_texts:
        if _looks_like_course_label(label) and label in text:
            return True
        overlap = [token for token in item_tokens if token in text]
        if len(overlap) >= min(2, len(item_tokens)):
            return True
        if reason:
            reason_tokens = _support_tokens(reason)
            if len([token for token in reason_tokens if token in text]) >= 3:
                return True
    return False


def _support_tokens(text: str) -> list[str]:
    tokens = []
    for token in re.findall(r"[a-z0-9]{2,}", text.lower()):
        if token not in {"the", "and", "for", "with", "this", "that", "from", "your", "good", "best", "option"} and token not in tokens:
            tokens.append(token)
    return tokens


def _looks_like_course_label(label: str) -> bool:
    return bool(re.search(r"\b[A-Z]{2,4}\s?-?\d{3}[A-Z]?\b", label or "", re.I))


def _label_to_relationship(label: str) -> str:
    """Map an entity label to a relationship type."""
    mapping = {
        "Interest": "INTERESTED_IN",
        "Goal": "HAS_GOAL",
        "Skill": "HAS_SKILL",
        "Company": "WORKED_AT",
        "Project": "COMPLETED",
        "Course": "TOOK",
    }
    return mapping.get(label, "HAS")


def _evaluate_stop_reason(payload: dict[str, Any], blocked_reasons: list[str]) -> str:
    blocked_markers = payload.get("blocked_reasons", []) if isinstance(payload, dict) else []
    for marker in blocked_markers:
        if isinstance(marker, str) and marker.startswith("hard_blocked"):
            return "hard_blocked"
        if isinstance(marker, str) and marker.startswith("safe_partial_plan"):
            return "safe_partial_plan"
    if blocked_reasons:
        return "partial_answer"
    return ""
