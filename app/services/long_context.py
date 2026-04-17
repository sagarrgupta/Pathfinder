"""Shared builders for the long-context payload passed to specialists."""

from __future__ import annotations

from typing import Any

_ROOT_PROPERTY_EXCLUDE_KEYS = {
    "id",
    "created_at",
    "updated_at",
    "long_context_notes",
    "long_context_summary",
}


def get_profile_student(profile: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical root student properties from either profile shape."""
    student = profile.get("student")
    if isinstance(student, dict):
        return student

    root = profile.get("root_properties")
    return dict(root) if isinstance(root, dict) else {}


def get_profile_entity_groups(profile: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Return entity groups keyed by label for current and legacy profile payloads."""
    if isinstance(profile.get("all_entities"), dict):
        return {
            str(label): list(items)
            for label, items in profile.get("all_entities", {}).items()
            if isinstance(items, list)
        }

    groups: dict[str, list[dict[str, Any]]] = {}
    entities = profile.get("entities", []) if isinstance(profile.get("entities"), list) else []
    for entity in entities:
        if not isinstance(entity, dict):
            continue

        label = str(entity.get("entity_type") or "Entity")
        groups.setdefault(label, []).append(entity)

        for document in entity.get("documents", []) if isinstance(entity.get("documents"), list) else []:
            if isinstance(document, dict):
                groups.setdefault("Document", []).append(document)

        for chunk in entity.get("chunks", []) if isinstance(entity.get("chunks"), list) else []:
            if isinstance(chunk, dict):
                groups.setdefault("Chunk", []).append(chunk)

    return groups


def build_profile_manifest(profile: dict[str, Any], memories: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the compact manifest used by long-context and specialist runtime."""
    all_entities = get_profile_entity_groups(profile)
    documents = all_entities.get("Document", []) if isinstance(all_entities.get("Document"), list) else []
    document_groups: dict[str, int] = {}
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        group = str(doc.get("file_type") or "unknown")
        document_groups[group] = document_groups.get(group, 0) + 1

    manifest = {
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

    normalized_memories = memories if isinstance(memories, dict) else {}
    if normalized_memories:
        manifest["memory_buckets"] = {
            key: len(value)
            for key, value in normalized_memories.items()
            if isinstance(value, list)
        }

    return manifest


def build_profile_small_facts(
    profile: dict[str, Any],
    session_summary: dict[str, Any],
) -> dict[str, Any]:
    """Extract populated root fields, section labels, and entity types."""
    summary_fields = _summary_bucket(session_summary, "root_properties")
    if isinstance(summary_fields, dict) and summary_fields:
        root_fields = dict(summary_fields)
    else:
        root_fields = get_profile_student(profile)

    profile_fields: dict[str, str] = {}
    for key, value in root_fields.items():
        if key in _ROOT_PROPERTY_EXCLUDE_KEYS:
            continue
        text = str(value or "").strip()
        if text:
            profile_fields[key] = text

    summary_sections = _summary_bucket(session_summary, "sections")
    if isinstance(summary_sections, list) and summary_sections:
        section_labels = [
            str(item).strip()
            for item in summary_sections
            if str(item).strip()
        ]
    else:
        sections = profile.get("sections", []) if isinstance(profile.get("sections"), list) else []
        section_labels = [
            str(item.get("label") or item.get("key") or "").strip()
            for item in sections
            if isinstance(item, dict) and str(item.get("label") or item.get("key") or "").strip()
        ]

    summary_entity_types = _summary_bucket(session_summary, "entity_types")
    if isinstance(summary_entity_types, dict) and summary_entity_types:
        entity_types = [
            str(label).strip()
            for label, count in summary_entity_types.items()
            if str(label).strip()
            and int(count or 0) > 0
        ]

    return {
        "profile_fields": profile_fields,
        "sections": section_labels,
        "entity_types": entity_types,
    }


def _summary_bucket(summary: dict[str, Any], key: str) -> Any:
    entry = summary.get(key, {})
    if isinstance(entry, dict):
        return entry.get("value")
    return None


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
        "manifest": build_profile_manifest(normalized_profile),
        "small_facts": build_profile_small_facts(normalized_profile, normalized_summary),
    }


def normalize_long_context_summary(text: str) -> str:
    """Validate and normalize an editable long-context summary.

    Accepts any set of ``Label: value`` lines — no fixed field list.
    """
    raw = str(text or "").strip()
    if not raw:
        raise ValueError(
            "Long-context summary is required and must use 'Label: value' lines."
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
        if not normalized_label:
            raise ValueError("Summary label cannot be empty.")
        if normalized_label in parsed:
            raise ValueError(f"Duplicate summary label '{normalized_label}'.")
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError(f"Summary field '{normalized_label}' cannot be empty. Use 'none' when needed.")
        parsed[normalized_label] = normalized_value

    if not parsed:
        raise ValueError("Summary must contain at least one 'Label: value' line.")

    return "\n".join(f"{label}: {value}" for label, value in parsed.items())


def _summary(profile: dict[str, Any], session_summary: dict[str, Any]) -> str:
    root = get_profile_student(profile)
    stored = str(root.get("long_context_summary", "") or "").strip()
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
    """Build a summary dynamically from whatever data exists in the profile."""
    facts = build_profile_small_facts(profile, session_summary)
    profile_fields = facts.get("profile_fields", {})
    section_labels = facts.get("sections", [])
    entity_types = facts.get("entity_types", [])

    lines: dict[str, str] = {}
    lines["Profile"] = profile_fields.get("name", "none")

    detail_parts = [
        f"{key} {value}"
        for key, value in profile_fields.items()
        if key != "name"
    ]
    lines["Details"] = ", ".join(detail_parts) if detail_parts else "none"
    lines["Sections"] = ", ".join(section_labels[:8]) if section_labels else "none"
    lines["Entities"] = ", ".join(entity_types[:8]) if entity_types else "none"
    lines["Notes"] = carried_notes or "none"

    summary_text = "\n".join(f"{label}: {value}" for label, value in lines.items())
    return normalize_long_context_summary(summary_text)
