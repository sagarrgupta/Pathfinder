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

from app.adapters.llm.lmstudio import get_text_llm
from app.core.quality import (
    DecisionPayload,
    add_working_memory_item,
    academic_source_relevance,
    build_support_ref,
    complete_task,
    course_code_matches_level,
    group_evidence_records,
    infer_target_level,
    infer_target_program,
    init_working_memory,
)
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.course_planner")

_PLANNER_PROMPT = """You are Pathfinder's Course Planner.

Your task is to produce a structured decision payload for a student's course-planning question.

Return ONLY valid JSON in this form:
{
  "decision_type": "course_planning",
  "answer_outline": ["short paragraph or bullet sentence", "..."],
  "recommended_items": [
    {
      "label": "CSC 215 Artificial Intelligence",
      "reason": "Why this is a good next step for this student",
      "status": "catalog_option|likely_next|confirmed_open",
      "support_codes": ["CSC 215"],
      "assumption": "Assuming fully classified status"
    }
  ],
  "blocked_or_uncertain_items": [
    {
      "label": "CSC 219 Machine Learning",
      "reason": "Why this may be blocked or uncertain",
      "kind": "uncertain|blocked|needs_verification"
    }
  ],
  "assumptions": ["..."],
  "next_best_action": "one concrete next step",
  "source_refs": [
    {"title": "...", "url": "...", "excerpt": "...", "source_type": "degree_page", "entity_type": "course"}
  ]
}

Rules:
1. Answer the student's decision question first.
2. Prefer ranked recommendations over descriptive summaries.
3. Separate catalog-based options from currently confirmed schedule availability.
4. Use assumptions explicitly rather than hiding them.
5. Do not invent course codes, prerequisites, schedules, or degree requirements.
6. Every recommended item must correspond to at least one evidence record.
"""


async def course_planner(state: PathfinderState) -> PathfinderState:
    """Generate a structured course-planning decision payload."""
    query = state.get("query", "")
    summary = state.get("session_summary", {})
    evidence_records = state.get("evidence_records", [])
    evidence_groups = group_evidence_records(evidence_records, state.get("profile_data", {}))
    target_program = infer_target_program(state.get("profile_data", {}), summary, query)
    target_level = infer_target_level(state.get("profile_data", {}), summary, query)
    working_memory = init_working_memory(state.get("working_memory", {}))
    task_graph = state.get("task_graph", [])
    blocked_reasons = list(state.get("blocked_reasons", []))

    step_progress = list(state.get("step_progress", []))
    step_progress.append("Building a ranked course plan...")

    decision_payload = _heuristic_course_payload(summary, evidence_groups, target_program, target_level)
    llm_payload = await _llm_course_payload(query, summary, evidence_groups)

    merged = _merge_payloads(decision_payload, llm_payload)
    draft = _render_course_draft(merged)

    if merged.get("blocked_or_uncertain_items"):
        for item in merged.get("blocked_or_uncertain_items", []):
            if item.get("kind") in {"blocked", "needs_verification"}:
                blocked_reasons.append(item.get("reason", ""))
                working_memory = add_working_memory_item(working_memory, "planner_blockers", item.get("reason", ""))

    if merged.get("assumptions"):
        for assumption in merged.get("assumptions", []):
            working_memory = add_working_memory_item(working_memory, "active_assumptions", assumption)

    if merged.get("recommended_items"):
        working_memory = add_working_memory_item(
            working_memory,
            "ranking_rationale",
            "Course planner ranked recommendations from typed evidence groups.",
        )

    task_graph = complete_task(task_graph, "compare_to_student_state")
    if blocked_reasons:
        task_graph = complete_task(task_graph, "check_blockers")
    if merged.get("recommended_items"):
        task_graph = complete_task(task_graph, "rank_options")

    step_progress.append("Course plan prepared")
    log.info(
        "Course planner produced %d recommendations",
        len(merged.get("recommended_items", [])),
    )

    return {
        **state,
        "decision_payload": merged,
        "draft_answer": draft,
        "working_memory": working_memory,
        "task_graph": task_graph,
        "blocked_reasons": [reason for reason in blocked_reasons if reason],
        "stop_reason": state.get("stop_reason", "") or ("partial_answer" if blocked_reasons else ""),
        "step_progress": step_progress,
        "next_node": "evaluator",
    }


async def _llm_course_payload(
    query: str,
    summary: dict[str, Any],
    evidence_groups: dict[str, Any],
) -> DecisionPayload:
    """Ask the LLM to synthesize a structured decision from the evidence."""
    if not any(evidence_groups.values()):
        return {}

    llm = get_text_llm()
    response = await llm.ainvoke([
        SystemMessage(content=_PLANNER_PROMPT),
        HumanMessage(content=(
            f"User query:\n{query}\n\n"
            f"Session summary:\n{json.dumps(summary, ensure_ascii=True)}\n\n"
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
        log.warning("Course planner parse failed: %s", exc)
        return {}


def _heuristic_course_payload(
    summary: dict[str, Any],
    evidence_groups: dict[str, Any],
    target_program: str = "",
    target_level: str = "unknown",
) -> DecisionPayload:
    """Build a baseline decision payload deterministically."""
    target_program = target_program or str(summary.get("program", {}).get("value", ""))
    if target_level == "unknown":
        program_text = target_program.lower()
        if any(word in program_text for word in ("master", "masters", "graduate", "ms")):
            target_level = "graduate"

    required: list[dict[str, Any]] = []
    ai_aligned: list[dict[str, Any]] = []
    uncertain: list[dict[str, Any]] = []
    support_refs = []
    assumptions = list(summary.get("assumptions", []))

    goal_text = " ".join(summary.get("goals", {}).get("value", []))
    completed = set(summary.get("completed_courses", {}).get("value", []))
    availability_records = evidence_groups.get("availability", [])
    course_records = evidence_groups.get("courses", [])
    constraint_records = evidence_groups.get("constraints", [])
    live_codes = {
        rec.get("value", {}).get("code", "")
        for rec in availability_records
    }

    if constraint_records:
        assumptions.append("Some prerequisite or program-constraint evidence was found and may affect final enrollment eligibility.")

    candidate_records = [
        record
        for record in course_records + availability_records
        if _record_matches_program_context(record, target_program, target_level)
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
        label = record.get("value", {}).get("name") or code
        ref = build_support_ref(record)
        if ref.get("url"):
            support_refs.append(ref)

        entry = {
            "label": label if code in label else f"{code} {label}".strip(),
            "reason": _course_reason(code, goal_text, record),
            "status": "confirmed_open" if code in live_codes else "catalog_option",
            "support_codes": [code],
            "assumption": "" if code in live_codes else "Assuming normal standing and no hidden deficiency constraints.",
        }

        if _is_required_core(record):
            if not any(item.get("support_codes") == [code] for item in required):
                required.append(entry)
        elif _is_goal_aligned(record, goal_text):
            if not any(item.get("support_codes") == [code] for item in ai_aligned):
                ai_aligned.append(entry)
        else:
            uncertain.append({
                "label": entry["label"],
                "reason": "This course appears in the evidence but is not clearly a top next-step recommendation yet.",
                "kind": "uncertain",
            })

    recommended_items = (required[:4] + ai_aligned[:4])[:6]

    if not live_codes:
        assumptions.append("Current open sections were not directly verified in retrieved schedule sources.")

    if not direct_primary_courses:
        return {
            "decision_type": "course_planning",
            "answer_outline": [
                "I found some potentially relevant evidence, but not enough direct primary official program evidence to safely rank your next-semester course options.",
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
        }

    if not recommended_items:
        return {
            "decision_type": "course_planning",
            "answer_outline": [
                "I could not verify a clean set of program-matched course recommendations from the current evidence.",
            ],
            "recommended_items": [],
            "blocked_or_uncertain_items": [{
                "label": "Program-matched graduate course set not verified",
                "reason": "The retrieved sources do not yet provide enough MS-level, program-specific course evidence to recommend a safe next-semester shortlist.",
                "kind": "needs_verification",
            }],
            "assumptions": assumptions,
            "next_best_action": "Use the official graduate program page and current graduate schedule, then I can rank the best next-semester options.",
            "source_refs": _dedupe_source_refs(support_refs)[:8],
        }

    return {
        "decision_type": "course_planning",
        "answer_outline": [
            "Here are the strongest catalog-based next-semester options based on your program, goals, and the verified sources.",
        ],
        "recommended_items": recommended_items,
        "blocked_or_uncertain_items": uncertain[:4],
        "assumptions": assumptions,
        "next_best_action": "Check the registrar schedule for live section availability for the top-ranked courses.",
        "source_refs": _dedupe_source_refs(support_refs)[:8],
    }


def _merge_payloads(base: DecisionPayload, llm_payload: DecisionPayload) -> DecisionPayload:
    """Merge heuristic and LLM payloads conservatively."""
    if not llm_payload:
        return base

    merged = dict(base)
    for key in ("decision_type", "next_best_action"):
        if llm_payload.get(key):
            merged[key] = llm_payload[key]

    for key in ("answer_outline", "recommended_items", "blocked_or_uncertain_items", "assumptions", "source_refs"):
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

    if payload.get("next_best_action"):
        lines.append(f"\n**Next step:** {payload['next_best_action']}")

    return "\n".join(lines).strip()


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


def _record_matches_program_context(record: dict[str, Any], target_program: str, target_level: str) -> bool:
    title = record.get("source_title", "")
    excerpt = record.get("excerpt", "")
    url = record.get("source_url", "")
    code = str((record.get("value", {}) or {}).get("code", ""))
    source_type = record.get("source_type", "")
    if code and not course_code_matches_level(code, target_level, title, excerpt):
        return False

    if not target_program:
        return source_type in {"degree_page", "certificate_page"} or bool(code)

    relevance = academic_source_relevance(title, excerpt, url, target_program, target_level)
    if relevance >= 1.0:
        return True

    if source_type == "certificate_page" and code:
        return True

    return False


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
