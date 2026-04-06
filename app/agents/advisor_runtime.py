"""Shared runtime helpers for structured advisor nodes.

This module centralizes the repeated setup/finalization logic used by
planner-style advisory agents so we can keep the graph shape stable
while reducing prompt drift and boilerplate.
"""

from __future__ import annotations

import json
from typing import Any

from app.adapters.llm.lmstudio import get_text_llm
from app.agents.tool_calling import run_advisor_tool_loop
from app.core.quality import (
    DecisionPayload,
    add_handoff_note,
    add_working_memory_item,
    complete_task,
    group_evidence_records,
    init_working_memory,
    recent_handoff_context,
    start_task,
)
from app.core.state import PathfinderState
from app.utils.json_extract import parse_json_object


def prepare_structured_advisor(
    state: PathfinderState,
    *,
    node_name: str,
    progress_message: str,
) -> dict[str, Any]:
    """Prepare common planner-style advisor inputs from graph state."""
    query = state.get("query", "")
    summary = state.get("session_summary", {})
    profile = state.get("profile_data", {})
    evidence_pack = state.get("evidence_pack", {})
    evidence_records = list(evidence_pack.get("evidence_records", []) or state.get("evidence_records", []))
    evidence_groups = group_evidence_records(evidence_records, profile)
    working_memory = init_working_memory(state.get("working_memory", {}))
    task_graph = state.get("task_graph", [])
    blocked_reasons = list(state.get("blocked_reasons", []))
    for task_id in ("compare_to_student_state", "check_blockers", "rank_options"):
        task_graph = start_task(task_graph, task_id)
    handoff_context = recent_handoff_context(working_memory, to_node=node_name)
    step_progress = list(state.get("step_progress", []))
    step_progress.append(progress_message)
    return {
        "query": query,
        "summary": summary,
        "profile": profile,
        "evidence_records": evidence_records,
        "evidence_groups": evidence_groups,
        "working_memory": working_memory,
        "task_graph": task_graph,
        "blocked_reasons": blocked_reasons,
        "handoff_context": handoff_context,
        "step_progress": step_progress,
    }


async def run_structured_advisor_loop(
    *,
    query: str,
    summary: dict[str, Any],
    evidence_groups: dict[str, Any],
    handoff_context: list[dict[str, str]],
    state: PathfinderState,
    system_prompt: str,
    profile: dict[str, Any] | None = None,
) -> tuple[DecisionPayload, list[dict[str, Any]]]:
    """Run the shared tool-capable advisor synthesis loop and parse JSON."""
    if not any(evidence_groups.values()):
        return {}, list(state.get("tool_call_log", []))

    llm = get_text_llm()
    json_contract = (
        "Return ONLY valid JSON matching this schema keys: decision_type, answer_outline, "
        "recommended_items, blocked_or_uncertain_items, assumptions, next_best_action, source_refs."
    )
    parts = [
        f"User query:\n{query}",
        f"Session summary:\n{json.dumps(summary, ensure_ascii=True)}",
    ]
    if profile:
        parts.append(f"Profile snapshot:\n{json.dumps(profile, ensure_ascii=True)}")
    parts.extend(
        [
            f"Handoff notes:\n{json.dumps(handoff_context, ensure_ascii=True)}",
            f"Evidence groups:\n{json.dumps(evidence_groups, ensure_ascii=True)}",
        ]
    )
    content, tool_call_log = await run_advisor_tool_loop(
        llm=llm,
        system_prompt=f"{system_prompt}\n\n{json_contract}",
        user_query="\n\n".join(parts),
        state=state,
        max_rounds=4,
    )
    try:
        parsed = parse_json_object(content) or {}
        return (parsed if isinstance(parsed, dict) else {}), tool_call_log
    except Exception:
        return {}, tool_call_log


def finalize_structured_advisor(
    state: PathfinderState,
    *,
    node_name: str,
    completion_message: str,
    ranking_note: str,
    merged_payload: DecisionPayload,
    tool_call_log: list[dict[str, Any]],
    runtime: dict[str, Any],
    draft_answer: str = "",
    stop_reason: str | None = None,
    complete_rank_options_without_recommendations: bool = True,
) -> PathfinderState:
    """Apply common finalization logic for structured advisor nodes."""
    merged_payload = _normalize_decision_payload(merged_payload)
    working_memory = runtime["working_memory"]
    task_graph = runtime["task_graph"]
    blocked_reasons = list(runtime["blocked_reasons"])
    step_progress = list(runtime["step_progress"])

    for assumption in merged_payload.get("assumptions", []):
        working_memory = add_working_memory_item(working_memory, "active_assumptions", assumption)
    for item in merged_payload.get("blocked_or_uncertain_items", []):
        if item.get("kind") in {"blocked", "needs_verification"}:
            blocked_reasons.append(item.get("reason", ""))
            working_memory = add_working_memory_item(working_memory, "planner_blockers", item.get("reason", ""))

    working_memory = add_working_memory_item(working_memory, "ranking_rationale", ranking_note)
    task_graph = complete_task(task_graph, "compare_to_student_state")
    if blocked_reasons:
        task_graph = complete_task(task_graph, "check_blockers")
    if complete_rank_options_without_recommendations or merged_payload.get("recommended_items"):
        task_graph = complete_task(task_graph, "rank_options")
    working_memory = add_handoff_note(
        working_memory,
        from_node=node_name,
        to_node="evaluator",
        contract="decision_payload",
        summary=(
            f"recommended={len(merged_payload.get('recommended_items', []))}; "
            f"blocked={len(merged_payload.get('blocked_or_uncertain_items', []))}"
        ),
    )
    step_progress.append(completion_message)

    return {
        **state,
        "decision_payload": merged_payload,
        "draft_answer": draft_answer,
        "tool_call_log": tool_call_log,
        "working_memory": working_memory,
        "task_graph": task_graph,
        "blocked_reasons": [reason for reason in blocked_reasons if reason],
        "stop_reason": state.get("stop_reason", "") or (stop_reason if stop_reason is not None else ("partial_answer" if blocked_reasons else "")),
        "step_progress": step_progress,
        "next_node": "evaluator",
    }


def _normalize_decision_payload(payload: DecisionPayload) -> DecisionPayload:
    normalized = dict(payload) if isinstance(payload, dict) else {}
    normalized["answer_outline"] = _normalize_string_list(normalized.get("answer_outline", []))
    normalized["assumptions"] = _normalize_string_list(normalized.get("assumptions", []))
    normalized["blocked_reasons"] = _normalize_string_list(normalized.get("blocked_reasons", []))
    normalized["recommended_items"] = _normalize_item_list(
        normalized.get("recommended_items", []),
        default_kind="recommended",
    )
    normalized["blocked_or_uncertain_items"] = _normalize_item_list(
        normalized.get("blocked_or_uncertain_items", []),
        default_kind="needs_verification",
    )
    normalized["source_refs"] = _normalize_source_refs(normalized.get("source_refs", []))
    normalized["recommendation_paths"] = _normalize_item_list(
        normalized.get("recommendation_paths", []),
        default_kind="path",
    )
    if not isinstance(normalized.get("student_strategy", {}), dict):
        normalized["student_strategy"] = {}
    return normalized


def _normalize_string_list(values: Any) -> list[str]:
    result: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text:
            result.append(text)
    return result


def _normalize_item_list(values: Any, *, default_kind: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for value in values or []:
        if isinstance(value, dict):
            item = dict(value)
            if default_kind == "recommended":
                item.setdefault("label", str(item.get("label", "") or item.get("reason", "") or "Recommendation").strip())
                item.setdefault("reason", str(item.get("reason", "") or item.get("label", "") or "").strip())
                item.setdefault("status", str(item.get("status", "") or "recommended").strip())
                item.setdefault("support_codes", item.get("support_codes", []) if isinstance(item.get("support_codes", []), list) else [])
                item.setdefault("support_refs", item.get("support_refs", []) if isinstance(item.get("support_refs", []), list) else [])
                item.setdefault("assumption", str(item.get("assumption", "") or "").strip())
            elif default_kind == "needs_verification":
                item.setdefault("label", str(item.get("label", "") or item.get("reason", "") or "Open question").strip())
                item.setdefault("reason", str(item.get("reason", "") or item.get("label", "") or "").strip())
                item.setdefault("kind", str(item.get("kind", "") or "needs_verification").strip())
            else:
                item.setdefault("label", str(item.get("label", "") or item.get("reason", "") or "Path").strip())
                item.setdefault("reason", str(item.get("reason", "") or item.get("label", "") or "").strip())
            normalized.append(item)
            continue

        text = str(value or "").strip()
        if not text:
            continue
        if default_kind == "recommended":
            normalized.append({
                "label": text,
                "reason": text,
                "status": "recommended",
                "support_codes": [],
                "support_refs": [],
                "assumption": "",
            })
        elif default_kind == "needs_verification":
            normalized.append({
                "label": text,
                "reason": text,
                "kind": "needs_verification",
            })
        else:
            normalized.append({
                "label": text,
                "reason": text,
            })
    return normalized


def _normalize_source_refs(values: Any) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for value in values or []:
        if isinstance(value, dict):
            refs.append({
                "title": str(value.get("title", "") or "").strip(),
                "url": str(value.get("url", "") or "").strip(),
                "excerpt": str(value.get("excerpt", "") or "").strip(),
                "source_type": str(value.get("source_type", "") or "").strip(),
                "entity_type": str(value.get("entity_type", "") or "").strip(),
            })
        else:
            text = str(value or "").strip()
            if text:
                refs.append({"title": text, "url": "", "excerpt": "", "source_type": "", "entity_type": ""})
    return refs
