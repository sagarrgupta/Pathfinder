"""Node: Course Planner.

Builds a structured decision payload for course-planning questions
using session summary plus extracted evidence records.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.adapters.llm.lmstudio import get_json_llm
from app.agents.advisor_runtime import (
    finalize_structured_advisor,
    prepare_structured_advisor,
)
from app.core.prompts import COURSE_PLANNER_PROMPT
from app.core.quality import (
    DecisionPayload,
    academic_source_relevance,
    build_support_ref,
    course_code_matches_level,
    infer_target_level,
    infer_target_program,
)
from app.core.state import PathfinderState
from app.utils.json_extract import parse_json_object

log = logging.getLogger("pathfinder.agents.course_planner")


async def course_planner(state: PathfinderState) -> PathfinderState:
    """Generate a structured course-planning decision payload."""
    runtime = prepare_structured_advisor(
        state,
        node_name="course_planner",
        progress_message="Building a ranked course plan...",
    )
    query = runtime["query"]
    summary = runtime["summary"]
    evidence_groups = runtime["evidence_groups"]
    target_program = infer_target_program(state.get("profile_data", {}), summary, query)
    target_level = infer_target_level(state.get("profile_data", {}), summary, query)

    merged_summary = _merge_planner_summary(
        summary,
        state.get("compacted_session", {}),
        state.get("profile_data", {}),
        state.get("semantic_memory", {}),
        state.get("query", ""),
    )
    student_strategy = state.get("student_strategy", {})
    student_operating_model = state.get("student_operating_model", {})
    recommendation_outcome_profile = state.get("recommendation_outcome_profile", {})
    decision_payload = _heuristic_course_payload(
        merged_summary,
        evidence_groups,
        target_program,
        target_level,
        query,
        student_strategy,
        student_operating_model,
        recommendation_outcome_profile,
    )
    llm_payload = await _llm_course_payload(query, summary, evidence_groups, runtime["handoff_context"])

    merged = _merge_payloads(decision_payload, llm_payload)
    merged["student_strategy"] = dict(student_strategy or {})
    merged["recommendation_paths"] = _build_recommendation_paths(
        merged.get("recommended_items", []),
        merged.get("blocked_or_uncertain_items", []),
        student_strategy,
        student_operating_model,
        recommendation_outcome_profile,
    )
    merged = _enforce_recommendation_support(merged)
    draft = _render_course_draft(merged)
    log.info(
        "Course planner produced %d recommendations",
        len(merged.get("recommended_items", [])),
    )
    return finalize_structured_advisor(
        state,
        node_name="course_planner",
        completion_message="Course plan prepared",
        ranking_note="Course planner ranked recommendations from typed evidence groups.",
        merged_payload=merged,
        tool_call_log=list(state.get("tool_call_log", [])),
        runtime=runtime,
        draft_answer=draft,
        stop_reason=_planner_stop_reason(merged, runtime["blocked_reasons"]),
        complete_rank_options_without_recommendations=False,
    )


async def _llm_course_payload(
    query: str,
    summary: dict[str, Any],
    evidence_groups: dict[str, Any],
    handoff_context: list[dict[str, str]],
) -> DecisionPayload:
    """Ask the LLM to synthesize a structured decision from the evidence."""
    if not any(evidence_groups.values()):
        return {}

    llm = get_json_llm()
    response = await llm.ainvoke([
        SystemMessage(content=COURSE_PLANNER_PROMPT),
        HumanMessage(content=(
            f"User query:\n{query}\n\n"
            f"Session summary:\n{json.dumps(summary, ensure_ascii=True)}\n\n"
            f"Handoff notes:\n{json.dumps(handoff_context, ensure_ascii=True)}\n\n"
            f"Evidence groups:\n{json.dumps(evidence_groups, ensure_ascii=True)}"
        )),
    ])

    content = response.content if isinstance(response.content, str) else str(response.content)
    try:
        parsed = parse_json_object(content) or {}
        return parsed if isinstance(parsed, dict) else {}
    except Exception as exc:
        log.warning("Course planner parse failed: %s", exc)
        return {}


def _heuristic_course_payload(
    summary: dict[str, Any],
    evidence_groups: dict[str, Any],
    target_program: str = "",
    target_level: str = "unknown",
    query: str = "",
    student_strategy: dict[str, Any] | None = None,
    student_operating_model: dict[str, Any] | None = None,
    recommendation_outcome_profile: dict[str, Any] | None = None,
) -> DecisionPayload:
    student_strategy = student_strategy or {}
    student_operating_model = student_operating_model or {}
    recommendation_outcome_profile = recommendation_outcome_profile or {}
    """Build a baseline decision payload deterministically."""
    target_program = target_program or str(summary.get("program", {}).get("value", ""))
    if target_level == "unknown":
        program_text = target_program.lower()
        if any(word in program_text for word in ("master", "masters", "graduate", "ms")):
            target_level = "graduate"
    target_institution = str((summary.get("institution", {}) or {}).get("value", "") or "")
    query_lower = (query or "").lower()
    asks_major_or_electives = any(token in query_lower for token in ("major", "elective", "specialization", "concentration"))
    allowed_prefixes = _allowed_course_prefixes(target_program)

    assumptions = list(summary.get("assumptions", []))

    if asks_major_or_electives and not target_institution:
        return {
            "decision_type": "course_planning",
            "answer_outline": [
                "I need to know your university and program to give you accurate major and elective recommendations.",
            ],
            "recommended_items": [],
            "blocked_or_uncertain_items": [
                {
                    "label": "University and program context needed",
                    "reason": "Without knowing your institution and program, I cannot look up the correct catalog or verify course availability.",
                    "kind": "needs_verification",
                }
            ],
            "assumptions": assumptions,
            "next_best_action": "Please share your university and program so I can look up your specific catalog and give personalized recommendations.",
            "source_refs": [],
            "verified_requirements": [],
            "semester_plan_options": [],
            "blocked_reasons": ["safe_partial_plan:missing_institution_context"],
        }

    required: list[dict[str, Any]] = []
    goal_aligned: list[dict[str, Any]] = []
    uncertain: list[dict[str, Any]] = []
    support_refs = []
    goal_text = " ".join(summary.get("goals", {}).get("value", []))
    completed = set(summary.get("completed_courses", {}).get("value", []))
    availability_records = evidence_groups.get("availability", [])
    course_records = evidence_groups.get("courses", [])
    constraint_records = evidence_groups.get("constraints", [])
    requirement_records = evidence_groups.get("requirements", [])
    live_codes = {
        rec.get("value", {}).get("code", "")
        for rec in availability_records
    }

    if constraint_records:
        assumptions.append("Some prerequisite or program-constraint evidence was found and may affect final enrollment eligibility.")

    program_model = _compile_academic_program_model(requirement_records, course_records, summary, target_program)

    candidate_records = [
        record
        for record in course_records + availability_records
        if _record_matches_program_context(record, target_program, target_level, target_institution)
    ]
    direct_primary_courses = [
        record for record in candidate_records
        if (
            (record.get("trust_tier") == "primary_official" and record.get("fit_tier") in {"direct", ""})
            or (
                not record.get("trust_tier")
                and record.get("source_type") in {"degree_page", "schedule_page", "admissions_page"}
            )
        )
    ]

    for record in candidate_records:
        code = record.get("value", {}).get("code", "")
        if not code or code in completed:
            continue
        if not _code_allowed_for_program(code, allowed_prefixes):
            continue
        label = record.get("value", {}).get("name") or code
        ref = build_support_ref(record)
        if ref.get("url"):
            support_refs.append(ref)

        support_ref = build_support_ref(record)
        entry = {
            "label": label if code in label else f"{code} {label}".strip(),
            "reason": _course_reason(code, goal_text, record),
            "status": "confirmed_open" if code in live_codes else "catalog_option",
            "support_codes": [code],
            "support_refs": [support_ref] if support_ref.get("url") else [],
            "assumption": "" if code in live_codes else "Assuming normal standing and no hidden deficiency constraints.",
        }

        if _is_required_core(record):
            if not any(item.get("support_codes") == [code] for item in required):
                required.append(entry)
        elif _is_goal_aligned(record, goal_text):
            if not any(item.get("support_codes") == [code] for item in goal_aligned):
                goal_aligned.append(entry)
        else:
            uncertain.append({
                "label": entry["label"],
                "reason": "This course appears in the evidence but is not clearly a top next-step recommendation yet.",
                "kind": "uncertain",
            })

    if not required and requirement_records:
        for record in requirement_records:
            if not _record_matches_program_context(record, target_program, target_level, target_institution):
                continue
            excerpt = f"{record.get('source_title', '')} {record.get('excerpt', '')}"
            for code in _extract_course_codes_from_text(excerpt)[:6]:
                if code in completed:
                    continue
                if not _code_allowed_for_program(code, allowed_prefixes):
                    continue
                ref = build_support_ref(record)
                if ref.get("url"):
                    support_refs.append(ref)
                item = {
                    "label": code,
                    "reason": "This course code appears in official program requirement evidence and is a strong catalog-based planning candidate.",
                    "status": "catalog_option",
                    "support_codes": [code],
                    "support_refs": [ref] if ref.get("url") else [],
                    "assumption": "Assuming prerequisites and classification status are satisfied.",
                }
                if not any(existing.get("support_codes") == [code] for existing in required):
                    required.append(item)

    if not required and program_model.get("required_core"):
        for core in program_model["required_core"][:8]:
            core_code = core.get("code", "")
            if not core_code or core_code in completed:
                continue
            if not _code_allowed_for_program(core_code, allowed_prefixes):
                continue
            ref = core.get("support_ref", {})
            required.append({
                "label": f"{core_code} {core.get('name', '')}".strip(),
                "reason": "This appears in the verified core requirement model and is a strong catalog-based planning course.",
                "status": "catalog_option",
                "support_codes": [core_code],
                "support_refs": [ref] if ref.get("url") else [],
                "assumption": "Assuming prerequisites and classification status are satisfied.",
            })
            if ref.get("url"):
                support_refs.append(ref)

    recommended_items = (required[:4] + goal_aligned[:4])[:6]

    if not live_codes:
        assumptions.append("Current open sections were not directly verified in retrieved schedule sources.")

    direct_primary_requirements = [
        record for record in requirement_records
        if _record_matches_program_context(record, target_program, target_level, target_institution)
        and record.get("trust_tier") == "primary_official"
        and record.get("fit_tier") in {"direct", "adjacent", ""}
    ]

    if not direct_primary_courses and not direct_primary_requirements:
        return {
            "decision_type": "course_planning",
            "answer_outline": [
                "I could not find enough primary official program requirement evidence to safely build a semester plan.",
            ],
            "recommended_items": [],
            "blocked_or_uncertain_items": [{
                "label": "Primary official course evidence missing",
                "reason": "The retrieved sources do not yet contain enough direct official program/course evidence for a safe ranked recommendation.",
                "kind": "blocked",
            }],
            "assumptions": assumptions,
            "next_best_action": "Retrieve the official program page, official course catalog, or current graduate schedule and then rank the next-semester options.",
            "source_refs": _dedupe_source_refs(support_refs)[:8],
            "verified_requirements": _render_verified_requirements(program_model),
            "semester_plan_options": [],
            "student_strategy": dict(student_strategy),
            "blocked_reasons": ["hard_blocked:missing_primary_program_requirements"],
        }

    if not recommended_items:
        sample_plan = _build_semester_plan_options(program_model, goal_aligned, query)
        return {
            "decision_type": "course_planning",
            "answer_outline": [
                "I could not verify enough live offerings, but I can still give you a catalog-based semester planning sample from official program requirements.",
            ],
            "recommended_items": sample_plan[0].get("courses", [])[:6] if sample_plan else [],
            "blocked_or_uncertain_items": [{
                "label": "Program-matched graduate course set not verified",
                "reason": "Live schedule availability is not confirmed; this plan is catalog-based and should be verified against the registrar schedule.",
                "kind": "needs_verification",
            }],
            "assumptions": assumptions,
            "next_best_action": "Use the official graduate program page and current graduate schedule, then I can rank the best next-semester options.",
            "source_refs": _dedupe_source_refs(support_refs)[:8],
            "verified_requirements": _render_verified_requirements(program_model),
            "semester_plan_options": sample_plan,
            "student_strategy": dict(student_strategy),
            "blocked_reasons": ["safe_partial_plan:catalog_without_live_schedule"],
        }

    sample_plan = _build_semester_plan_options(program_model, recommended_items + goal_aligned, query)
    return {
        "decision_type": "course_planning",
        "answer_outline": [
            _course_outline_for_strategy(student_strategy),
            _course_outline_for_operating_model(student_operating_model),
        ],
        "recommended_items": recommended_items,
        "blocked_or_uncertain_items": uncertain[:4],
        "assumptions": assumptions,
        "next_best_action": _next_step_for_strategy(
            student_strategy,
            student_operating_model,
            recommendation_outcome_profile,
        ),
        "source_refs": _dedupe_source_refs(support_refs)[:8],
        "verified_requirements": _render_verified_requirements(program_model),
        "semester_plan_options": sample_plan,
        "student_strategy": dict(student_strategy),
        "blocked_reasons": ["safe_partial_plan:catalog_without_live_schedule"] if not live_codes else [],
    }


def _merge_payloads(base: DecisionPayload, llm_payload: DecisionPayload) -> DecisionPayload:
    """Merge heuristic and LLM payloads conservatively."""
    if not llm_payload:
        return base

    merged = dict(base)
    for key in ("decision_type", "next_best_action", "student_strategy"):
        if llm_payload.get(key):
            merged[key] = llm_payload[key]

    for key in (
        "answer_outline",
        "recommended_items",
        "blocked_or_uncertain_items",
        "assumptions",
        "source_refs",
        "verified_requirements",
        "semester_plan_options",
        "blocked_reasons",
        "recommendation_paths",
    ):
        values = list(base.get(key, [])) + list(llm_payload.get(key, []))
        merged[key] = _dedupe_sequence(values)

    return merged


def _render_course_draft(payload: DecisionPayload) -> str:
    """Render a structured payload into concise markdown prose."""
    lines = []
    outline = payload.get("answer_outline", [])
    if outline:
        lines.append(outline[0])

    recommended = payload.get("recommended_items", [])
    if recommended:
        lines.append("\n**Top options**")
        for item in recommended[:5]:
            status = item.get("status", "")
            status_label = {
                "confirmed_open": "confirmed open",
                "likely_next": "strong next-step option",
                "catalog_option": "catalog-based option",
            }.get(status, status)
            lines.append(f"- **{item.get('label', '')}**: {item.get('reason', '')} ({status_label})")

    blocked = payload.get("blocked_or_uncertain_items", [])
    if blocked:
        lines.append("\n**Uncertain or needs verification**")
        for item in blocked[:3]:
            lines.append(f"- **{item.get('label', '')}**: {item.get('reason', '')}")

    assumptions = payload.get("assumptions", [])
    if assumptions:
        lines.append("\n**Assumptions**")
        for assumption in assumptions[:3]:
            lines.append(f"- {assumption}")

    requirements = payload.get("verified_requirements", [])
    if requirements:
        lines.append("\n**Verified Program Rules**")
        for requirement in requirements[:4]:
            lines.append(f"- {requirement}")

    plan_options = payload.get("semester_plan_options", [])
    if plan_options:
        lines.append("\n**Sample Semester Plan (Catalog-Based)**")
        for option in plan_options[:2]:
            term = option.get("term", "")
            labels = []
            for course in option.get("courses", [])[:4]:
                if isinstance(course, dict):
                    labels.append(str(course.get("label", "")))
                else:
                    labels.append(str(course))
            if term and labels:
                lines.append(f"- **{term}**: {', '.join([label for label in labels if label])}")
        lines.append("- Verify live offering/section availability in the official schedule before registration.")

    if payload.get("next_best_action"):
        lines.append(f"\n**Next step:** {payload['next_best_action']}")

    return "\n".join(lines).strip()


def _course_outline_for_strategy(student_strategy: dict[str, Any]) -> str:
    primary = str((student_strategy or {}).get("primary_priority", "balanced_progress"))
    if primary == "internship_readiness":
        return "Here are the strongest next-semester options based on your program, with extra weight on internship readiness and applied skill growth."
    if primary == "gpa_protection":
        return "Here are the strongest next-semester options based on your program, with extra weight on protecting GPA and avoiding unnecessary overload."
    if primary == "graduation_speed":
        return "Here are the strongest next-semester options based on your program, with extra weight on keeping graduation progress efficient."
    if primary == "grad_school_preparation":
        return "Here are the strongest next-semester options based on your program, with extra weight on graduate-school preparation and academic depth."
    if primary == "workload_balance":
        return "Here are the strongest next-semester options based on your program, with extra weight on maintaining a manageable workload."
    return "Here are the strongest catalog-based next-semester options based on your program, goals, and the verified sources."


def _course_outline_for_operating_model(student_operating_model: dict[str, Any]) -> str:
    risk = str((student_operating_model or {}).get("risk_tolerance", ""))
    load = str((student_operating_model or {}).get("workload_preference", ""))
    certainty = str((student_operating_model or {}).get("certainty_preference", ""))
    grad_school = str((student_operating_model or {}).get("grad_school_seriousness", ""))
    if risk == "conservative" and load == "lighter":
        return "The recommendations also lean toward steadier, lower-volatility choices because your recent signals suggest you prefer safer tradeoffs and manageable load."
    if grad_school == "high":
        return "The recommendations keep academic depth visible because your recent signals suggest graduate-school preparation is a serious consideration."
    if certainty == "high":
        return "The recommendations lean toward clearer, better-supported choices because your recent signals suggest you prefer higher-certainty decisions."
    if risk == "ambitious":
        return "A stretch path stays visible because your recent signals suggest you may tolerate more upside-seeking tradeoffs."
    if load == "lighter":
        return "The recommendations keep term shape in mind because your recent signals suggest workload sustainability matters."
    return ""


def _next_step_for_strategy(
    student_strategy: dict[str, Any],
    student_operating_model: dict[str, Any] | None = None,
    recommendation_outcome_profile: dict[str, Any] | None = None,
) -> str:
    primary = str((student_strategy or {}).get("primary_priority", "balanced_progress"))
    student_operating_model = student_operating_model or {}
    recommendation_outcome_profile = recommendation_outcome_profile or {}
    risk = str(student_operating_model.get("risk_tolerance", ""))
    load = str(student_operating_model.get("workload_preference", ""))
    certainty = str(student_operating_model.get("certainty_preference", ""))
    follow_through_style = str(recommendation_outcome_profile.get("follow_through_style", ""))
    if follow_through_style == "prefers_small_commits":
        return "Pick one small course-planning action first, like verifying the registrar schedule for the top option, before committing to the full semester plan."
    if primary == "internship_readiness":
        if load == "lighter":
            return "Check the registrar schedule, then prioritize the most resume-relevant courses without crowding out project time."
        return "Check the registrar schedule, then prioritize the courses that strengthen resume-ready skills and project depth."
    if primary == "gpa_protection":
        return "Check the registrar schedule, then keep the strongest options while avoiding a term that is too theory-heavy all at once."
    if primary == "graduation_speed":
        if risk == "conservative":
            return "Check the registrar schedule and lock in the fastest requirement-clearing options that still keep the term stable."
        return "Check the registrar schedule and lock in the options that clear the most important requirements earliest."
    if primary == "grad_school_preparation":
        return "Check the registrar schedule and favor the options that add stronger academic depth, research alignment, or advanced technical preparation."
    if primary == "workload_balance":
        return "Check the registrar schedule and choose the most important options while keeping the term load sustainable."
    if certainty == "high":
        return "Check the registrar schedule and verify the clearest well-supported options first before considering stretch choices."
    if follow_through_style == "high_follow_through":
        return "Check the registrar schedule, then commit to the top verified course option and lock in the next supporting step right away."
    return "Check the registrar schedule for live section availability for the top-ranked courses."


def _build_recommendation_paths(
    recommended_items: list[dict[str, Any]],
    blocked_items: list[dict[str, Any]],
    student_strategy: dict[str, Any],
    student_operating_model: dict[str, Any] | None = None,
    recommendation_outcome_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    primary = str((student_strategy or {}).get("primary_priority", "balanced_progress"))
    student_operating_model = student_operating_model or {}
    recommendation_outcome_profile = recommendation_outcome_profile or {}
    risk = str(student_operating_model.get("risk_tolerance", ""))
    load = str(student_operating_model.get("workload_preference", ""))
    certainty = str(student_operating_model.get("certainty_preference", ""))
    grad_school = str(student_operating_model.get("grad_school_seriousness", ""))
    follow_through_style = str(recommendation_outcome_profile.get("follow_through_style", ""))
    top_items = [item for item in recommended_items if isinstance(item, dict)]
    top_labels = [str(item.get("label", "")).strip() for item in top_items if str(item.get("label", "")).strip()]
    blocked_labels = [
        str(item.get("label", "")).strip()
        for item in blocked_items
        if isinstance(item, dict) and str(item.get("label", "")).strip()
    ]
    if not top_labels:
        return []
    conservative_reason = "Lighter risk path that keeps progress moving while leaving room for verification and workload control."
    balanced_reason = "Middle path that balances requirement progress with the student's current goals."
    aggressive_reason = "Higher-upside path that pushes faster toward the main priority, but may need more capacity or verification."
    if primary == "internship_readiness":
        conservative_reason = "Choose the most practical and manageable courses first so you can still build projects and prepare for internship applications."
        aggressive_reason = "Lean harder into the most career-aligned courses, even if the term becomes more demanding."
    elif primary == "gpa_protection":
        conservative_reason = "Favor the safest high-value courses first to reduce grade risk."
        aggressive_reason = "Take on more important requirements sooner, but with a higher chance of GPA pressure."
    elif primary == "graduation_speed":
        balanced_reason = "Keep requirement progress strong without overloading the semester."
        aggressive_reason = "Push more requirements forward now to shorten the path to graduation."
    elif primary == "grad_school_preparation":
        aggressive_reason = "Favor deeper or more advanced courses now to strengthen later graduate applications."
    if risk == "conservative":
        conservative_reason = "Favor the most stable, well-supported path first because your current signals suggest lower-risk tradeoffs."
    if load == "lighter":
        balanced_reason = "Keep meaningful progress while preserving a term shape that still feels sustainable."
    if certainty == "high":
        conservative_reason = "Favor the clearest, best-supported path first because your current signals suggest higher-certainty decisions are a better fit."
    if grad_school == "high":
        aggressive_reason = "Keep a deeper academic path visible because your current signals suggest long-term graduate-school preparation matters."
    if follow_through_style == "prefers_small_commits":
        conservative_reason = "Favor the smallest high-value path first because your recent follow-through signals suggest smaller commitments are more sustainable."
    conservative_courses = top_labels[:2]
    balanced_courses = top_labels[:3]
    aggressive_courses = top_labels[:4]
    paths = [
        {"label": "Conservative", "reason": conservative_reason, "courses": conservative_courses},
        {"label": "Balanced", "reason": balanced_reason, "courses": balanced_courses},
        {"label": "Aggressive", "reason": aggressive_reason, "courses": aggressive_courses},
    ]
    if blocked_labels:
        for path in paths:
            path["watchouts"] = blocked_labels[:2]
    return paths


def _is_required_core(record: dict[str, Any]) -> bool:
    source_type = record.get("source_type", "")
    excerpt = record.get("excerpt", "").lower()
    return source_type == "degree_page" or "required" in excerpt or "core" in excerpt


def _is_goal_aligned(record: dict[str, Any], goal_text: str) -> bool:
    if not goal_text.strip():
        return False

    value = record.get("value", {})
    haystack = " ".join(
        str(part)
        for part in (
            value.get("name", ""),
            value.get("details", ""),
            value.get("kind", ""),
            record.get("excerpt", ""),
        )
    ).lower()
    goal_tokens = _meaningful_tokens(goal_text)
    if not goal_tokens:
        return False

    if "ai" in goal_tokens and any(phrase in haystack for phrase in ("artificial intelligence", "machine learning", "deep learning", "neural")):
        return True
    if "ml" in goal_tokens and any(phrase in haystack for phrase in ("machine learning", "artificial intelligence", "predictive")):
        return True

    overlap = [token for token in goal_tokens if token in haystack]
    if len(overlap) >= 2:
        return True
    if overlap and any(keyword in haystack for keyword in ("project", "specialization", "track", "concentration", "advanced")):
        return True
    return False


def _course_reason(code: str, goal_text: str, record: dict[str, Any]) -> str:
    if _is_goal_aligned(record, goal_text):
        return "This course is directly aligned with the student's stated goal."
    if _is_required_core(record):
        return "This appears to be part of the core program foundation and is a strong early priority."
    return "This appears in the verified academic sources and may fit the student's next-semester plan."


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


def _record_matches_program_context(
    record: dict[str, Any],
    target_program: str,
    target_level: str,
    target_institution: str = "",
) -> bool:
    title = record.get("source_title", "")
    excerpt = record.get("excerpt", "")
    url = record.get("source_url", "")
    code = str((record.get("value", {}) or {}).get("code", ""))
    source_type = record.get("source_type", "")
    trust_tier = str(record.get("trust_tier", "") or "")
    number_match = re.search(r"(\d{3})", code)
    if target_level == "graduate" and number_match:
        number = int(number_match.group(1))
        # Only filter out very low course numbers (< 100) that are almost
        # certainly intro/remedial. Different universities use different
        # numbering conventions, so we cannot assume < 200 = undergraduate.
        if number < 100:
            prereq_context = f"{title} {excerpt}".lower()
            if source_type == "schedule_page":
                return False
            if "prereq" not in prereq_context and "deficien" not in prereq_context and "admission" not in prereq_context:
                return False
    if code and not course_code_matches_level(code, target_level, title, excerpt):
        return False
    if trust_tier == "third_party" and source_type not in {"degree_page", "admissions_page", "schedule_page"}:
        return False

    if not target_program:
        return source_type in {"degree_page", "certificate_page"} or bool(code)

    relevance = academic_source_relevance(
        title,
        excerpt,
        url,
        target_program,
        target_level,
        target_institution,
    )
    if relevance >= 1.0:
        return True

    if source_type == "certificate_page" and code:
        return True

    return False


def _extract_course_codes_from_text(text: str) -> list[str]:
    codes: list[str] = []
    for match in re.findall(r"\b[A-Z]{2,4}\s?-?\d{3}[A-Z]?\b", text or ""):
        code = match.replace("-", " ").replace("  ", " ").strip().upper()
        if code not in codes:
            codes.append(code)
    return codes


def _allowed_course_prefixes(target_program: str) -> set[str]:
    # No hardcoded prefix filtering — course relevance is determined
    # by evidence records and source context, not by code prefix.
    # Different universities use different prefix conventions.
    return set()


def _code_allowed_for_program(code: str, allowed_prefixes: set[str]) -> bool:
    if not allowed_prefixes:
        return True
    match = re.match(r"^([A-Z]{2,5})\s?-?\d{3}[A-Z]?$", (code or "").strip().upper())
    if not match:
        return True
    prefix = match.group(1)
    return prefix in allowed_prefixes


def _meaningful_tokens(text: str) -> list[str]:
    stopwords = {
        "want", "become", "work", "role", "career", "field", "engineer", "student",
        "goal", "study", "program", "next", "semester", "good", "best",
    }
    tokens = []
    for token in re.findall(r"[a-z0-9]{2,}", text.lower()):
        if token not in stopwords and token not in tokens:
            tokens.append(token)
    return tokens


def _compile_academic_program_model(
    requirement_records: list[dict[str, Any]],
    course_records: list[dict[str, Any]],
    summary: dict[str, Any],
    target_program: str,
) -> dict[str, Any]:
    model: dict[str, Any] = {
        "program": target_program or str((summary.get("program", {}) or {}).get("value", "")),
        "required_core": [],
        "total_units": None,
        "breadth_units": None,
        "milestones": [],
    }
    required_core: list[dict[str, Any]] = []
    seen_codes: set[str] = set()

    for record in requirement_records:
        trust_tier = str(record.get("trust_tier", "") or "")
        source_type = str(record.get("source_type", "") or "")
        if trust_tier == "third_party":
            continue
        if source_type not in {"degree_page", "admissions_page", "schedule_page", "profile_doc"}:
            continue
        text = f"{record.get('source_title', '')} {record.get('excerpt', '')} {record.get('value', {}).get('summary', '')}"
        if model["total_units"] is None:
            unit_match = re.search(r"\b(\d{2})\s+units?\b", text, re.I)
            if unit_match:
                model["total_units"] = int(unit_match.group(1))
        if model["breadth_units"] is None:
            breadth_match = re.search(r"\b(\d{1,2})\s+breadth\s+units?\b", text, re.I)
            if breadth_match:
                model["breadth_units"] = int(breadth_match.group(1))
        if re.search(r"\bcandidacy\b", text, re.I):
            model["milestones"].append("Advancement to candidacy required before culminating experience.")
        if re.search(r"\bculminating\b|\bthesis\b|\bproject\b", text, re.I):
            model["milestones"].append("Culminating experience planning is required in later semesters.")

        for code in _extract_course_codes_from_text(text):
            if code in seen_codes:
                continue
            seen_codes.add(code)
            required_core.append({
                "code": code,
                "name": "",
                "support_ref": build_support_ref(record),
            })

    for record in course_records:
        trust_tier = str(record.get("trust_tier", "") or "")
        if trust_tier == "third_party":
            continue
        if not _is_required_core(record):
            continue
        code = str((record.get("value", {}) or {}).get("code", ""))
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        required_core.append({
            "code": code,
            "name": str((record.get("value", {}) or {}).get("name", "")),
            "support_ref": build_support_ref(record),
        })

    model["required_core"] = required_core[:16]
    model["milestones"] = _dedupe_sequence(model["milestones"])
    return model


def _render_verified_requirements(program_model: dict[str, Any]) -> list[str]:
    rendered: list[str] = []
    total_units = program_model.get("total_units")
    breadth_units = program_model.get("breadth_units")
    core_codes = [item.get("code", "") for item in program_model.get("required_core", []) if item.get("code")]
    if total_units:
        rendered.append(f"Program total: {total_units} units (from official requirement evidence).")
    if breadth_units:
        rendered.append(f"Breadth requirement: {breadth_units} units (from official requirement evidence).")
    if core_codes:
        rendered.append(f"Core/required courses evidenced: {', '.join(core_codes[:8])}.")
    for milestone in program_model.get("milestones", [])[:2]:
        rendered.append(milestone)
    return rendered


def _build_semester_plan_options(
    program_model: dict[str, Any],
    ranked_courses: list[dict[str, Any]],
    query: str,
) -> list[dict[str, Any]]:
    wants_long_range = bool(re.search(r"\b(2\s*year|two\s*year|semester[- ]wise|spring\s+20\d{2}|fall\s+20\d{2}|graduate\s+by)\b", query, re.I))
    if not ranked_courses:
        return []

    normalized_courses = []
    seen = set()
    for item in ranked_courses:
        label = str(item.get("label", "")).strip()
        if not label or label in seen:
            continue
        seen.add(label)
        normalized_courses.append(item)

    if not wants_long_range:
        return [{
            "term": "Next semester",
            "courses": normalized_courses[:3],
            "units_note": "Verify your program's required course load and unit limits before registering.",
        }]

    # Generic four-term sample structure for long-range planning requests.
    buckets = [
        ("Term 1", normalized_courses[0:3]),
        ("Term 2", normalized_courses[3:6] or normalized_courses[0:3]),
        ("Term 3", normalized_courses[6:9] or normalized_courses[1:4]),
        ("Term 4", normalized_courses[9:11] or normalized_courses[2:5]),
    ]
    return [
        {
            "term": term,
            "courses": courses,
            "units_note": "Catalog-based sample; verify live offerings and prerequisites before registration.",
        }
        for term, courses in buckets
        if courses
    ]


def _merge_planner_summary(
    session_summary: dict[str, Any],
    compacted_session: dict[str, Any],
    profile_data: dict[str, Any],
    semantic_memory: dict[str, Any],
    query: str,
) -> dict[str, Any]:
    merged = dict(session_summary or {})
    stable = (compacted_session or {}).get("stable_facts", {}) or {}
    personal = (profile_data or {}).get("personal", {}) or {}
    corrections = list((session_summary or {}).get("recent_corrections", []))

    institution_value = (
        _extract_institution_from_query(query)
        or str((session_summary.get("institution", {}) or {}).get("value", "") or "")
        or str(stable.get("institution", "") or "")
        or str(personal.get("university", "") or "")
    )
    program_value = (
        _extract_program_from_query(query)
        or str((session_summary.get("program", {}) or {}).get("value", "") or "")
        or str(stable.get("program", "") or "")
        or str(personal.get("program", "") or "")
    )
    standing_value = (
        _extract_semester_from_query(query)
        or str((session_summary.get("standing", {}) or {}).get("value", "") or "")
        or str(stable.get("standing", "") or "")
        or str(personal.get("semester", "") or "")
    )

    completed_courses = list((session_summary.get("completed_courses", {}) or {}).get("value", []) or [])
    if not completed_courses:
        completed_courses = list(stable.get("completed_courses", []) or [])
    if not completed_courses:
        completed_courses = [c.get("code", "") for c in (profile_data or {}).get("courses", []) if c.get("code")]

    goals = list((session_summary.get("goals", {}) or {}).get("value", []) or [])
    if not goals:
        goals = [g.get("name", "") for g in (profile_data or {}).get("goals", []) if g.get("name")]
    if not goals:
        temporal_profile = (profile_data or {}).get("temporal_profile", {}) or {}
        goals = [
            str(item.get("value", "")).strip()
            for item in (temporal_profile.get("evolving_facts", []) or [])
            if str(item.get("fact_type", "")).lower() == "goal" and str(item.get("value", "")).strip()
        ]
    if not goals:
        temporal_profile = (profile_data or {}).get("temporal_profile", {}) or {}
        goals = [
            str(item.get("value", "")).strip()
            for item in (temporal_profile.get("active_candidates", []) or [])
            if str(item.get("fact_type", "")).lower() == "goal" and str(item.get("value", "")).strip()
        ]

    if semantic_memory.get("candidate_facts"):
        merged["memory_sources_used"] = ["short", "long"]
    else:
        merged["memory_sources_used"] = ["short"]

    merged["institution"] = {"known": bool(institution_value), "value": institution_value}
    merged["program"] = {"known": bool(program_value), "value": program_value}
    merged["standing"] = {"known": bool(standing_value), "value": standing_value}
    merged["completed_courses"] = {"known": True, "value": _dedupe_sequence(completed_courses)}
    merged["goals"] = {"known": bool(goals), "value": _dedupe_sequence([goal for goal in goals if goal])}
    merged["recent_corrections"] = corrections
    return merged


def _extract_institution_from_query(query: str) -> str:
    match = re.search(r"\b(?:at|from|to)\s+([A-Z][A-Za-z0-9&',.\- ]{6,120}(?:University|College|Institute))\b", query or "", re.I)
    return match.group(1).strip() if match else ""


def _extract_program_from_query(query: str) -> str:
    match = re.search(r"\b(?:in|for)\s+(masters?|ms|m\.s\.)\s+(?:in\s+)?([A-Za-z][A-Za-z0-9&/,\- ]{2,80})\b", query or "", re.I)
    if not match:
        return ""
    degree = match.group(1).strip()
    field = match.group(2).strip().rstrip(".")
    return f"{degree} in {field}"


def _extract_semester_from_query(query: str) -> str:
    match = re.search(r"\b(first|second|third|fourth|\d(?:st|nd|rd|th))\s+semester\b", query or "", re.I)
    return match.group(0).strip() if match else ""


def _enforce_recommendation_support(payload: DecisionPayload) -> DecisionPayload:
    if not payload:
        return {}

    source_refs = payload.get("source_refs", [])
    ref_urls = {ref.get("url", "") for ref in source_refs if ref.get("url")}
    validated = dict(payload)
    kept = []
    blocked = list(payload.get("blocked_or_uncertain_items", []))
    for item in payload.get("recommended_items", []):
        refs = item.get("support_refs", [])
        if refs:
            urls = {ref.get("url", "") for ref in refs if isinstance(ref, dict) and ref.get("url")}
            if urls and urls & ref_urls:
                kept.append(item)
                continue
        if item.get("support_codes"):
            kept.append(item)
            continue
        blocked.append({
            "label": item.get("label", "Recommendation"),
            "reason": "Removed because no claim-level support reference could be validated.",
            "kind": "needs_verification",
        })
    validated["recommended_items"] = kept
    validated["blocked_or_uncertain_items"] = blocked
    return validated


def _planner_stop_reason(payload: DecisionPayload, blocked_reasons: list[str]) -> str:
    if payload.get("blocked_reasons"):
        for reason in payload.get("blocked_reasons", []):
            if isinstance(reason, str) and reason.startswith("hard_blocked"):
                return "hard_blocked"
            if isinstance(reason, str) and reason.startswith("safe_partial_plan"):
                return "safe_partial_plan"
    if blocked_reasons:
        return "partial_answer"
    return ""
