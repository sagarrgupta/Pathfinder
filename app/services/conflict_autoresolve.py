"""Conservative conflict helpers for profile-memory resolution."""

from __future__ import annotations

from typing import Any

from app.adapters.neo4j.graph_store import apply_conflict_choice
from app.services.consolidation import (
    auto_resolve_profile_conflicts as _auto_resolve_consolidation,
    list_profile_conflicts as _list_conflicts_consolidation,
    maybe_consolidate_memory,
)


def _build_options(current_option: str, other_options: list[str]) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    if current_option:
        options.append({"label": f"Keep: {current_option}", "action": "choose_value", "value": current_option})
    for option in other_options:
        if option and option != current_option:
            options.append({"label": f"Use: {option}", "action": "choose_value", "value": option})
    options.append({"label": "Leave unresolved for now", "action": "unresolved", "value": None})
    return options


async def list_profile_conflicts(student_id: str) -> list[dict[str, Any]]:
    """Return unresolved profile conflicts in UI-friendly shape."""
    raw = await _list_conflicts_consolidation(student_id)
    enriched: list[dict[str, Any]] = []
    for item in raw:
        current = str(item.get("current_option") or "").strip()
        others = [str(option).strip() for option in (item.get("other_options") or []) if str(option).strip()]
        fact_type = str(item.get("fact_type") or "conflict")
        question = str(item.get("question") or f"Which {fact_type} should Pathfinder trust?")
        enriched.append(
            {
                "id": str(item.get("id") or ""),
                "fact_type": fact_type,
                "question": question,
                "message": "Choose what Pathfinder should treat as your current preference/fact.",
                "current_option": current,
                "other_options": others,
                "confidence": float(item.get("confidence", 0.0) or 0.0),
                "options": _build_options(current, others),
                "summary": {
                    "question": question,
                    "current_option": current,
                    "other_options": others,
                },
            }
        )
    return enriched


async def resolve_conflict_choice(
    *,
    student_id: str,
    conflict_id: str,
    fact_type: str,
    action: str,
    selected_value: str | None = None,
) -> dict[str, Any]:
    """Apply a user-provided conflict choice and refresh conflict view."""
    result = await apply_conflict_choice(
        student_id=student_id,
        conflict_id=conflict_id,
        fact_type=fact_type,
        action=action,
        selected_value=selected_value,
    )
    await maybe_consolidate_memory(student_id, "profile_conflict_choice")
    remaining = await list_profile_conflicts(student_id)
    return {
        "student_id": student_id,
        "applied": result,
        "remaining_conflicts": len(remaining),
    }


async def auto_resolve_profile_conflicts(student_id: str) -> dict[str, Any]:
    """Run conservative auto-resolution and return summary."""
    result = await _auto_resolve_consolidation(student_id)
    remaining = await list_profile_conflicts(student_id)
    return {
        "student_id": student_id,
        "resolved_count": int(result.get("resolved", 0) or 0),
        "superseded_count": int(result.get("superseded", 0) or 0),
        "remaining_conflicts": len(remaining),
        "decisions": result.get("decisions", []),
    }
