"""Event-driven and periodic memory consolidation hooks."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.adapters.neo4j.graph_store import get_student, run_cypher
from app.services.conflict_semantics import are_semantic_duplicates, normalize_fact_value, split_conflict_groups

log = logging.getLogger("pathfinder.consolidation")

_STRICT_CONFLICT_TYPES = {"preference", "constraint"}


def _parse_datetimeish(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _freshness_score(item: dict[str, object]) -> float:
    updated = _parse_datetimeish(item.get("updated_at") or item.get("created_at"))
    if updated is None:
        return 0.0
    age_days = max(0.0, (datetime.now(timezone.utc) - updated).total_seconds() / 86400.0)
    if age_days <= 14:
        return 0.35
    if age_days <= 45:
        return 0.2
    if age_days <= 120:
        return 0.08
    return -0.08


def _rank_candidate(item: dict[str, object]) -> tuple[float, float, float, str]:
    confidence = float(item.get("confidence", 0.0) or 0.0)
    direct_support = 0.08 if int(item.get("direct_statement_count") or 0) > 0 else 0.0
    freshness = _freshness_score(item)
    timestamp = str(item.get("updated_at") or item.get("created_at") or "")
    score = confidence + direct_support + freshness
    return (score, confidence, freshness, timestamp)


async def _fetch_candidate_facts(student_id: str) -> list[dict[str, object]]:
    rows = await run_cypher(
        """
        MATCH (s:Student {id: $sid})-[:HAS_CANDIDATE_FACT]->(c:CandidateFact)
        WHERE coalesce(c.status, 'candidate') <> 'archived'
        RETURN c {.*} AS fact
        """,
        {"sid": student_id},
    )
    return [row.get("fact", {}) for row in rows if row.get("fact")]


async def _update_statuses(ids: list[str], status: str) -> int:
    if not ids:
        return 0
    rows = await run_cypher(
        """
        MATCH (c:CandidateFact)
        WHERE c.id IN $ids
        SET c.status = $status, c.updated_at = datetime()
        RETURN count(c) AS count
        """,
        {"ids": ids, "status": status},
    )
    return int(rows[0]["count"]) if rows else 0


async def maybe_consolidate_memory(student_id: str, reason: str) -> dict[str, int | str]:
    """Run a bounded consolidation pass over candidate facts and memories."""
    promoted = await run_cypher(
        """
        MATCH (s:Student {id: $sid})-[:HAS_CANDIDATE_FACT]->(c:CandidateFact)
        WHERE c.status = 'candidate'
          AND (
            coalesce(c.promotion_score, 0) >= 0.78
            OR (
              coalesce(c.support_count, 1) >= 2
              AND (
                coalesce(c.direct_statement_count, 0) > 0
                OR coalesce(c.document_support_count, 0) > 0
              )
              AND coalesce(c.confidence, 0) >= 0.7
            )
          )
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
    grouped: dict[str, list[dict[str, object]]] = {}
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
        if fact_type == "goal":
            ranked = sorted(
                active_items,
                key=lambda item: (
                    len(normalize_fact_value(fact_type, str(item.get("value")))),
                    *_rank_candidate(item),
                ),
                reverse=True,
            )
            kept_values: list[str] = []
            for item in ranked:
                item_id = str(item["id"])
                normalized = normalize_fact_value(fact_type, str(item.get("value")))
                if not normalized:
                    supersede_ids.add(item_id)
                    continue
                if any(
                    normalized == kept or normalized in kept or are_semantic_duplicates(fact_type, normalized, kept)
                    for kept in kept_values
                ):
                    supersede_ids.add(item_id)
                    continue
                kept_values.append(normalized)
                confidence = float(item.get("confidence", 0.0) or 0.0) + _freshness_score(item)
                (restore_resolved_ids if confidence >= 0.65 else restore_candidate_ids).add(item_id)
            continue
        if fact_type not in _STRICT_CONFLICT_TYPES:
            for item in active_items:
                item_id = str(item["id"])
                confidence = float(item.get("confidence", 0.0) or 0.0) + _freshness_score(item)
                (restore_resolved_ids if confidence >= 0.65 else restore_candidate_ids).add(item_id)
            continue

        conflict_groups, compatible_items = split_conflict_groups(fact_type, active_items)
        for group in conflict_groups:
            conflict_ids.update(str(item["id"]) for item in group if item.get("id"))
        for item in compatible_items:
            item_id = str(item["id"])
            confidence = float(item.get("confidence", 0.0) or 0.0) + _freshness_score(item)
            (restore_resolved_ids if confidence >= 0.65 else restore_candidate_ids).add(item_id)

    restore_resolved_ids -= supersede_ids
    restore_candidate_ids -= supersede_ids
    restore_resolved_ids -= conflict_ids
    restore_candidate_ids -= conflict_ids

    superseded = await _update_statuses(sorted(supersede_ids), "superseded")
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
    result = {
        "reason": reason,
        "promoted": promoted[0]["promoted"] if promoted else 0,
        "archived": archived[0]["archived"] if archived else 0,
        "conflicted": conflicted,
        "merged": (merged_duplicates[0]["merged"] if merged_duplicates else 0) + superseded,
        "restored": restored_resolved + restored_candidate,
    }
    log.info("Consolidation for %s after %s: %s", student_id, reason, result)
    return result


async def list_profile_conflicts(student_id: str) -> list[dict[str, object]]:
    """Return unresolved memory conflicts for the profile screen."""
    await maybe_consolidate_memory(student_id, "profile_conflicts")
    facts = await _fetch_candidate_facts(student_id)
    grouped: dict[str, list[dict[str, object]]] = {}
    for item in facts:
        if item.get("status") != "conflicted":
            continue
        fact_type = str(item.get("fact_type") or "").strip()
        if fact_type:
            grouped.setdefault(fact_type, []).append(item)

    conflicts: list[dict[str, object]] = []
    for fact_type, items in grouped.items():
        groups, _ = split_conflict_groups(fact_type, items)
        for group in groups:
            ranked = sorted(group, key=_rank_candidate, reverse=True)
            top = ranked[0]
            conflicts.append({
                "id": str(top.get("id") or ""),
                "fact_type": fact_type,
                "current_option": str(top.get("value") or ""),
                "other_options": [str(item.get("value") or "") for item in ranked[1:3] if str(item.get("value") or "").strip()],
                "question": f"Which {fact_type} should Pathfinder trust going forward?",
                "confidence": float(top.get("confidence", 0.0) or 0.0),
                "updated_at": str(top.get("updated_at") or top.get("created_at") or ""),
            })
    return conflicts


async def auto_resolve_profile_conflicts(student_id: str, limit: int = 20) -> dict[str, object]:
    """Resolve obvious profile conflicts by keeping the strongest option per group.

    Strategy:
    - For each conflicted group, keep the highest-confidence item as ``resolved``.
    - Mark remaining options in that group as ``superseded``.
    - Return a compact summary for UI feedback.
    """
    await maybe_consolidate_memory(student_id, "profile_conflicts_self_resolve")
    facts = await _fetch_candidate_facts(student_id)

    grouped: dict[str, list[dict[str, object]]] = {}
    for item in facts:
        if item.get("status") != "conflicted":
            continue
        fact_type = str(item.get("fact_type") or "").strip()
        if fact_type:
            grouped.setdefault(fact_type, []).append(item)

    keep_ids: set[str] = set()
    suppress_ids: set[str] = set()
    decisions: list[dict[str, object]] = []

    for fact_type, items in grouped.items():
        groups, _ = split_conflict_groups(fact_type, items)
        for group in groups[:limit]:
            ranked = sorted(group, key=_rank_candidate, reverse=True)
            if not ranked:
                continue
            winner = ranked[0]
            winner_id = str(winner.get("id") or "")
            if winner_id:
                keep_ids.add(winner_id)
            loser_values: list[str] = []
            for loser in ranked[1:]:
                loser_id = str(loser.get("id") or "")
                if loser_id:
                    suppress_ids.add(loser_id)
                value = str(loser.get("value") or "").strip()
                if value:
                    loser_values.append(value)
            decisions.append(
                {
                    "fact_type": fact_type,
                    "chosen": str(winner.get("value") or ""),
                    "suppressed": loser_values,
                    "confidence": float(winner.get("confidence", 0.0) or 0.0),
                }
            )

    resolved_count = await _update_statuses(sorted(keep_ids), "resolved")
    superseded_count = await _update_statuses(sorted(suppress_ids), "superseded")

    return {
        "resolved": resolved_count,
        "superseded": superseded_count,
        "decisions": decisions,
    }
