"""Event-driven and periodic memory consolidation hooks."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.adapters.neo4j.graph_store import get_student, run_cypher
from app.services.conflict_semantics import (
    are_semantic_duplicates,
    normalize_fact_value,
    normalize_text,
    split_conflict_groups,
)

log = logging.getLogger("pathfinder.consolidation")

_STRICT_CONFLICT_TYPES = {"preference", "constraint"}
_MULTI_VALUE_TYPES = {"skill", "interest", "goal", "course", "experience", "project", "generic"}


def _expand_compound_parts(value: str | None) -> list[str]:
    text = (value or "").strip()
    if not text or len(text) > 80:
        return []
    normalized = re.sub(r"\s+(and|&)\s+", ",", text, flags=re.IGNORECASE)
    parts = [part.strip(" .") for part in normalized.split(",")]
    cleaned = []
    seen = set()
    for part in parts:
        key = normalize_text(part)
        if part and key and key not in seen:
            cleaned.append(part)
            seen.add(key)
    return cleaned


async def _fetch_candidate_facts(student_id: str) -> list[dict[str, Any]]:
    rows = await run_cypher(
        """
        MATCH (s:Student {id: $sid})-[:HAS_CANDIDATE_FACT]->(c:CandidateFact)
        WHERE coalesce(c.status, 'candidate') <> 'archived'
        RETURN c {.*} AS fact
        """,
        {"sid": student_id},
    )
    return [row.get("fact", {}) for row in rows if row.get("fact")]


async def _update_statuses(ids: list[str], status: str, *, nudge_state: str | None = None) -> int:
    if not ids:
        return 0
    set_clause = "c.status = $status, c.updated_at = datetime()"
    if nudge_state is not None:
        set_clause += ", c.nudge_state = $nudge_state"
    rows = await run_cypher(
        f"""
        MATCH (c:CandidateFact)
        WHERE c.id IN $ids
        SET {set_clause}
        RETURN count(c) AS count
        """,
        {"ids": ids, "status": status, "nudge_state": nudge_state},
    )
    return int(rows[0]["count"]) if rows else 0


async def maybe_consolidate_memory(student_id: str, reason: str) -> dict[str, Any]:
    """Run a bounded consolidation pass that self-resolves noisy overlaps first."""
    promoted = await run_cypher(
        """
        MATCH (s:Student {id: $sid})-[:HAS_CANDIDATE_FACT]->(c:CandidateFact)
        WHERE c.status = 'candidate' AND coalesce(c.confidence, 0) >= 0.85 AND coalesce(c.salience, 0) >= 0.75
        SET c.status = 'resolved', c.last_reinforced_at = datetime()
        RETURN count(c) AS promoted
        """,
        {"sid": student_id},
    )
    archived = await run_cypher(
        """
        MATCH (s:Student {id: $sid})-[:HAS_MEMORY]->(m:MemoryItem)
        WHERE m.status = 'candidate' AND coalesce(m.confidence, 0) < 0.35 AND coalesce(m.salience, 0) < 0.35
        SET m.status = 'archived'
        RETURN count(m) AS archived
        """,
        {"sid": student_id},
    )

    student = await get_student(student_id) or {}
    facts = await _fetch_candidate_facts(student_id)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for fact in facts:
        fact_type = str(fact.get("fact_type") or "generic").lower()
        grouped.setdefault(fact_type, []).append(fact)

    supersede_ids: set[str] = set()
    restore_resolved_ids: set[str] = set()
    restore_candidate_ids: set[str] = set()
    conflict_ids: set[str] = set()

    for fact_type, items in grouped.items():
        active_items = [item for item in items if item.get("id")]
        if not active_items:
            continue

        if fact_type == "identity" and any(student.get(key) for key in ("name", "university", "program", "semester", "gpa", "email")):
            supersede_ids.update(str(item["id"]) for item in active_items)
            continue

        if fact_type in {"skill", "interest"}:
            atomic = {
                normalize_fact_value(fact_type, item.get("value"))
                for item in active_items
                if len(_expand_compound_parts(item.get("value"))) <= 1
            }
            for item in active_items:
                parts = _expand_compound_parts(item.get("value"))
                if len(parts) > 1:
                    part_keys = {normalize_fact_value(fact_type, part) for part in parts}
                    if part_keys and part_keys.issubset(atomic):
                        supersede_ids.add(str(item["id"]))
            for item in active_items:
                item_id = str(item["id"])
                if item_id in supersede_ids:
                    continue
                confidence = float(item.get("confidence", 0.0) or 0.0)
                (restore_resolved_ids if confidence >= 0.65 else restore_candidate_ids).add(item_id)
            continue

        if fact_type == "goal":
            ranked = sorted(
                active_items,
                key=lambda item: (
                    len(normalize_fact_value(fact_type, item.get("value"))),
                    float(item.get("confidence", 0.0) or 0.0),
                ),
                reverse=True,
            )
            kept_values: list[str] = []
            for item in ranked:
                item_id = str(item["id"])
                normalized = normalize_fact_value(fact_type, item.get("value"))
                if not normalized:
                    supersede_ids.add(item_id)
                    continue
                if any(
                    normalized == kept
                    or normalized in kept
                    or are_semantic_duplicates(fact_type, normalized, kept)
                    for kept in kept_values
                ):
                    supersede_ids.add(item_id)
                    continue
                kept_values.append(normalized)
                confidence = float(item.get("confidence", 0.0) or 0.0)
                (restore_resolved_ids if confidence >= 0.65 else restore_candidate_ids).add(item_id)
            continue

        if fact_type not in _STRICT_CONFLICT_TYPES:
            for item in active_items:
                item_id = str(item["id"])
                confidence = float(item.get("confidence", 0.0) or 0.0)
                (restore_resolved_ids if confidence >= 0.65 else restore_candidate_ids).add(item_id)
            continue

        conflict_groups, compatible_items = split_conflict_groups(fact_type, active_items)
        for group in conflict_groups:
            conflict_ids.update(str(item["id"]) for item in group if item.get("id"))
        for item in compatible_items:
            item_id = str(item["id"])
            confidence = float(item.get("confidence", 0.0) or 0.0)
            (restore_resolved_ids if confidence >= 0.65 else restore_candidate_ids).add(item_id)

    restore_resolved_ids -= supersede_ids
    restore_candidate_ids -= supersede_ids
    restore_resolved_ids -= conflict_ids
    restore_candidate_ids -= conflict_ids

    superseded = await _update_statuses(sorted(supersede_ids), "superseded", nudge_state="acknowledged")
    restored_resolved = await _update_statuses(sorted(restore_resolved_ids), "resolved")
    restored_candidate = await _update_statuses(sorted(restore_candidate_ids), "candidate")
    conflicted = await _update_statuses(sorted(conflict_ids), "conflicted")

    merged_duplicates = await run_cypher(
        """
        MATCH (s:Student {id: $sid})-[:HAS_MEMORY]->(m1:MemoryItem),
              (s)-[:HAS_MEMORY]->(m2:MemoryItem)
        WHERE m1.id < m2.id
          AND m1.memory_type = m2.memory_type
          AND toLower(trim(coalesce(m1.summary, ''))) = toLower(trim(coalesce(m2.summary, '')))
          AND coalesce(m2.status, 'candidate') <> 'archived'
        SET m2.status = 'superseded', m1.last_reinforced_at = datetime()
        RETURN count(m2) AS merged
        """,
        {"sid": student_id},
    )
    stale_demoted = await run_cypher(
        """
        MATCH (s:Student {id: $sid})-[:HAS_CANDIDATE_FACT]->(c:CandidateFact)
        WHERE c.status = 'resolved'
          AND c.last_used_at IS NOT NULL
          AND datetime(c.last_used_at) < datetime() - duration('P180D')
          AND coalesce(c.confidence, 0) < 0.7
        SET c.status = 'candidate'
        RETURN count(c) AS demoted
        """,
        {"sid": student_id},
    )
    result = {
        "reason": reason,
        "promoted": promoted[0]["promoted"] if promoted else 0,
        "archived": archived[0]["archived"] if archived else 0,
        "conflicted": conflicted,
        "merged": (merged_duplicates[0]["merged"] if merged_duplicates else 0) + superseded,
        "demoted": stale_demoted[0]["demoted"] if stale_demoted else 0,
        "restored": restored_resolved + restored_candidate,
    }
    log.info("Consolidation for %s after %s: %s", student_id, reason, result)
    return result
