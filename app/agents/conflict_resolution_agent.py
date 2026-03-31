"""Capability agent: conflict detection, suppression, and soft nudges."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.adapters.neo4j.graph_store import mark_memory_nudged
from app.core.state import PathfinderState
from app.services.conflict_semantics import split_conflict_groups


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _needs_nudge(conflict: dict) -> bool:
    nudge_state = conflict.get("nudge_state")
    if nudge_state in {"acknowledged", "resolved"}:
        return False
    nudge_until = _parse_datetime(conflict.get("nudge_until"))
    if nudge_until and nudge_until > datetime.now(timezone.utc):
        return False
    if nudge_state != "snoozed" and int(conflict.get("nudge_count", 0) or 0) > 0:
        return False
    confidence = float(conflict.get("confidence", 0.0))
    kind = conflict.get("conflict_kind", "explicit")
    if kind == "explicit":
        return confidence >= 0.45
    return confidence >= 0.55


def _build_nudge(conflict: dict) -> dict:
    value = conflict.get("value") or conflict.get("summary") or "conflicting information"
    fact_type = conflict.get("fact_type", "profile detail")
    alternatives = conflict.get("alternatives", [])
    readable_fact_type = fact_type.replace("_", " ")
    if alternatives:
        message = (
            f"I found more than one possible current {readable_fact_type} for your profile. "
            f"Please choose which option Pathfinder should treat as current."
        )
    else:
        message = (
            f"I found a possible conflict in your {readable_fact_type}. "
            "Please confirm whether this should be treated as current, kept as an alternate, or revisited later."
        )
    options = [
        {"action": "choose_value", "value": value, "label": f"Use {value} as my current {readable_fact_type}"},
        *[
            {"action": "choose_value", "value": alt, "label": f"Use {alt} as my current {readable_fact_type}"}
            for alt in alternatives
            if alt and alt != value
        ],
        {"action": "keep_both", "label": "Keep both for now"},
        {"action": "ask_later", "label": "Ask me later"},
    ]
    return {
        "id": conflict.get("id"),
        "fact_type": fact_type,
        "value": value,
        "confidence": float(conflict.get("confidence", 0.0) or 0.0),
        "message": message,
        "alternatives": alternatives,
        "summary": {
            "current_option": value,
            "other_options": alternatives,
            "question": f"Which {readable_fact_type} should Pathfinder use going forward?",
        },
        "options": options,
    }


def build_conflict_nudges(
    conflicts: list[dict[str, Any]],
    *,
    only_nudgeable: bool = True,
) -> list[dict[str, Any]]:
    eligible = [conflict for conflict in conflicts if not only_nudgeable or _needs_nudge(conflict)]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for conflict in eligible:
        fact_type = str(conflict.get("fact_type") or "profile detail")
        grouped.setdefault(fact_type, []).append(conflict)

    nudges: list[dict[str, Any]] = []
    for fact_type, items in grouped.items():
        conflict_groups, _ = split_conflict_groups(fact_type, items)
        for group_items in conflict_groups:
            ranked = sorted(
                group_items,
                key=lambda item: (
                    float(item.get("confidence", 0.0) or 0.0),
                    len(str(item.get("value") or item.get("summary") or "")),
                ),
                reverse=True,
            )
            primary = ranked[0]
            alternatives = [str(item.get("value") or item.get("summary") or "").strip() for item in ranked[1:] if str(item.get("value") or item.get("summary") or "").strip()]
            filtered_alternatives: list[str] = []
            for alt in sorted(alternatives, key=len, reverse=True):
                if alt and alt != str(primary.get("value") or primary.get("summary") or "").strip() and not any(alt != kept and alt in kept for kept in filtered_alternatives):
                    filtered_alternatives.append(alt)
            nudges.append(
                _build_nudge(
                    {
                        "id": primary.get("id"),
                        "fact_type": fact_type,
                        "value": primary.get("value") or primary.get("summary") or "",
                        "confidence": float(primary.get("confidence", 0.0) or 0.0),
                        "alternatives": filtered_alternatives,
                    }
                )
            )
    return nudges


async def conflict_resolution_agent(state: PathfinderState) -> PathfinderState:
    """Resolve answer-impacting conflicts conservatively and nudge once when needed."""
    conflicts = list(state.get("conflicts", []))
    if not conflicts:
        return {**state, "conflict_nudges": []}

    high_impact = []
    nudgeable_conflicts = []
    for conflict in conflicts[:5]:
        confidence = float(conflict.get("confidence", 0.0))
        if confidence >= 0.5 or conflict.get("conflict_kind") == "explicit":
            high_impact.append(conflict)
        if _needs_nudge(conflict):
            nudgeable_conflicts.append(conflict)
            label = "CandidateFact" if conflict.get("value") else "MemoryItem"
            memory_id = conflict.get("id")
            if memory_id:
                await mark_memory_nudged(label, memory_id)
    nudges = build_conflict_nudges(nudgeable_conflicts, only_nudgeable=True)

    rationale = list(state.get("answer_rationale", []))
    if high_impact:
        rationale.append(f"Detected {len(high_impact)} relevant conflicting memories")
    if nudges:
        rationale.append(f"Prepared {len(nudges)} one-time conflict nudges")

    step_progress = list(state.get("step_progress", []))
    step_progress.append(
        "Checked conflicting memories"
        + (f" ({len(high_impact)} relevant, {len(nudges)} nudged)" if high_impact or nudges else "")
    )

    execution_trace = list(state.get("execution_trace", []))
    execution_trace.append(
        {
            "agent": "conflict_resolution_agent",
            "relevant_conflicts": len(high_impact),
            "nudges": len(nudges),
        }
    )
    return {
        **state,
        "conflicts": high_impact[:3],
        "conflict_nudges": nudges[:2],
        "answer_rationale": rationale,
        "execution_trace": execution_trace,
        "step_progress": step_progress,
    }
