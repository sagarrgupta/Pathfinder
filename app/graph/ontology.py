"""Single source of truth for Neo4j node labels, relationships, and profile API keys.

All extraction prompts and ``store_extracted_entities`` should align with this module
so the graph stays consistent and dynamic labels are mapped predictably.
"""

from __future__ import annotations

import re
from typing import Any

# ── Allowed Neo4j identifiers (LLM output is validated before Cypher) ─────────
VALID_NODE_LABELS: frozenset[str] = frozenset({
    "Course",
    "Skill",
    "Company",
    "Project",
    "Goal",
    "Interest",
    "Department",
    "Document",
    "Chunk",
    "Student",
})

VALID_RELATIONSHIP_TYPES: frozenset[str] = frozenset({
    "HAS",
    "HAS_SKILL",
    "WORKED_AT",
    "COMPLETED",
    "TOOK",
    "HAS_GOAL",
    "INTERESTED_IN",
    "IN_DEPARTMENT",
    "UPLOADED",
    "FROM_DOCUMENT",
})

# Student → entity edges used when persisting extracted profile facts
RELATIONSHIP_FOR_LABEL: dict[str, str] = {
    "Course": "TOOK",
    "Skill": "HAS_SKILL",
    "Company": "WORKED_AT",
    "Project": "COMPLETED",
    "Goal": "HAS_GOAL",
    "Interest": "INTERESTED_IN",
    "Department": "IN_DEPARTMENT",
}

# Neo4j label → ``get_full_profile`` / API bucket name (backward compatible)
LABEL_TO_PROFILE_KEY: dict[str, str] = {
    "Course": "courses",
    "Skill": "skills",
    "Goal": "goals",
    "Interest": "interests",
    "Company": "experience",
    "Document": "documents",
    "Project": "projects",
    "Department": "departments",
}

# Evaluator / passive-learning field names → Neo4j label
_FIELD_TO_LABEL: dict[str, str] = {
    "interest": "Interest",
    "interests": "Interest",
    "goal": "Goal",
    "goals": "Goal",
    "skill": "Skill",
    "skills": "Skill",
    "company": "Company",
    "experience": "Company",
    "project": "Project",
    "projects": "Project",
    "course": "Course",
    "courses": "Course",
    "department": "Department",
    "departments": "Department",
}


def _is_safe_identifier(name: str) -> bool:
    return bool(name) and bool(re.match(r"^[A-Za-z][A-Za-z0-9_]*$", name))


def validate_label(label: str | None) -> str:
    """Return a whitelisted label or a safe default."""
    if label and label in VALID_NODE_LABELS and label not in ("Document", "Chunk", "Student"):
        return label
    return "Interest"


def validate_relationship(rel: str | None, label: str) -> str:
    """Return a whitelisted relationship, defaulting from *label* when needed."""
    if rel and rel in VALID_RELATIONSHIP_TYPES and rel not in ("UPLOADED", "FROM_DOCUMENT"):
        return rel
    return RELATIONSHIP_FOR_LABEL.get(label, "HAS")


def profile_key_for_label(label: str) -> str:
    """API key for a node label (fixed mapping or dynamic ``entity_<Label>``)."""
    if label in LABEL_TO_PROFILE_KEY:
        return LABEL_TO_PROFILE_KEY[label]
    # PascalCase → snake_case plural-ish bucket for new types
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", label).lower().strip("_")
    return f"entity_{snake}" if snake else "entity_misc"


def field_to_label(field: str) -> str:
    """Map evaluator profile field names to Neo4j labels."""
    return _FIELD_TO_LABEL.get(field.lower(), "Interest")


def label_to_relationship(label: str) -> str:
    """Default Student→entity relationship for a node label."""
    return RELATIONSHIP_FOR_LABEL.get(label, "HAS")


def normalize_extracted_entity(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Validate and normalize one LLM entity dict for storage."""
    label = validate_label(raw.get("label"))
    props = raw.get("properties")
    if not isinstance(props, dict):
        props = {}
    props = dict(props)
    rel = validate_relationship(raw.get("relationship"), label)
    name = props.get("name")
    if name is None or (isinstance(name, str) and not name.strip()):
        # Stable display/merge name for courses and similar
        fallback = props.get("code") or props.get("title") or props.get("id")
        if fallback is not None and str(fallback).strip():
            props["name"] = str(fallback).strip()
        elif not any(props.get(k) for k in ("code", "title", "id")):
            return None
    return {"label": label, "properties": props, "relationship": rel}


def ontology_prompt_fragment() -> str:
    """Inject into LLM prompts so extraction stays aligned with the graph."""
    pairs = [f"{lab}→{RELATIONSHIP_FOR_LABEL[lab]}" for lab in sorted(RELATIONSHIP_FOR_LABEL)]
    labels = ", ".join(sorted(RELATIONSHIP_FOR_LABEL.keys()))
    rels = ", ".join(sorted(RELATIONSHIP_FOR_LABEL.values()))
    return (
        f"Use exactly these node labels: {labels}. "
        f"Use these relationship types from the student to the entity: {rels}. "
        f"Preferred pairs: {'; '.join(pairs)}."
    )
