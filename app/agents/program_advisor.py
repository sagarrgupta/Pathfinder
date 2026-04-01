"""Node: Program Advisor.

Builds a structured academic-program decision payload from session
summary plus extracted evidence records.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.adapters.llm.lmstudio import get_text_llm
from app.agents.tool_calling import run_advisor_tool_loop
from app.core.prompts import PROGRAM_ADVISOR_PROMPT
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
from app.utils.json_extract import parse_json_object

log = logging.getLogger("pathfinder.agents.program_advisor")


async def program_advisor(state: PathfinderState) -> PathfinderState:
    """Generate structured program guidance."""
    query = state.get("query", "")
    summary = state.get("session_summary", {})
    evidence_records = state.get("evidence_records", [])
    evidence_groups = group_evidence_records(evidence_records, state.get("profile_data", {}))
    working_memory = init_working_memory(state.get("working_memory", {}))
    task_graph = state.get("task_graph", [])
    blocked_reasons = list(state.get("blocked_reasons", []))
    task_graph = start_task(task_graph, "compare_to_student_state")
    task_graph = start_task(task_graph, "check_blockers")
    task_graph = start_task(task_graph, "rank_options")
    handoff_context = recent_handoff_context(working_memory, to_node="program_advisor")

    step_progress = list(state.get("step_progress", []))
    step_progress.append("Building program guidance...")

    baseline = _heuristic_program_payload(query, summary, evidence_groups)
    llm_payload, tool_call_log = await _llm_program_payload(query, summary, evidence_groups, handoff_context, state)
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
        "Program advisor synthesized requirements, constraints, and deadlines from typed evidence groups.",
    )
    task_graph = complete_task(task_graph, "compare_to_student_state")
    if blocked_reasons:
        task_graph = complete_task(task_graph, "check_blockers")
    task_graph = complete_task(task_graph, "rank_options")
    working_memory = add_handoff_note(
        working_memory,
        from_node="program_advisor",
        to_node="evaluator",
        contract="decision_payload",
        summary=(
            f"recommended={len(merged.get('recommended_items', []))}; "
            f"blocked={len(merged.get('blocked_or_uncertain_items', []))}"
        ),
    )

    step_progress.append("Program guidance prepared")
    log.info(
        "Program advisor produced %d recommendation(s)",
        len(merged.get("recommended_items", [])),
    )

    return {
        **state,
        "decision_payload": merged,
        "draft_answer": "",
        "tool_call_log": tool_call_log,
        "working_memory": working_memory,
        "task_graph": task_graph,
        "blocked_reasons": [reason for reason in blocked_reasons if reason],
        "stop_reason": state.get("stop_reason", "") or ("partial_answer" if blocked_reasons else ""),
        "step_progress": step_progress,
        "next_node": "evaluator",
    }


async def _llm_program_payload(
    query: str,
    summary: dict[str, Any],
    evidence_groups: dict[str, Any],
    handoff_context: list[dict[str, str]],
    state: PathfinderState,
) -> tuple[DecisionPayload, list[dict[str, Any]]]:
    if not any(evidence_groups.values()):
        return {}, list(state.get("tool_call_log", []))

    llm = get_text_llm()
    json_contract = (
        "Return ONLY valid JSON matching this schema keys: decision_type, answer_outline, "
        "recommended_items, blocked_or_uncertain_items, assumptions, next_best_action, source_refs."
    )
    system_prompt = f"{PROGRAM_ADVISOR_PROMPT}\n\n{json_contract}"
    user_prompt = (
        f"User query:\n{query}\n\n"
        f"Session summary:\n{json.dumps(summary, ensure_ascii=True)}\n\n"
        f"Handoff notes:\n{json.dumps(handoff_context, ensure_ascii=True)}\n\n"
        f"Evidence groups:\n{json.dumps(evidence_groups, ensure_ascii=True)}"
    )
    content, tool_call_log = await run_advisor_tool_loop(
        llm=llm,
        system_prompt=system_prompt,
        user_query=user_prompt,
        state=state,
        max_rounds=4,
    )
    try:
        parsed = parse_json_object(content) or {}
        return (parsed if isinstance(parsed, dict) else {}), tool_call_log
    except Exception as exc:
        log.warning("Program advisor parse failed: %s", exc)
        return {}, tool_call_log


def _heuristic_program_payload(
    query: str,
    summary: dict[str, Any],
    evidence_groups: dict[str, Any],
) -> DecisionPayload:
    recommended = []
    uncertain = []
    source_refs = []
    assumptions = list(summary.get("assumptions", []))

    institution = summary.get("institution", {}).get("value", "")
    program = summary.get("program", {}).get("value", "")
    query_lower = (query or "").lower()
    asks_university_selection = (
        "which universities" in query_lower
        or "rank universities" in query_lower
        or "safe" in query_lower and "ambitious" in query_lower
        or "realistic" in query_lower and "universit" in query_lower
        or "top" in query_lower and "universit" in query_lower
    )
    asks_admission_chances = any(token in query_lower for token in ("chances", "chance", "odds", "probability"))

    for record in evidence_groups.get("requirements", []):
        title = record.get("source_title", "")
        source_refs.append(build_support_ref(record))
        recommended.append({
            "label": title or "Verified program requirement",
            "reason": "This source appears to define an official requirement or core structure relevant to the user's academic decision.",
            "status": "verified",
            "support_codes": [],
            "assumption": "",
        })

    for record in evidence_groups.get("constraints", []):
        excerpt = record.get("excerpt", "")
        source_refs.append(build_support_ref(record))
        uncertain.append({
            "label": record.get("source_title", "") or "Program constraint",
            "reason": excerpt or "This source suggests a policy, prerequisite, or program constraint that may affect the student's plan.",
            "kind": "uncertain" if "may" in excerpt.lower() else "needs_verification",
        })

    for record in evidence_groups.get("certificates", []):
        source_refs.append(build_support_ref(record))
        recommended.append({
            "label": record.get("source_title", "") or "Related certificate option",
            "reason": "This appears to be a secondary specialization path that may complement the main program.",
            "status": "comparison_note",
            "support_codes": [],
            "assumption": "",
        })

    for record in evidence_groups.get("deadlines", []):
        source_refs.append(build_support_ref(record))
        uncertain.append({
            "label": record.get("source_title", "") or "Time-sensitive item",
            "reason": record.get("excerpt", "") or "This item appears time-sensitive and should be verified before acting on it.",
            "kind": "needs_verification",
        })

    if evidence_groups.get("availability"):
        assumptions.append("Live schedule evidence exists, but program guidance should still be anchored primarily in official requirements and constraints.")

    if not recommended and asks_university_selection:
        recommended.extend([
            {
                "label": "Build a 3-tier target list (safe, moderate, ambitious)",
                "reason": "A realistic university strategy should include all three tiers to balance outcome risk.",
                "status": "recommended",
                "support_codes": [],
                "assumption": "",
            },
            {
                "label": "Score each target on fit dimensions (GPA, research, projects, budget, location, deadlines)",
                "reason": "A weighted fit score is more reliable than ranking by prestige alone.",
                "status": "recommended",
                "support_codes": [],
                "assumption": "",
            },
            {
                "label": "Prioritize programs with strong CS outcomes in your intended subfield",
                "reason": "Department-level fit and lab alignment matter more than overall brand rank for admission success.",
                "status": "recommended",
                "support_codes": [],
                "assumption": "",
            },
        ])
        uncertain.extend([
            {
                "label": "Missing profile evidence for precise shortlist",
                "reason": "Need GPA scale, transcript rigor, projects/research depth, test scores, and budget to produce program-by-program shortlisting.",
                "kind": "needs_verification",
            }
        ])
        assumptions.append("Providing structured strategy because source-backed program shortlist evidence is currently limited.")
    elif not recommended and asks_admission_chances:
        recommended.extend([
            {
                "label": "Estimate admission probability in bands (low / moderate / high) per target program",
                "reason": "Probability should be tied to profile-program fit, not a single global estimate.",
                "status": "recommended",
                "support_codes": [],
                "assumption": "",
            },
            {
                "label": "Use evidence-based factors: GPA trend, prerequisite match, research output, project quality, and statement fit",
                "reason": "These factors typically drive graduate CS admissions outcomes.",
                "status": "recommended",
                "support_codes": [],
                "assumption": "",
            },
        ])
        uncertain.append({
            "label": "Insufficient profile details for accurate probability estimate",
            "reason": "Need program list, GPA scale, transcript strength, and research/project evidence.",
            "kind": "needs_verification",
        })
    elif not recommended:
        recommended.append({
            "label": f"{program or 'Program'} guidance for {institution or 'the student'}".strip(),
            "reason": "Use the verified degree and department sources as the main basis for advising the next academic step.",
            "status": "recommended",
            "support_codes": [],
            "assumption": "",
        })

    return {
        "decision_type": "program_guidance",
        "answer_outline": [
            "Here is the most relevant guidance for your question.",
        ],
        "recommended_items": _dedupe_sequence(recommended)[:5],
        "blocked_or_uncertain_items": _dedupe_sequence(uncertain)[:4],
        "assumptions": assumptions,
        "next_best_action": (
            "If you share your GPA, preferred locations, budget range, and target subfield, I can produce a concrete safe/moderate/ambitious shortlist next."
            if (asks_university_selection or asks_admission_chances)
            else "Use the official program page as the primary source and verify any time-sensitive or policy-specific details before acting."
        ),
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
