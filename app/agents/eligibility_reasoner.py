"""Node: Eligibility Reasoner.

Handles "can I take/apply/do this?" questions using structured evidence,
student state, and explicit assumptions/blockers.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.advisor_runtime import (
    finalize_structured_advisor,
    prepare_structured_advisor,
    run_structured_advisor_loop,
)
from app.core.prompts import ELIGIBILITY_REASONER_PROMPT
from app.core.quality import (
    DecisionPayload,
    build_support_ref,
)
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.eligibility_reasoner")


async def eligibility_reasoner(state: PathfinderState) -> PathfinderState:
    """Generate structured eligibility guidance."""
    runtime = prepare_structured_advisor(
        state,
        node_name="eligibility_reasoner",
        progress_message="Checking eligibility and blockers...",
    )
    query = runtime["query"]
    summary = runtime["summary"]
    profile = runtime["profile"]
    evidence_groups = runtime["evidence_groups"]
    student_strategy = state.get("student_strategy", {})
    student_operating_model = state.get("student_operating_model", {})
    recommendation_outcome_profile = state.get("recommendation_outcome_profile", {})

    baseline = _heuristic_eligibility_payload(
        summary,
        profile,
        evidence_groups,
        student_strategy,
        student_operating_model,
        recommendation_outcome_profile,
    )
    llm_payload, tool_call_log = await _llm_eligibility_payload(
        query,
        summary,
        evidence_groups,
        runtime["handoff_context"],
        state,
    )
    merged = _merge_payloads(baseline, llm_payload)
    merged["student_strategy"] = dict(student_strategy or {})
    merged["recommendation_paths"] = _build_eligibility_paths(
        merged.get("recommended_items", []),
        merged.get("blocked_or_uncertain_items", []),
        student_strategy,
        student_operating_model,
        recommendation_outcome_profile,
    )
    return finalize_structured_advisor(
        state,
        node_name="eligibility_reasoner",
        completion_message="Eligibility guidance prepared",
        ranking_note="Eligibility reasoner separated verified rules, conditional assumptions, and missing evidence.",
        merged_payload=merged,
        tool_call_log=tool_call_log,
        runtime=runtime,
    )


async def _llm_eligibility_payload(
    query: str,
    summary: dict[str, Any],
    evidence_groups: dict[str, Any],
    handoff_context: list[dict[str, str]],
    state: PathfinderState,
) -> tuple[DecisionPayload, list[dict[str, Any]]]:
    parsed, tool_call_log = await run_structured_advisor_loop(
        query=query,
        summary=summary,
        evidence_groups=evidence_groups,
        handoff_context=handoff_context,
        state=state,
        system_prompt=ELIGIBILITY_REASONER_PROMPT,
    )
    if not parsed:
        log.warning("Eligibility reasoner parse failed or returned empty payload")
    return parsed, tool_call_log


def _heuristic_eligibility_payload(
    summary: dict[str, Any],
    profile: dict[str, Any],
    evidence_groups: dict[str, Any],
    student_strategy: dict[str, Any] | None = None,
    student_operating_model: dict[str, Any] | None = None,
    recommendation_outcome_profile: dict[str, Any] | None = None,
) -> DecisionPayload:
    student_strategy = student_strategy or {}
    student_operating_model = student_operating_model or {}
    recommendation_outcome_profile = recommendation_outcome_profile or {}
    assumptions = list(summary.get("assumptions", []))
    recommended = []
    uncertain = []
    source_refs = []
    completed = set(summary.get("completed_courses", {}).get("value", []))
    goals = _eligibility_goals(summary, profile)
    temporary_constraints = _eligibility_temporary_constraints(profile)

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

    if temporary_constraints and not evidence_groups.get("constraints"):
        assumptions.append(
            f"Current short-term student constraints may matter here too: {', '.join(temporary_constraints[:2])}."
        )

    if not recommended and goals:
        recommended.append({
            "label": goals[0],
            "reason": "Use the student's active goal as the main lens for deciding whether this eligibility path is worth pursuing now.",
            "status": "goal_aligned",
            "support_codes": [],
            "assumption": "",
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
            _eligibility_outline_for_strategy(student_strategy),
            _eligibility_outline_for_operating_model(student_operating_model),
        ],
        "recommended_items": _dedupe_sequence(recommended)[:5],
        "blocked_or_uncertain_items": _dedupe_sequence(uncertain)[:4],
        "assumptions": assumptions,
        "next_best_action": _eligibility_next_step_for_strategy(
            student_strategy,
            student_operating_model,
            recommendation_outcome_profile,
        ),
        "source_refs": _dedupe_source_refs(source_refs)[:8],
        "student_strategy": dict(student_strategy),
    }


def _eligibility_goals(summary: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    goals = [str(goal).strip() for goal in (summary.get("goals", {}) or {}).get("value", []) if str(goal).strip()]
    if goals:
        return _dedupe_sequence(goals)

    goals = [str(item.get("name", "")).strip() for item in (profile.get("goals", []) or []) if str(item.get("name", "")).strip()]
    if goals:
        return _dedupe_sequence(goals)

    temporal_profile = (profile or {}).get("temporal_profile", {}) or {}
    goals = [
        str(item.get("value", "")).strip()
        for item in (temporal_profile.get("evolving_facts", []) or [])
        if str(item.get("fact_type", "")).lower() == "goal" and str(item.get("value", "")).strip()
    ]
    if goals:
        return _dedupe_sequence(goals)

    goals = [
        str(item.get("value", "")).strip()
        for item in (temporal_profile.get("active_candidates", []) or [])
        if str(item.get("fact_type", "")).lower() == "goal" and str(item.get("value", "")).strip()
    ]
    return _dedupe_sequence(goals)


def _eligibility_temporary_constraints(profile: dict[str, Any]) -> list[str]:
    temporal_profile = (profile or {}).get("temporal_profile", {}) or {}
    constraints = [
        str(item.get("value", "")).strip()
        for item in (temporal_profile.get("temporary_facts", []) or [])
        if str(item.get("fact_type", "")).lower() in {"constraint", "preference"} and str(item.get("value", "")).strip()
    ]
    return _dedupe_sequence(constraints)


def _merge_payloads(base: DecisionPayload, llm_payload: DecisionPayload) -> DecisionPayload:
    if not llm_payload:
        return base

    merged = dict(base)
    for key in ("decision_type", "next_best_action", "student_strategy"):
        if llm_payload.get(key):
            merged[key] = llm_payload[key]
    for key in ("answer_outline", "recommended_items", "blocked_or_uncertain_items", "assumptions", "source_refs", "recommendation_paths"):
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


def _eligibility_outline_for_strategy(student_strategy: dict[str, Any]) -> str:
    primary = str((student_strategy or {}).get("primary_priority", "balanced_progress"))
    if primary == "graduation_speed":
        return "Here is the most practical eligibility read based on what is verified, with extra weight on keeping you moving forward quickly."
    if primary == "gpa_protection":
        return "Here is the safest eligibility read based on what is verified, with extra weight on avoiding avoidable academic risk."
    if primary == "internship_readiness":
        return "Here is the most practical eligibility read based on what is verified, with extra weight on not delaying career-relevant progress unnecessarily."
    return "Here is the safest eligibility read based on what is verified, what is conditional, and what still needs confirmation."


def _eligibility_outline_for_operating_model(student_operating_model: dict[str, Any]) -> str:
    risk = str((student_operating_model or {}).get("risk_tolerance", ""))
    certainty = str((student_operating_model or {}).get("certainty_preference", ""))
    if certainty == "high":
        return "The guidance leans toward the clearest evidence-backed interpretation because your recent signals suggest you prefer higher-certainty decisions."
    if risk == "conservative":
        return "The guidance leans more conservative because your recent signals suggest you prefer lower-risk interpretations when evidence is incomplete."
    return ""


def _eligibility_next_step_for_strategy(
    student_strategy: dict[str, Any],
    student_operating_model: dict[str, Any] | None = None,
    recommendation_outcome_profile: dict[str, Any] | None = None,
) -> str:
    primary = str((student_strategy or {}).get("primary_priority", "balanced_progress"))
    student_operating_model = student_operating_model or {}
    recommendation_outcome_profile = recommendation_outcome_profile or {}
    risk = str(student_operating_model.get("risk_tolerance", ""))
    certainty = str(student_operating_model.get("certainty_preference", ""))
    follow_through_style = str(recommendation_outcome_profile.get("follow_through_style", ""))
    if follow_through_style == "prefers_small_commits":
        return "Verify the single blocker that matters most first, then decide on the next step only after that one uncertainty is cleared."
    if primary == "graduation_speed":
        if risk == "conservative":
            return "Verify the specific prerequisite or policy detail quickly, then take the fastest option that still keeps downside risk controlled."
        return "Verify the specific prerequisite or policy detail quickly, then act on the fastest safe path instead of waiting on unnecessary uncertainty."
    if primary == "internship_readiness":
        return "Verify the prerequisite or classification detail, then prioritize the path that keeps career-relevant momentum moving."
    if primary == "gpa_protection":
        return "Verify the specific prerequisite, classification, or policy detail before treating this as a final eligibility decision."
    if certainty == "high":
        return "Verify the single most important prerequisite or policy detail first, then proceed only on the clearest evidence-backed path."
    if follow_through_style == "high_follow_through":
        return "Verify the key prerequisite or policy detail, then move immediately on the best-supported eligible path so momentum stays high."
    return "Verify the specific prerequisite, classification, or policy detail before treating this as a final eligibility decision."


def _build_eligibility_paths(
    recommended_items: list[dict[str, Any]],
    blocked_items: list[dict[str, Any]],
    student_strategy: dict[str, Any],
    student_operating_model: dict[str, Any] | None = None,
    recommendation_outcome_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    primary = str((student_strategy or {}).get("primary_priority", "balanced_progress"))
    risk = str((student_operating_model or {}).get("risk_tolerance", ""))
    certainty = str((student_operating_model or {}).get("certainty_preference", ""))
    follow_through_style = str((recommendation_outcome_profile or {}).get("follow_through_style", ""))
    labels = [str(item.get("label", "")).strip() for item in recommended_items if isinstance(item, dict) and str(item.get("label", "")).strip()]
    blockers = [str(item.get("label", "")).strip() for item in blocked_items if isinstance(item, dict) and str(item.get("label", "")).strip()]
    if not labels:
        return []
    conservative_reason = "Use the safest interpretation first and do not proceed until the key prerequisite or policy detail is explicitly verified."
    balanced_reason = "Move forward on the likely path, but only after the most important uncertainty is checked."
    aggressive_reason = "Assume the likely eligibility path holds and prepare to move fast, while accepting more verification risk."
    if primary == "graduation_speed":
        balanced_reason = "Keep the fastest likely path in play while verifying only the blockers that really matter."
        aggressive_reason = "Prepare for the fastest path immediately so you can act as soon as the key condition checks out."
    elif primary == "gpa_protection":
        aggressive_reason = "Proceed faster only if the remaining uncertainty is low enough that it will not create avoidable academic risk."
    elif primary == "internship_readiness":
        balanced_reason = "Keep the most career-relevant path open while verifying the main blocker."
    if risk == "conservative":
        conservative_reason = "Use the most evidence-backed interpretation first because your current signals suggest safer tradeoffs are a better fit."
    if certainty == "high":
        conservative_reason = "Use the clearest evidence-backed interpretation first because your current signals suggest higher-certainty decisions are a better fit."
    if follow_through_style == "prefers_small_commits":
        conservative_reason = "Start with the smallest verified interpretation first because your recent follow-through signals suggest narrower commitments are more durable."
    paths = [
        {"label": "Conservative", "reason": conservative_reason, "courses": labels[:2]},
        {"label": "Balanced", "reason": balanced_reason, "courses": labels[:3]},
        {"label": "Aggressive", "reason": aggressive_reason, "courses": labels[:4]},
    ]
    if blockers:
        for path in paths:
            path["watchouts"] = blockers[:2]
    return paths
