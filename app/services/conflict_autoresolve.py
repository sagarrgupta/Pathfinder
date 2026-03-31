"""Conservative conflict self-resolution helpers."""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.adapters.llm.lmstudio import get_text_llm
from app.adapters.neo4j.graph_store import apply_conflict_choice, get_student
from app.agents.conflict_resolution_agent import build_conflict_nudges
from app.services.consolidation import maybe_consolidate_memory
from app.adapters.neo4j.graph_store import get_full_profile

log = logging.getLogger("pathfinder.conflict.autoresolve")

_AUTO_RESOLVE_PROMPT = """You are deciding whether Pathfinder can safely self-resolve a profile conflict.

Rules:
- Only choose a value if one option is clearly a richer, more complete, or more canonical version of the same meaning.
- Do NOT choose when the options represent different user intent, different goals, or different preferences.
- Prefer "unresolved" whenever there is any ambiguity.
- Return ONLY valid JSON:
  {"decision":"choose_value|unresolved","selected_value":"", "reason":"brief reason"}
"""


def _choose_options(conflict: dict[str, Any]) -> list[str]:
    return [
        option.get("value", "").strip()
        for option in conflict.get("options", [])
        if option.get("action") == "choose_value" and (option.get("value") or "").strip()
    ]


async def _llm_autoresolve_choice(conflict: dict[str, Any]) -> dict[str, Any] | None:
    options = _choose_options(conflict)
    if len(options) < 2:
        return None
    llm = get_text_llm()
    response = await llm.ainvoke(
        [
            SystemMessage(content=_AUTO_RESOLVE_PROMPT),
            HumanMessage(
                content=json.dumps(
                    {
                        "fact_type": conflict.get("fact_type"),
                        "question": conflict.get("question"),
                        "current_option": conflict.get("current_option"),
                        "other_options": conflict.get("other_options", []),
                        "chooseable_options": options,
                    }
                )
            ),
        ]
    )
    content = response.content if isinstance(response.content, str) else str(response.content)
    try:
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(content[start:end])
            if data.get("decision") == "choose_value" and str(data.get("selected_value", "")).strip() in options:
                return {
                    "action": "choose_value",
                    "selected_value": str(data.get("selected_value", "")).strip(),
                    "reason": str(data.get("reason", "")).strip(),
                }
    except Exception as exc:
        log.warning("Conflict self-resolve parse failed: %s", exc)
    return None


async def list_profile_conflicts(student_id: str) -> list[dict[str, Any]]:
    """Return grouped unresolved conflicts for the profile screen."""
    await maybe_consolidate_memory(student_id, "profile_conflicts")
    student = await get_student(student_id)
    if not student:
        return []
    profile = await get_full_profile(student_id)
    candidate_facts = profile.get("candidate_facts", [])
    raw_conflicts = []
    for item in candidate_facts:
        if item.get("status") != "conflicted":
            continue
        fact_type = str(item.get("fact_type") or "").strip()
        value = str(item.get("value") or "").strip()
        if not fact_type or not value:
            continue
        raw_conflicts.append(
            {
                "id": item.get("id"),
                "fact_type": fact_type,
                "value": value,
                "confidence": float(item.get("confidence", 0.0) or 0.0),
                "nudge_count": int(item.get("nudge_count", 0) or 0),
                "nudge_state": item.get("nudge_state"),
                "nudge_until": item.get("nudge_until"),
                "conflict_kind": "explicit",
            }
        )
    return build_conflict_nudges(raw_conflicts, only_nudgeable=False)


async def auto_resolve_profile_conflicts(student_id: str) -> dict[str, Any]:
    """Attempt safe self-resolution for remaining profile conflicts."""
    conflicts = await list_profile_conflicts(student_id)
    resolved: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    used_llm = False

    for conflict in conflicts:
        llm_choice = await _llm_autoresolve_choice(conflict)
        if not llm_choice:
            unresolved.append(
                {
                    "id": conflict.get("id"),
                    "fact_type": conflict.get("fact_type"),
                    "question": conflict.get("summary", {}).get("question") or conflict.get("question"),
                    "current_option": conflict.get("summary", {}).get("current_option") or conflict.get("current_option"),
                    "other_options": conflict.get("summary", {}).get("other_options") or conflict.get("other_options", []),
                }
            )
            continue

        used_llm = True
        await apply_conflict_choice(
            student_id=student_id,
            conflict_id=conflict.get("id", ""),
            fact_type=conflict.get("fact_type", ""),
            action="choose_value",
            selected_value=llm_choice["selected_value"],
        )
        resolved.append(
            {
                "id": conflict.get("id"),
                "fact_type": conflict.get("fact_type"),
                "selected_value": llm_choice["selected_value"],
                "reason": llm_choice.get("reason", ""),
            }
        )

    await maybe_consolidate_memory(student_id, "profile_self_resolve")
    remaining = await list_profile_conflicts(student_id)
    return {
        "student_id": student_id,
        "resolved_count": len(resolved),
        "unresolved_count": len(remaining),
        "used_llm": used_llm,
        "resolved": resolved,
        "unresolved": [
            {
                "id": item.get("id"),
                "fact_type": item.get("fact_type"),
                "question": item.get("summary", {}).get("question"),
                "current_option": item.get("summary", {}).get("current_option"),
                "other_options": item.get("summary", {}).get("other_options", []),
            }
            for item in remaining
        ],
    }
