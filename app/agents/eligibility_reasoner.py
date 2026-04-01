"""Node: Eligibility Reasoner.

Handles "can I take/apply/do this?" questions using structured evidence,
student state, and explicit assumptions/blockers.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.adapters.llm.lmstudio import get_text_llm
from app.core.prompts import ELIGIBILITY_REASONER_PROMPT
from app.core.quality import (
    DecisionPayload,
    add_handoff_note,
    add_working_memory_item,
    build_support_ref,
    complete_task,
    group_evidence_records,
    init_working_memory,
    recent_handoff_context,
    start_task,
)
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.eligibility_reasoner")


async def eligibility_reasoner(state: PathfinderState) -> PathfinderState:
    """Generate structured eligibility guidance."""
    query = state.get("query", "")
    summary = state.get("session_summary", {})
    profile = state.get("profile_data", {})
    evidence_records = state.get("evidence_records", [])
    evidence_groups = group_evidence_records(evidence_records, profile)
    working_memory = init_working_memory(state.get("working_memory", {}))
    task_graph = state.get("task_graph", [])
    blocked_reasons = list(state.get("blocked_reasons", []))
    task_graph = start_task(task_graph, "compare_to_student_state")
    task_graph = start_task(task_graph, "check_blockers")
    task_graph = start_task(task_graph, "rank_options")
    handoff_context = recent_handoff_context(working_memory, to_node="eligibility_reasoner")

    step_progress = list(state.get("step_progress", []))
    step_progress.append("Checking eligibility and blockers...")

    baseline = _heuristic_eligibility_payload(summary, evidence_groups)
    llm_payload = await _llm_eligibility_payload(query, summary, evidence_groups, handoff_context)
    merged = _merge_payloads(baseline, llm_payload)

    for assumption in merged.get("assumptions", []):
        working_memory = add_working_memory_item(working_memory, "active_assumptions", assumption)
    for item in merged.get("blocked_or_uncertain_items", []):
        if item.get("kind") in {"blocked", "needs_verification"}:
            blocked_reasons.append(item.get("reason", ""))
            working_memory = add_working_memory_item(working_memory, "planner_blockers", item.get("reason", ""))

    working_memory = add_working_memory_item(
        working_memory,
        "ranking_rationale",
        "Eligibility reasoner separated verified rules, conditional assumptions, and missing evidence.",
    )
    task_graph = complete_task(task_graph, "compare_to_student_state")
    if blocked_reasons:
        task_graph = complete_task(task_graph, "check_blockers")
    task_graph = complete_task(task_graph, "rank_options")
    working_memory = add_handoff_note(
        working_memory,
        from_node="eligibility_reasoner",
        to_node="evaluator",
        contract="decision_payload",
        summary=(
            f"recommended={len(merged.get('recommended_items', []))}; "
            f"blocked={len(merged.get('blocked_or_uncertain_items', []))}"
        ),
    )

    return {
        **state,
        "decision_payload": merged,
        "draft_answer": "",
        "working_memory": working_memory,
        "task_graph": task_graph,
        "blocked_reasons": [reason for reason in blocked_reasons if reason],
        "stop_reason": state.get("stop_reason", "") or ("partial_answer" if blocked_reasons else ""),
        "step_progress": step_progress + ["Eligibility guidance prepared"],
        "next_node": "evaluator",
    }


async def _llm_eligibility_payload(
    query: str,
    summary: dict[str, Any],
    evidence_groups: dict[str, Any],
    handoff_context: list[dict[str, str]],
) -> DecisionPayload:
    if not any(evidence_groups.values()):
        return {}

    llm = get_text_llm()
    response = await llm.ainvoke([
        SystemMessage(content=ELIGIBILITY_REASONER_PROMPT),
        HumanMessage(content=(
            f"User query:\n{query}\n\n"
            f"Session summary:\n{json.dumps(summary, ensure_ascii=True)}\n\n"
            f"Handoff notes:\n{json.dumps(handoff_context, ensure_ascii=True)}\n\n"
            f"Evidence groups:\n{json.dumps(evidence_groups, ensure_ascii=True)}"
        )),
    ])

    content = response.content if isinstance(response.content, str) else str(response.content)
    try:
        json_start = content.find("{")
        json_end = content.rfind("}") + 1
        parsed = json.loads(content[json_start:json_end])
        return parsed if isinstance(parsed, dict) else {}
    except Exception as exc:
        log.warning("Eligibility reasoner parse failed: %s", exc)
        return {}


def _heuristic_eligibility_payload(
    summary: dict[str, Any],
    evidence_groups: dict[str, Any],
) -> DecisionPayload:
    assumptions = list(summary.get("assumptions", []))
    recommended = []
    uncertain = []
    source_refs = []
    completed = set(summary.get("completed_courses", {}).get("value", []))

    for record in evidence_groups.get("constraints", []):
        source_refs.append(build_support_ref(record))
        uncertain.append({
            "label": record.get("source_title", "") or "Eligibility constraint",
            "reason": record.get("excerpt", "") or "This constraint may affect eligibility and should be checked against your current record.",
            "kind": "needs_verification",
        })

    for record in evidence_groups.get("requirements", []):
        source_refs.append(build_support_ref(record))
        recommended.append({
            "label": record.get("source_title", "") or "Verified requirement",
            "reason": "This requirement is directly relevant to the eligibility decision.",
            "status": "verified",
            "support_codes": [],
            "assumption": "",
        })

    for record in evidence_groups.get("courses", []):
        code = record.get("value", {}).get("code", "")
        if code and code not in completed:
            source_refs.append(build_support_ref(record))
            recommended.append({
                "label": code,
                "reason": "This course appears relevant to the eligibility question, but prerequisite and classification checks may still apply.",
                "status": "conditional",
                "support_codes": [code],
                "assumption": "Assuming you meet any prerequisite or classification requirements not fully visible in the retrieved evidence.",
            })

    if not recommended:
        recommended.append({
            "label": "Conditional eligibility guidance",
            "reason": "The retrieved sources are enough to explain what matters, but not enough for a fully definitive eligibility ruling.",
            "status": "likely",
            "support_codes": [],
            "assumption": "",
        })

    if not evidence_groups.get("constraints"):
        assumptions.append("No explicit blocking prerequisite or policy was extracted, so eligibility may still depend on details not visible in the retrieved sources.")

    return {
        "decision_type": "eligibility_check",
        "answer_outline": [
            "Here is the safest eligibility read based on what is verified, what is conditional, and what still needs confirmation.",
        ],
        "recommended_items": _dedupe_sequence(recommended)[:5],
        "blocked_or_uncertain_items": _dedupe_sequence(uncertain)[:4],
        "assumptions": assumptions,
        "next_best_action": "Verify the specific prerequisite, classification, or policy detail before treating this as a final eligibility decision.",
        "source_refs": _dedupe_source_refs(source_refs)[:8],
    }


def _merge_payloads(base: DecisionPayload, llm_payload: DecisionPayload) -> DecisionPayload:
    if not llm_payload:
        return base

    merged = dict(base)
    for key in ("decision_type", "next_best_action"):
        if llm_payload.get(key):
            merged[key] = llm_payload[key]
    for key in ("answer_outline", "recommended_items", "blocked_or_uncertain_items", "assumptions", "source_refs"):
        merged[key] = _dedupe_sequence(list(base.get(key, [])) + list(llm_payload.get(key, [])))
    return merged


def _dedupe_source_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped = []
    seen = set()
    for ref in refs:
        key = (ref.get("url", ""), ref.get("title", ""), ref.get("entity_type", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return deduped


def _dedupe_sequence(values: list[Any]) -> list[Any]:
    deduped = []
    seen = set()
    for value in values:
        key = json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else str(value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped
