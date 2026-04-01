"""Node: Program Advisor.

Builds a structured academic-program decision payload from session
summary plus extracted evidence records.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.adapters.llm.lmstudio import get_text_llm
from app.core.quality import DecisionPayload, build_support_ref, group_evidence_records
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.program_advisor")

_PROGRAM_PROMPT = """You are Pathfinder's Program Advisor.

Produce a structured decision payload for academic-program and requirements questions.

Return ONLY valid JSON:
{
  "decision_type": "program_guidance",
  "answer_outline": ["..."],
  "recommended_items": [
    {
      "label": "MS in Computer Science requirement summary",
      "reason": "Why this matters for the user's decision",
      "status": "verified|recommended|comparison_note",
      "support_codes": [],
      "assumption": ""
    }
  ],
  "blocked_or_uncertain_items": [
    {"label": "...", "reason": "...", "kind": "uncertain|blocked|needs_verification"}
  ],
  "assumptions": ["..."],
  "next_best_action": "one concrete next step",
  "source_refs": [{"title": "...", "url": "...", "excerpt": "...", "source_type": "degree_page", "entity_type": "requirement"}]
}

Rules:
1. Answer the user's decision question first, not with a general summary.
2. Prefer direct recommendations, comparisons, and requirement implications.
3. Distinguish verified requirements from assumptions.
4. Do not invent policies, deadlines, or prerequisites.
5. Every recommendation must be supported by source refs.
"""


async def program_advisor(state: PathfinderState) -> PathfinderState:
    """Generate structured program guidance."""
    query = state.get("query", "")
    summary = state.get("session_summary", {})
    evidence_records = state.get("evidence_records", [])
    evidence_groups = group_evidence_records(evidence_records, state.get("profile_data", {}))

    step_progress = list(state.get("step_progress", []))
    step_progress.append("Building program guidance...")

    baseline = _heuristic_program_payload(summary, evidence_groups)
    llm_payload = await _llm_program_payload(query, summary, evidence_groups)
    merged = _merge_payloads(baseline, llm_payload)

    step_progress.append("Program guidance prepared")
    log.info(
        "Program advisor produced %d recommendation(s)",
        len(merged.get("recommended_items", [])),
    )

    return {
        **state,
        "decision_payload": merged,
        "draft_answer": "",
        "step_progress": step_progress,
        "next_node": "evaluator",
    }


async def _llm_program_payload(
    query: str,
    summary: dict[str, Any],
    evidence_groups: dict[str, Any],
) -> DecisionPayload:
    if not any(evidence_groups.values()):
        return {}

    llm = get_text_llm()
    response = await llm.ainvoke([
        SystemMessage(content=_PROGRAM_PROMPT),
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
        log.warning("Program advisor parse failed: %s", exc)
        return {}


def _heuristic_program_payload(
    summary: dict[str, Any],
    evidence_groups: dict[str, Any],
) -> DecisionPayload:
    recommended = []
    uncertain = []
    source_refs = []
    assumptions = list(summary.get("assumptions", []))

    institution = summary.get("institution", {}).get("value", "")
    program = summary.get("program", {}).get("value", "")

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

    if not recommended:
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
            "Here is the most relevant program guidance from the verified sources for your question.",
        ],
        "recommended_items": _dedupe_sequence(recommended)[:5],
        "blocked_or_uncertain_items": _dedupe_sequence(uncertain)[:4],
        "assumptions": assumptions,
        "next_best_action": "Use the official program page as the primary source and verify any time-sensitive or policy-specific details before acting.",
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
