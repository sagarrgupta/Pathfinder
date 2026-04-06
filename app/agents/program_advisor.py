"""Node: Program Advisor.

Builds a structured academic-program decision payload from session
summary plus extracted evidence records.
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
from app.core.prompts import PROGRAM_ADVISOR_PROMPT
from app.core.quality import (
    DecisionPayload,
    build_support_ref,
)
from app.core.state import PathfinderState
from app.services.transcript_state import primary_transcript_state

log = logging.getLogger("pathfinder.agents.program_advisor")


async def program_advisor(state: PathfinderState) -> PathfinderState:
    """Generate structured program guidance."""
    runtime = prepare_structured_advisor(
        state,
        node_name="program_advisor",
        progress_message="Building program guidance...",
    )
    query = runtime["query"]
    summary = runtime["summary"]
    profile = runtime["profile"]
    evidence_groups = runtime["evidence_groups"]
    student_strategy = state.get("student_strategy", {})
    student_operating_model = state.get("student_operating_model", {})
    recommendation_outcome_profile = state.get("recommendation_outcome_profile", {})
    transcript_state = primary_transcript_state(state.get("transcript_states", []), state.get("semantic_memory", {}))

    baseline = _heuristic_program_payload(
        query,
        summary,
        profile,
        evidence_groups,
        transcript_state,
        student_strategy,
        student_operating_model,
        recommendation_outcome_profile,
    )
    llm_payload, tool_call_log = await _llm_program_payload(
        query,
        summary,
        evidence_groups,
        runtime["handoff_context"],
        state,
    )
    merged = _merge_payloads(baseline, llm_payload)
    merged["student_strategy"] = dict(student_strategy) if isinstance(student_strategy, dict) else {}
    merged["recommendation_paths"] = _build_program_paths(
        merged.get("recommended_items", []),
        merged.get("blocked_or_uncertain_items", []),
        student_strategy,
        student_operating_model,
        recommendation_outcome_profile,
    )
    log.info(
        "Program advisor produced %d recommendation(s)",
        len(merged.get("recommended_items", [])),
    )
    return finalize_structured_advisor(
        state,
        node_name="program_advisor",
        completion_message="Program guidance prepared",
        ranking_note="Program advisor synthesized requirements, constraints, and deadlines from typed evidence groups.",
        merged_payload=merged,
        tool_call_log=tool_call_log,
        runtime=runtime,
    )


async def _llm_program_payload(
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
        system_prompt=PROGRAM_ADVISOR_PROMPT,
    )
    if not parsed:
        log.warning("Program advisor parse failed or returned empty payload")
    return parsed, tool_call_log


def _heuristic_program_payload(
    query: str,
    summary: dict[str, Any],
    profile: dict[str, Any],
    evidence_groups: dict[str, Any],
    transcript_state: dict[str, Any] | None = None,
    student_strategy: dict[str, Any] | None = None,
    student_operating_model: dict[str, Any] | None = None,
    recommendation_outcome_profile: dict[str, Any] | None = None,
) -> DecisionPayload:
    transcript_state = transcript_state or {}
    student_strategy = student_strategy or {}
    student_operating_model = student_operating_model or {}
    recommendation_outcome_profile = recommendation_outcome_profile or {}
    recommended = []
    uncertain = []
    source_refs = []
    assumptions = list(summary.get("assumptions", []))

    institution = summary.get("institution", {}).get("value", "")
    program = summary.get("program", {}).get("value", "")
    goals = _program_goals(summary, profile)
    query_lower = (query or "").lower()
    asks_university_selection = (
        "which universities" in query_lower
        or "rank universities" in query_lower
        or "safe" in query_lower and "ambitious" in query_lower
        or "realistic" in query_lower and "universit" in query_lower
        or "top" in query_lower and "universit" in query_lower
    )
    asks_admission_chances = any(token in query_lower for token in ("chances", "chance", "odds", "probability"))

    for milestone in (transcript_state.get("milestones", []) or [])[:3]:
        description = str(milestone.get("description", "") or "").strip()
        status = str(milestone.get("status", "") or "").strip()
        if description:
            assumptions.append(f"Transcript milestone: {description}{f' ({status})' if status else ''}.")

    if transcript_state.get("planned_courses"):
        next_term = str((transcript_state.get("summary", {}) or {}).get("upcoming_term", "") or "")
        next_codes = [
            str(course.get("code", "")).strip()
            for course in (transcript_state.get("planned_courses", []) or [])[:4]
            if str(course.get("code", "")).strip()
        ]
        if next_codes:
            recommended.append({
                "label": f"{next_term or 'Upcoming term'} plan anchor",
                "reason": f"The transcript-backed student state already shows {', '.join(next_codes)} in the upcoming term, so program guidance should anchor on that actual near-term plan.",
                "status": "verified",
                "support_codes": next_codes,
                "assumption": "",
            })

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

    if goals and not recommended:
        recommended.append({
            "label": goals[0],
            "reason": "Use the student's active academic goal as the main lens for interpreting program requirements and tradeoffs.",
            "status": "goal_aligned",
            "support_codes": [],
            "assumption": "",
        })

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
            _program_outline_for_strategy(student_strategy, asks_university_selection, asks_admission_chances),
            _program_outline_for_operating_model(student_operating_model),
        ],
        "recommended_items": _dedupe_sequence(recommended)[:5],
        "blocked_or_uncertain_items": _dedupe_sequence(uncertain)[:4],
        "assumptions": assumptions,
        "next_best_action": _program_next_step_for_strategy(
            student_strategy,
            student_operating_model,
            recommendation_outcome_profile,
            asks_university_selection,
            asks_admission_chances,
        ),
        "source_refs": _dedupe_source_refs(source_refs)[:8],
        "student_strategy": dict(student_strategy),
    }


def _program_goals(summary: dict[str, Any], profile: dict[str, Any]) -> list[str]:
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


def _program_outline_for_strategy(
    student_strategy: dict[str, Any],
    asks_university_selection: bool,
    asks_admission_chances: bool,
) -> str:
    primary = str((student_strategy or {}).get("primary_priority", "balanced_progress"))
    if asks_university_selection or asks_admission_chances:
        if primary == "grad_school_preparation":
            return "Here is the most relevant guidance for your question, with extra weight on graduate-school fit and long-term academic trajectory."
        if primary == "gpa_protection":
            return "Here is the most relevant guidance for your question, with extra weight on realistic fit and academic risk."
    return "Here is the most relevant guidance for your question."


def _program_outline_for_operating_model(student_operating_model: dict[str, Any]) -> str:
    risk = str((student_operating_model or {}).get("risk_tolerance", ""))
    planning_style = str((student_operating_model or {}).get("planning_style", ""))
    certainty = str((student_operating_model or {}).get("certainty_preference", ""))
    grad_school = str((student_operating_model or {}).get("grad_school_seriousness", ""))
    if grad_school == "high":
        return "The guidance keeps long-term academic upside more visible because your recent signals suggest graduate-school preparation is a serious objective."
    if certainty == "high":
        return "The guidance leans toward clearer, better-supported options because your recent signals suggest you prefer higher-certainty decisions."
    if risk == "conservative":
        return "The guidance also leans toward better-supported and lower-volatility options because your recent signals suggest you prefer safer tradeoffs."
    if planning_style == "exploratory":
        return "The guidance keeps a wider option set visible because your recent signals suggest you may still be exploring alternatives."
    return ""


def _program_next_step_for_strategy(
    student_strategy: dict[str, Any],
    student_operating_model: dict[str, Any],
    recommendation_outcome_profile: dict[str, Any],
    asks_university_selection: bool,
    asks_admission_chances: bool,
) -> str:
    primary = str((student_strategy or {}).get("primary_priority", "balanced_progress"))
    risk = str((student_operating_model or {}).get("risk_tolerance", ""))
    certainty = str((student_operating_model or {}).get("certainty_preference", ""))
    follow_through_style = str((recommendation_outcome_profile or {}).get("follow_through_style", ""))
    if follow_through_style == "prefers_small_commits":
        return "Start with one narrow input set, like GPA plus preferred locations, and I can turn that into a smaller safer shortlist before we widen the plan."
    if asks_university_selection or asks_admission_chances:
        if primary == "grad_school_preparation":
            return "If you share your GPA, research/project depth, preferred locations, and target subfield, I can produce a safer moderate/ambitious shortlist next."
        if primary == "gpa_protection":
            return "If you share your GPA, budget, and preferred locations, I can produce a shortlist that stays realistic and avoids overreaching."
        if certainty == "high":
            return "If you share your GPA, budget, preferred locations, and target subfield, I can produce a shortlist that prioritizes the clearest evidence-backed options first."
        if risk == "conservative":
            return "If you share your GPA, budget, and preferred locations, I can produce a shortlist that stays evidence-backed and avoids unnecessary stretch."
        return "If you share your GPA, preferred locations, budget range, and target subfield, I can produce a concrete safe/moderate/ambitious shortlist next."
    if follow_through_style == "high_follow_through":
        return "Use the official program page as the primary source, then lock in one verified next action immediately so the plan keeps moving."
    return "Use the official program page as the primary source and verify any time-sensitive or policy-specific details before acting."


def _build_program_paths(
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
    conservative_reason = "Favor the most realistic and best-supported program directions first."
    balanced_reason = "Mix realistic options with moderate stretch while preserving flexibility."
    aggressive_reason = "Lean harder into the strongest stretch options, accepting more uncertainty."
    if primary == "grad_school_preparation":
        aggressive_reason = "Lean harder into the programs or program paths that maximize long-term academic upside, even with more admission risk."
    elif primary == "gpa_protection":
        conservative_reason = "Favor the paths most consistent with current academic standing and lower downside risk."
    if risk == "conservative":
        conservative_reason = "Favor the most evidence-backed and lower-volatility directions first."
    if certainty == "high":
        conservative_reason = "Favor the clearest evidence-backed directions first because your current signals suggest higher-certainty choices are a better fit."
    if grad_school == "high":
        aggressive_reason = "Keep the stronger academic-upside paths visible because your current signals suggest long-term graduate-school preparation matters."
    if follow_through_style == "prefers_small_commits":
        conservative_reason = "Favor the path with the smallest high-confidence commitment first because your recent follow-through signals suggest narrower next steps land better."
    paths = [
        {"label": "Conservative", "reason": conservative_reason, "courses": labels[:2]},
        {"label": "Balanced", "reason": balanced_reason, "courses": labels[:3]},
        {"label": "Aggressive", "reason": aggressive_reason, "courses": labels[:4]},
    ]
    if blockers:
        for path in paths:
            path["watchouts"] = blockers[:2]
    return paths
