"""Profile-assembly helpers for the Neo4j graph store."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from ._graph_common import metadata_dict, normalize_name, safe_float, safe_int


def fact_source_support_kind(source_type: str | None, source_ref: str | None) -> str:
    lowered_type = str(source_type or "").strip().lower()
    lowered_ref = str(source_ref or "").strip().lower()
    if any(token in lowered_type for token in ("document", "resume", "transcript", "upload", "pdf")):
        return "document"
    if lowered_ref.startswith("doc:") or lowered_ref.startswith("document:"):
        return "document"
    if lowered_type in {"profile_text", "chat_query"}:
        return "direct_input"
    return "other"


def candidate_promotion_score(
    confidence: float,
    salience: float,
    support_count: int,
    direct_statement_count: int,
    document_support_count: int,
) -> float:
    score = (confidence * 0.45) + (salience * 0.2)
    score += min(0.15, max(0, support_count - 1) * 0.06)
    if direct_statement_count > 0:
        score += 0.12
    if document_support_count > 0:
        score += 0.08
    return round(min(1.0, score), 2)


def candidate_confirmation_state(fact: dict[str, Any]) -> str:
    status = str(fact.get("status") or "candidate").lower()
    support_count = safe_int(fact.get("support_count") or 0, 0)
    direct_statement_count = safe_int(fact.get("direct_statement_count") or 0, 0)
    document_support_count = safe_int(fact.get("document_support_count") or 0, 0)
    promotion_score = safe_float(fact.get("promotion_score"), 0.0)
    if status == "resolved":
        return "confirmed"
    if promotion_score >= 0.8 or (support_count >= 2 and (direct_statement_count > 0 or document_support_count > 0)):
        return "reinforced"
    return "inferred"


def parse_datetimeish(value: Any) -> datetime | None:
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


def semantic_entity_key(label: str | None, value: str | None) -> str:
    text = normalize_name(value)
    if not text:
        return ""
    if label == "Goal":
        replacements = {
            "obtain": "get",
            "seeking": "get",
            "looking": "get",
            "want": "get",
            "wanting": "get",
            "enter": "industry",
            "entering": "industry",
            "internships": "internship",
            "jobs": "job",
            "roles": "role",
        }
        stopwords = {"to", "a", "an", "the", "and", "go", "into", "first", "for", "my"}
        tokens = []
        for token in re.findall(r"[a-z0-9]+", text):
            mapped = replacements.get(token, token)
            if mapped not in stopwords:
                tokens.append(mapped)
        return " ".join(sorted(dict.fromkeys(tokens)))
    return text


def canonical_entity_key(item: dict[str, Any], label: str | None, key_field: str = "name") -> str:
    raw = str(item.get("normalized_name") or item.get(key_field) or item.get("value") or item.get("summary") or "")
    text = semantic_entity_key(label, raw)
    if not text:
        return str(item.get("id", ""))
    if label == "Goal":
        text = re.sub(r"^(seeking|looking for|aiming for|wanting|want)\s+", "", text)
        text = re.sub(r"\binternships\b", "internship", text)
        text = re.sub(r"\bjobs\b", "job", text)
        text = re.sub(r"\broles\b", "role", text)
        text = text.rstrip(".")
    elif label == "Interest":
        text = re.sub(r"^(interested in)\s+", "", text)
        text = text.rstrip(".")
    elif label == "Preference":
        text = re.sub(r"^(prefer|prefers)\s+", "", text)
        text = text.rstrip(".")
    return text


def expand_compound_entity_values(name: str) -> list[str]:
    if not name:
        return []
    stripped = name.strip()
    if len(stripped) > 80:
        return []
    normalized = re.sub(r"\s+(and|&)\s+", ",", stripped, flags=re.IGNORECASE)
    parts = [part.strip(" .") for part in normalized.split(",")]
    return [part for part in parts if part]


def dedupe_entities(items: list[dict[str, Any]], key_field: str = "name", label: str | None = None) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for item in items:
        key = canonical_entity_key(item, label, key_field)
        current = deduped.get(key)
        if current is None:
            deduped[key] = item
            continue
        current_score = len(json.dumps(current, sort_keys=True, default=str)) + int(bool(current.get("updated_at")))
        candidate_score = len(json.dumps(item, sort_keys=True, default=str)) + int(bool(item.get("updated_at")))
        if candidate_score >= current_score:
            deduped[key] = item
    values = list(deduped.values())

    if label in {"Skill", "Interest"}:
        atomic_keys = {
            canonical_entity_key(item, label, key_field)
            for item in values
            if len(expand_compound_entity_values(str(item.get(key_field) or ""))) <= 1
        }
        filtered: list[dict[str, Any]] = []
        for item in values:
            parts = expand_compound_entity_values(str(item.get(key_field) or ""))
            if len(parts) > 1:
                part_keys = {normalize_name(part) for part in parts if part}
                if part_keys and part_keys.issubset(atomic_keys):
                    continue
            filtered.append(item)
        values = filtered

    return values


def profile_fact_from_personal(key: str, value: Any) -> dict[str, Any] | None:
    text = str(value or "").strip()
    if not text:
        return None
    return {
        "fact_type": key,
        "value": text,
        "normalized_value": text.casefold(),
        "source_kind": "student_property",
        "stability": "stable",
        "confidence": 1.0,
        "status": "resolved",
        "metadata": {"field": key},
    }


def profile_fact_from_entity(label: str, entity: dict[str, Any]) -> dict[str, Any] | None:
    value = str(entity.get("name") or entity.get("value") or "").strip()
    if not value:
        return None
    fact_type_map = {
        "Course": "course",
        "Skill": "skill",
        "Goal": "goal",
        "Interest": "interest",
        "Company": "experience",
        "Project": "project",
        "Constraint": "constraint",
        "Preference": "preference",
    }
    fact_type = fact_type_map.get(label)
    if not fact_type:
        return None
    return {
        "fact_type": fact_type,
        "value": value,
        "normalized_value": value.casefold(),
        "source_kind": "core_entity",
        "stability": "stable" if fact_type in {"skill", "course", "project", "experience"} else "evolving",
        "confidence": float(entity.get("confidence", 1.0) or 1.0),
        "status": "resolved",
        "metadata": {"label": label, "relationship": entity.get("_relationship", "")},
    }


def build_temporal_profile(
    profile_facts: list[dict[str, Any]],
    candidate_fact_ledger: list[dict[str, Any]],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=120)
    event_cutoff = now - timedelta(days=365)

    stable_facts = [fact for fact in profile_facts if str(fact.get("stability") or "").lower() == "stable"]
    evolving_facts = [fact for fact in profile_facts if str(fact.get("stability") or "").lower() == "evolving"]
    temporary_facts = [fact for fact in profile_facts if str(fact.get("stability") or "").lower() == "temporary"]
    expired_preferences: list[dict[str, Any]] = []
    recent_events: list[dict[str, Any]] = []

    stale_candidates: list[dict[str, Any]] = []
    active_candidates: list[dict[str, Any]] = []
    for item in candidate_fact_ledger:
        status = str(item.get("status") or "candidate").lower()
        fact_type = str(item.get("fact_type") or "").lower()
        stability = str(item.get("stability") or "").lower()
        updated_at = parse_datetimeish(item.get("updated_at") or item.get("created_at"))
        is_stale = status in {"superseded", "archived"} or (
            stability == "temporary"
            and updated_at is not None
            and updated_at < stale_cutoff
        )
        if stability == "temporary" and fact_type in {"preference", "constraint"} and updated_at is not None and updated_at < stale_cutoff:
            expired_preferences.append(item)
        if is_stale:
            stale_candidates.append(item)
        else:
            active_candidates.append(item)

        event_at = updated_at or parse_datetimeish(item.get("created_at"))
        if event_at is None or event_at < event_cutoff:
            continue
        event_type = "reinforced" if safe_int(item.get("support_count") or 0, 0) > 1 else "observed"
        if status in {"resolved", "superseded", "archived", "conflicted"}:
            event_type = status
        recent_events.append(
            {
                "fact_type": fact_type or "generic",
                "value": str(item.get("value", "")).strip(),
                "status": status,
                "stability": stability,
                "event_type": event_type,
                "timestamp": event_at.isoformat(),
            }
        )

    recent_events.sort(key=lambda item: str(item.get("timestamp", "")), reverse=True)
    return {
        "stable_facts": stable_facts,
        "evolving_facts": evolving_facts,
        "temporary_facts": temporary_facts,
        "active_candidates": active_candidates,
        "stale_candidates": stale_candidates,
        "expired_preferences": expired_preferences,
        "recent_events": recent_events[:12],
        "summary": {
            "stable_count": len(stable_facts),
            "evolving_count": len(evolving_facts),
            "temporary_count": len(temporary_facts),
            "active_candidate_count": len(active_candidates),
            "stale_candidate_count": len(stale_candidates),
            "expired_preference_count": len(expired_preferences),
            "recent_event_count": min(len(recent_events), 12),
        },
    }


def profile_completeness_breakdown(
    student: dict[str, Any],
    entities_by_label: dict[str, list[dict[str, Any]]],
    candidate_fact_ledger: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    confirmed_or_reinforced = [
        item
        for item in candidate_fact_ledger
        if item.get("confirmation_state") in {"confirmed", "reinforced"}
    ]
    by_type: dict[str, list[dict[str, Any]]] = {}
    for fact in confirmed_or_reinforced:
        by_type.setdefault(str(fact.get("fact_type") or "generic").lower(), []).append(fact)
    categories = {
        "identity": [bool(student.get("name")), bool(student.get("email")), bool(student.get("university"))],
        "academics": [bool(student.get("program")), bool(student.get("semester")), bool(student.get("gpa")), bool(entities_by_label.get("Course"))],
        "goals": [bool(entities_by_label.get("Goal")), bool(by_type.get("goal"))],
        "skills": [bool(entities_by_label.get("Skill")), bool(by_type.get("skill"))],
        "experience": [bool(entities_by_label.get("Company")), bool(entities_by_label.get("Project")), bool(entities_by_label.get("Document"))],
        "preferences": [bool(entities_by_label.get("Preference")), bool(entities_by_label.get("Constraint")), bool(by_type.get("preference")), bool(by_type.get("constraint"))],
    }
    breakdown: dict[str, dict[str, Any]] = {}
    for category, checks in categories.items():
        total = len(checks)
        score = round(sum(1 for item in checks if item) / total, 2) if total else 0.0
        breakdown[category] = {"score": score, "covered": sum(1 for item in checks if item), "total": total}
    return breakdown


def profile_fact_summary(
    profile_facts: list[dict[str, Any]],
    candidate_fact_ledger: list[dict[str, Any]],
) -> dict[str, Any]:
    confirmed = sum(1 for item in candidate_fact_ledger if item.get("confirmation_state") == "confirmed")
    reinforced = sum(1 for item in candidate_fact_ledger if item.get("confirmation_state") == "reinforced")
    inferred = sum(1 for item in candidate_fact_ledger if item.get("confirmation_state") == "inferred")
    direct = sum(1 for item in candidate_fact_ledger if safe_int(item.get("direct_statement_count") or 0, 0) > 0)
    document_backed = sum(1 for item in candidate_fact_ledger if safe_int(item.get("document_support_count") or 0, 0) > 0)
    stable_count = sum(1 for item in profile_facts if str(item.get("stability") or "").lower() == "stable")
    evolving_count = sum(1 for item in profile_facts if str(item.get("stability") or "").lower() == "evolving")
    temporary_count = sum(1 for item in profile_facts if str(item.get("stability") or "").lower() == "temporary")
    temporal_profile = build_temporal_profile(profile_facts, candidate_fact_ledger)
    return {
        "durable_profile_facts": len(profile_facts),
        "confirmed_candidate_facts": confirmed,
        "reinforced_candidate_facts": reinforced,
        "inferred_candidate_facts": inferred,
        "direct_statement_backed": direct,
        "document_backed": document_backed,
        "stable_profile_facts": stable_count,
        "evolving_profile_facts": evolving_count,
        "temporary_profile_facts": temporary_count,
        "stale_candidate_facts": len(temporal_profile.get("stale_candidates", [])),
    }


def build_candidate_fact_ledger(candidate_facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ledger: list[dict[str, Any]] = []
    for fact in candidate_facts:
        item = {
            "id": fact.get("id", ""),
            "fact_type": fact.get("fact_type", "generic"),
            "value": fact.get("value", ""),
            "normalized_value": fact.get("normalized_value") or str(fact.get("value", "")).casefold(),
            "confidence": float(fact.get("confidence", 0.0) or 0.0),
            "salience": float(fact.get("salience", 0.0) or 0.0),
            "status": fact.get("status", "candidate"),
            "time_scope": fact.get("time_scope", "long_term"),
            "stability": fact.get("stability", "evolving"),
            "evidence_kind": fact.get("evidence_kind", "inference"),
            "support_count": safe_int(fact.get("support_count", 0), 0),
            "direct_statement_count": safe_int(fact.get("direct_statement_count", 0), 0),
            "document_support_count": safe_int(fact.get("document_support_count", 0), 0),
            "revision_count": safe_int(fact.get("revision_count", 0), 0),
            "promotion_score": safe_float(fact.get("promotion_score"), 0.0),
            "created_at": fact.get("created_at"),
            "updated_at": fact.get("updated_at"),
            "metadata": metadata_dict(fact.get("metadata")),
        }
        item["confirmation_state"] = candidate_confirmation_state(item)
        ledger.append(item)
    return ledger


def build_full_profile_payload(student: dict[str, Any], raw_entities_by_label: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    entities_by_label = {
        label: dedupe_entities(items, label=label)
        for label, items in raw_entities_by_label.items()
    }
    profile_facts: list[dict[str, Any]] = []
    for personal_key in ("name", "email", "university", "program", "semester", "gpa"):
        fact = profile_fact_from_personal(personal_key, student.get(personal_key))
        if fact:
            profile_facts.append(fact)
    for label in ("Course", "Skill", "Goal", "Interest", "Company", "Project", "Constraint", "Preference"):
        for entity in entities_by_label.get(label, []):
            fact = profile_fact_from_entity(label, entity)
            if fact:
                profile_facts.append(fact)
    candidate_fact_ledger = build_candidate_fact_ledger(entities_by_label.get("CandidateFact", []))
    completeness_breakdown = profile_completeness_breakdown(student, entities_by_label, candidate_fact_ledger)
    fact_summary = profile_fact_summary(profile_facts, candidate_fact_ledger)
    temporal_profile = build_temporal_profile(profile_facts, candidate_fact_ledger)
    overall_completeness = round(
        sum(item.get("score", 0.0) for item in completeness_breakdown.values()) / max(len(completeness_breakdown), 1),
        2,
    )
    return {
        "personal": student,
        "courses": entities_by_label.get("Course", []),
        "skills": entities_by_label.get("Skill", []),
        "goals": entities_by_label.get("Goal", []),
        "interests": entities_by_label.get("Interest", []),
        "experience": entities_by_label.get("Company", []),
        "documents": entities_by_label.get("Document", []),
        "projects": entities_by_label.get("Project", []),
        "constraints": entities_by_label.get("Constraint", []),
        "preferences": entities_by_label.get("Preference", []),
        "candidate_facts": entities_by_label.get("CandidateFact", []),
        "candidate_fact_ledger": candidate_fact_ledger,
        "memory_items": entities_by_label.get("MemoryItem", []),
        "evidence": entities_by_label.get("Evidence", []),
        "profile_facts": profile_facts,
        "temporal_profile": temporal_profile,
        "all_entities": entities_by_label,
        "completeness": overall_completeness,
        "completeness_breakdown": completeness_breakdown,
        "fact_summary": fact_summary,
    }
