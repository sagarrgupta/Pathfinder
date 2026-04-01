"""Node: Career Matcher.

Builds a structured career decision payload from session summary,
profile data, and extracted evidence.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.adapters.llm.lmstudio import get_text_llm
from app.core.prompts import CAREER_MATCHER_PROMPT
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

log = logging.getLogger("pathfinder.agents.career_matcher")


async def career_matcher(state: PathfinderState) -> PathfinderState:
    """Generate structured career guidance."""
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
    handoff_context = recent_handoff_context(working_memory, to_node="career_matcher")

    step_progress = list(state.get("step_progress", []))
    step_progress.append("Matching your profile to career options...")

    baseline = _heuristic_career_payload(summary, profile, evidence_groups)
    llm_payload = await _llm_career_payload(query, summary, profile, evidence_groups, handoff_context)
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
        "Career matcher compared typed role evidence against profile skills and goals.",
    )
    task_graph = complete_task(task_graph, "compare_to_student_state")
    if blocked_reasons:
        task_graph = complete_task(task_graph, "check_blockers")
    task_graph = complete_task(task_graph, "rank_options")
    working_memory = add_handoff_note(
        working_memory,
        from_node="career_matcher",
        to_node="evaluator",
        contract="decision_payload",
        summary=(
            f"recommended={len(merged.get('recommended_items', []))}; "
            f"blocked={len(merged.get('blocked_or_uncertain_items', []))}"
        ),
    )

    step_progress.append("Career matching prepared")
    log.info(
        "Career matcher produced %d recommendation(s)",
        len(merged.get("recommended_items", [])),
    )

    return {
        **state,
        "decision_payload": merged,
        "draft_answer": "",
        "working_memory": working_memory,
        "task_graph": task_graph,
        "blocked_reasons": [reason for reason in blocked_reasons if reason],
        "stop_reason": state.get("stop_reason", "") or ("partial_answer" if blocked_reasons else ""),
        "step_progress": step_progress,
        "next_node": "evaluator",
    }


async def _llm_career_payload(
    query: str,
    summary: dict[str, Any],
    profile: dict[str, Any],
    evidence_groups: dict[str, Any],
    handoff_context: list[dict[str, str]],
) -> DecisionPayload:
    llm = get_text_llm()
    response = await llm.ainvoke([
        SystemMessage(content=CAREER_MATCHER_PROMPT),
        HumanMessage(content=(
            f"User query:\n{query}\n\n"
            f"Session summary:\n{json.dumps(summary, ensure_ascii=True)}\n\n"
            f"Profile snapshot:\n{json.dumps(profile, ensure_ascii=True)}\n\n"
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
        log.warning("Career matcher parse failed: %s", exc)
        return {}


def _heuristic_career_payload(
    summary: dict[str, Any],
    profile: dict[str, Any],
    evidence_groups: dict[str, Any],
) -> DecisionPayload:
    goals = [goal.lower() for goal in summary.get("goals", {}).get("value", [])]
    skills = {skill.get("name", "").lower() for skill in profile.get("skills", []) if skill.get("name")}
    courses = {course.get("code", "").upper() for course in profile.get("courses", []) if course.get("code")}

    recommended = []
    uncertain = []
    source_refs = []
    assumptions = list(summary.get("assumptions", []))

    for record in evidence_groups.get("job_roles", []):
        if record.get("source_url"):
            source_refs.append(build_support_ref(record))
        title = record.get("value", {}).get("name") or record.get("source_title", "")
        recommended.append({
            "label": title or "Relevant role",
            "reason": "This role appears in the verified evidence and aligns with the student's profile or stated goals.",
            "status": "goal_aligned" if any("ai" in goal or "machine learning" in goal for goal in goals) else "good_fit",
            "support_codes": [],
            "assumption": "",
        })

    for record in evidence_groups.get("missing_skills", []):
        skill_name = record.get("value", {}).get("name", "").lower()
        if skill_name and skill_name not in skills:
            source_refs.append(build_support_ref(record))
            uncertain.append({
                "label": skill_name.title(),
                "reason": "This skill appears in the evidence but is not clearly present in the student's profile yet.",
                "kind": "blocked",
            })

    for record in evidence_groups.get("courses", []):
        code = record.get("value", {}).get("code", "").upper()
        if code and code not in courses and any("ai" in goal or "machine learning" in goal for goal in goals):
            source_refs.append(build_support_ref(record))
            recommended.append({
                "label": code,
                "reason": "This course appears relevant for strengthening the student's target role readiness.",
                "status": "goal_aligned",
                "support_codes": [code],
                "assumption": "Assuming the student can fit this course into their plan.",
            })

    for record in evidence_groups.get("constraints", []):
        source_refs.append(build_support_ref(record))
        uncertain.append({
            "label": record.get("source_title", "") or "Career constraint",
            "reason": record.get("excerpt", "") or "This constraint may affect readiness or eligibility for some roles.",
            "kind": "needs_verification",
        })

    if not recommended and goals:
        goal_label = summary.get("goals", {}).get("value", [])[0]
        recommended.append({
            "label": goal_label,
            "reason": "Use the student's stated goal as the primary lens for role targeting and skill-gap planning.",
            "status": "goal_aligned",
            "support_codes": [],
            "assumption": "",
        })

    if not skills:
        assumptions.append("The student profile contains limited explicit skills, so role fit may be understated.")
    if evidence_groups.get("job_requirements") and not evidence_groups.get("job_roles"):
        assumptions.append("Only job requirement evidence was found, so role titles may still need confirmation.")

    return {
        "decision_type": "career_matching",
        "answer_outline": [
            "Here are the strongest career directions and next actions based on your profile and the verified evidence.",
        ],
        "recommended_items": _dedupe_sequence(recommended)[:6],
        "blocked_or_uncertain_items": _dedupe_sequence(uncertain)[:5],
        "assumptions": assumptions,
        "next_best_action": "Strengthen the highest-impact missing skill or project area before targeting the most ambitious roles.",
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
