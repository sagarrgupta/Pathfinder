"""Node: Career Matcher.

Builds a structured career decision payload from session summary,
profile data, and extracted evidence.
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
from app.core.prompts import CAREER_MATCHER_PROMPT
from app.core.quality import (
    DecisionPayload,
    build_support_ref,
)
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.career_matcher")


async def career_matcher(state: PathfinderState) -> PathfinderState:
    """Generate structured career guidance."""
    runtime = prepare_structured_advisor(
        state,
        node_name="career_matcher",
        progress_message="Matching your profile to career options...",
    )
    query = runtime["query"]
    summary = runtime["summary"]
    profile = runtime["profile"]
    evidence_groups = runtime["evidence_groups"]
    student_strategy = state.get("student_strategy", {})
    student_operating_model = state.get("student_operating_model", {})
    recommendation_outcome_profile = state.get("recommendation_outcome_profile", {})

    baseline = _heuristic_career_payload(
        summary,
        profile,
        evidence_groups,
        student_strategy,
        student_operating_model,
        recommendation_outcome_profile,
    )
    llm_payload, tool_call_log = await _llm_career_payload(
        query,
        summary,
        profile,
        evidence_groups,
        runtime["handoff_context"],
        state,
    )
    merged = _merge_payloads(baseline, llm_payload)
    merged["student_strategy"] = dict(student_strategy or {})
    merged["recommendation_paths"] = _build_career_paths(
        merged.get("recommended_items", []),
        merged.get("blocked_or_uncertain_items", []),
        student_strategy,
        student_operating_model,
        recommendation_outcome_profile,
    )
    log.info(
        "Career matcher produced %d recommendation(s)",
        len(merged.get("recommended_items", [])),
    )
    return finalize_structured_advisor(
        state,
        node_name="career_matcher",
        completion_message="Career matching prepared",
        ranking_note="Career matcher compared typed role evidence against profile skills and goals.",
        merged_payload=merged,
        tool_call_log=tool_call_log,
        runtime=runtime,
    )


async def _llm_career_payload(
    query: str,
    summary: dict[str, Any],
    profile: dict[str, Any],
    evidence_groups: dict[str, Any],
    handoff_context: list[dict[str, str]],
    state: PathfinderState,
) -> tuple[DecisionPayload, list[dict[str, Any]]]:
    parsed, tool_call_log = await run_structured_advisor_loop(
        query=query,
        summary=summary,
        profile=profile,
        evidence_groups=evidence_groups,
        handoff_context=handoff_context,
        state=state,
        system_prompt=CAREER_MATCHER_PROMPT,
    )
    if not parsed:
        log.warning("Career matcher parse failed or returned empty payload")
    return parsed, tool_call_log


def _heuristic_career_payload(
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
    goal_values = _career_goals(summary, profile)
    goals = [goal.lower() for goal in goal_values]
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

    if not recommended and goal_values:
        goal_label = goal_values[0]
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
            _career_outline_for_strategy(student_strategy),
            _career_outline_for_operating_model(student_operating_model),
        ],
        "recommended_items": _dedupe_sequence(recommended)[:6],
        "blocked_or_uncertain_items": _dedupe_sequence(uncertain)[:5],
        "assumptions": assumptions,
        "next_best_action": _career_next_step_for_strategy(
            student_strategy,
            student_operating_model,
            recommendation_outcome_profile,
        ),
        "source_refs": _dedupe_source_refs(source_refs)[:8],
        "student_strategy": dict(student_strategy),
    }


def _career_goals(summary: dict[str, Any], profile: dict[str, Any]) -> list[str]:
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


def _career_outline_for_strategy(student_strategy: dict[str, Any]) -> str:
    primary = str((student_strategy or {}).get("primary_priority", "balanced_progress"))
    if primary == "internship_readiness":
        return "Here are the strongest career directions and next actions based on your profile, with extra weight on internship readiness and practical hiring signals."
    if primary == "grad_school_preparation":
        return "Here are the strongest career directions and next actions based on your profile, while keeping graduate-school preparation in view."
    if primary == "gpa_protection":
        return "Here are the strongest career directions and next actions based on your profile, while keeping GPA risk and academic load in mind."
    return "Here are the strongest career directions and next actions based on your profile and the verified evidence."


def _career_outline_for_operating_model(student_operating_model: dict[str, Any]) -> str:
    risk = str((student_operating_model or {}).get("risk_tolerance", ""))
    planning_style = str((student_operating_model or {}).get("planning_style", ""))
    certainty = str((student_operating_model or {}).get("certainty_preference", ""))
    grad_school = str((student_operating_model or {}).get("grad_school_seriousness", ""))
    if grad_school == "high":
        return "The guidance keeps academically stronger or research-adjacent paths more visible because your recent signals suggest graduate-school preparation matters."
    if certainty == "high":
        return "The guidance leans toward clearer, better-supported career paths because your recent signals suggest you prefer higher-certainty decisions."
    if risk == "conservative":
        return "The guidance leans slightly toward more reachable role paths because your recent signals suggest you prefer lower-risk tradeoffs."
    if planning_style == "exploratory":
        return "The guidance keeps a broader role set visible because your recent signals suggest you may still be exploring fit."
    return ""


def _career_next_step_for_strategy(
    student_strategy: dict[str, Any],
    student_operating_model: dict[str, Any] | None = None,
    recommendation_outcome_profile: dict[str, Any] | None = None,
) -> str:
    primary = str((student_strategy or {}).get("primary_priority", "balanced_progress"))
    student_operating_model = student_operating_model or {}
    recommendation_outcome_profile = recommendation_outcome_profile or {}
    load = str(student_operating_model.get("workload_preference", ""))
    certainty = str(student_operating_model.get("certainty_preference", ""))
    follow_through_style = str(recommendation_outcome_profile.get("follow_through_style", ""))
    if follow_through_style == "prefers_small_commits":
        return "Choose one compact career step first, like tightening one project or one missing skill, before opening a wider application plan."
    if primary == "internship_readiness":
        if load == "lighter":
            return "Strengthen the highest-impact missing skill or project area in a way that still leaves room for classes and steady application momentum."
        return "Strengthen the highest-impact missing skill or project area, then target roles where your current profile already looks interviewable."
    if primary == "grad_school_preparation":
        return "Choose the next step that improves both career readiness and longer-term academic depth, such as a stronger project, research-aligned work, or advanced technical skill."
    if primary == "gpa_protection":
        return "Prioritize the highest-impact missing skill or project area without taking on so much at once that it hurts academic performance."
    if certainty == "high":
        return "Strengthen the clearest high-signal skill or project gap first, then target the most evidence-backed roles before stretching wider."
    if follow_through_style == "high_follow_through":
        return "Strengthen the top skill or project gap, then immediately target the most aligned roles so momentum does not get lost."
    return "Strengthen the highest-impact missing skill or project area before targeting the most ambitious roles."


def _build_career_paths(
    recommended_items: list[dict[str, Any]],
    blocked_items: list[dict[str, Any]],
    student_strategy: dict[str, Any],
    student_operating_model: dict[str, Any] | None = None,
    recommendation_outcome_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    primary = str((student_strategy or {}).get("primary_priority", "balanced_progress"))
    risk = str((student_operating_model or {}).get("risk_tolerance", ""))
    certainty = str((student_operating_model or {}).get("certainty_preference", ""))
    grad_school = str((student_operating_model or {}).get("grad_school_seriousness", ""))
    follow_through_style = str((recommendation_outcome_profile or {}).get("follow_through_style", ""))
    labels = [str(item.get("label", "")).strip() for item in recommended_items if isinstance(item, dict) and str(item.get("label", "")).strip()]
    blockers = [str(item.get("label", "")).strip() for item in blocked_items if isinstance(item, dict) and str(item.get("label", "")).strip()]
    if not labels:
        return []
    conservative_reason = "Target the most reachable roles first while closing the biggest skill gaps gradually."
    balanced_reason = "Mix realistic targets with one stronger stretch direction so momentum stays high."
    aggressive_reason = "Aim earlier at the most ambitious direction, accepting that more preparation may still be needed."
    if primary == "internship_readiness":
        conservative_reason = "Start with the roles where your current profile is closest to interview-ready."
        aggressive_reason = "Start reaching toward stronger internships sooner, while accepting more missing-skill work up front."
    elif primary == "grad_school_preparation":
        aggressive_reason = "Favor the path that builds stronger depth and credibility even if it is slower to monetize immediately."
    if risk == "conservative":
        conservative_reason = "Start with the most reachable roles first because your current signals suggest safer tradeoffs are a better fit."
    if certainty == "high":
        conservative_reason = "Start with the clearest, most evidence-backed roles first because your current signals suggest higher-certainty choices are a better fit."
    if grad_school == "high":
        aggressive_reason = "Keep academically stronger or research-adjacent paths visible because your current signals suggest graduate-school preparation matters."
    if follow_through_style == "prefers_small_commits":
        conservative_reason = "Start with the smallest high-payoff role direction first because your recent follow-through signals suggest narrower commitments stick better."
    paths = [
        {"label": "Conservative", "reason": conservative_reason, "courses": labels[:2]},
        {"label": "Balanced", "reason": balanced_reason, "courses": labels[:3]},
        {"label": "Aggressive", "reason": aggressive_reason, "courses": labels[:4]},
    ]
    if blockers:
        for path in paths:
            path["watchouts"] = blockers[:2]
    return paths
