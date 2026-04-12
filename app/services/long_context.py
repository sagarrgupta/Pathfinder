"""Shared builders for the long-context payload passed to specialists."""

from __future__ import annotations

from typing import Any

SUMMARY_FIELDS = (
    "Student",
    "Academic",
    "Goals",
    "Preferences",
    "Skills",
    "Notes",
)

SUMMARY_TEMPLATE = "\n".join(f"{field}: " for field in SUMMARY_FIELDS)


def build_long_context_payload(
    profile: dict[str, Any] | None,
    session_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the durable long-context payload shared across runtime and UI."""
    normalized_profile = profile if isinstance(profile, dict) else {}
    normalized_summary = session_summary if isinstance(session_summary, dict) else {}
    summary = _summary(normalized_profile, normalized_summary)
    return {
        "summary": summary,
        "manifest": _manifest(normalized_profile),
        "small_facts": _small_facts(normalized_profile, normalized_summary),
    }


def normalize_long_context_summary(text: str) -> str:
    """Validate and normalize the editable long-context summary format."""
    raw = str(text or "").strip()
    if not raw:
        raise ValueError(
            "Long-context summary is required and must use the labeled template."
        )

    parsed: dict[str, str] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if ":" not in stripped:
            raise ValueError("Each summary line must use the format 'Label: value'.")
        label, value = stripped.split(":", 1)
        normalized_label = label.strip()
        if normalized_label not in SUMMARY_FIELDS:
            raise ValueError(
                f"Unsupported summary label '{normalized_label}'. Use only: {', '.join(SUMMARY_FIELDS)}."
            )
        if normalized_label in parsed:
            raise ValueError(f"Duplicate summary label '{normalized_label}'.")
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError(f"Summary field '{normalized_label}' cannot be empty. Use 'none' when needed.")
        parsed[normalized_label] = normalized_value

    missing = [field for field in SUMMARY_FIELDS if field not in parsed]
    if missing:
        raise ValueError(
            f"Missing required summary fields: {', '.join(missing)}."
        )

    return "\n".join(f"{field}: {parsed[field]}" for field in SUMMARY_FIELDS)


def _manifest(profile: dict[str, Any]) -> dict[str, Any]:
    all_entities = profile.get("all_entities", {}) if isinstance(profile.get("all_entities", {}), dict) else {}
    documents = profile.get("documents", []) if isinstance(profile.get("documents", []), list) else []
    document_groups: dict[str, int] = {}
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        group = str(doc.get("document_role") or doc.get("doc_type") or "unknown")
        document_groups[group] = document_groups.get(group, 0) + 1
    return {
        "graph_entity_types": {
            label: len(items)
            for label, items in all_entities.items()
            if isinstance(items, list) and items
        },
        "documents": {
            "count": len(documents),
            "groups": document_groups,
        },
    }


def _small_facts(profile: dict[str, Any], session_summary: dict[str, Any]) -> dict[str, Any]:
    personal = profile.get("personal", {}) if isinstance(profile.get("personal", {}), dict) else {}
    goals = [
        str(item.get("name") or item.get("value") or "").strip()
        for item in profile.get("goals", [])
        if isinstance(item, dict) and str(item.get("name") or item.get("value") or "").strip()
    ][:5]
    preferences = [
        str(item.get("name") or item.get("value") or "").strip()
        for item in profile.get("preferences", [])
        if isinstance(item, dict) and str(item.get("name") or item.get("value") or "").strip()
    ][:5]
    return {
        "name": str(personal.get("name", "") or ""),
        "institution": str(personal.get("university", "") or ((session_summary.get("institution", {}) or {}).get("value", ""))),
        "program": str(personal.get("program", "") or ((session_summary.get("program", {}) or {}).get("value", ""))),
        "semester": str(personal.get("semester", "") or ((session_summary.get("standing", {}) or {}).get("value", ""))),
        "gpa": str(personal.get("gpa", "") or ""),
        "goals": goals,
        "preferences": preferences,
    }


def _summary(profile: dict[str, Any], session_summary: dict[str, Any]) -> str:
    personal = profile.get("personal", {}) if isinstance(profile.get("personal", {}), dict) else {}
    stored = str(personal.get("long_context_summary", "") or "").strip()
    if stored:
        try:
            return normalize_long_context_summary(stored)
        except ValueError:
            return _default_summary(profile, session_summary, carried_notes=stored)

    return _default_summary(profile, session_summary)


def _default_summary(
    profile: dict[str, Any],
    session_summary: dict[str, Any],
    *,
    carried_notes: str = "",
) -> str:
    small_facts = _small_facts(profile, session_summary)
    skills = [
        str(item.get("name") or "").strip()
        for item in profile.get("skills", [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ][:8]
    values = {
        "Student": small_facts.get("name") or "none",
        "Academic": ", ".join(
            item
            for item in [
                f"institution {small_facts['institution']}" if small_facts.get("institution") else "",
                f"program {small_facts['program']}" if small_facts.get("program") else "",
                f"semester {small_facts['semester']}" if small_facts.get("semester") else "",
                f"GPA {small_facts['gpa']}" if small_facts.get("gpa") else "",
            ]
            if item
        ) or "none",
        "Goals": ", ".join(small_facts.get("goals") or []) or "none",
        "Preferences": ", ".join(small_facts.get("preferences") or []) or "none",
        "Skills": ", ".join(skills) or "none",
        "Notes": carried_notes or "none",
    }
    return normalize_long_context_summary(
        "\n".join(f"{field}: {values[field]}" for field in SUMMARY_FIELDS)
    )
