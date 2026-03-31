"""Shared helpers for distinguishing true conflicts from compatible facts."""

from __future__ import annotations

import re
from typing import Any


def normalize_text(value: str | None) -> str:
    text = re.sub(r"[^\w\s/+&,-]", "", (value or "").strip())
    text = re.sub(r"\s+", " ", text)
    return text.casefold()


def normalize_fact_value(fact_type: str, value: str | None) -> str:
    text = normalize_text(value)
    if fact_type == "goal":
        text = re.sub(r"^(my current (main )?goal is|my goal is|goal|seeking|looking for|aiming for|wanting|want to|want)\s+", "", text)
        text = re.sub(r"\b(obtain|looking|seeking|wanting|want)\b", "get", text)
        text = re.sub(r"\b(enter|entering)\b", "industry", text)
        text = re.sub(r"\binternships\b", "internship", text)
        text = re.sub(r"\bjobs\b", "job", text)
        text = re.sub(r"\broles\b", "role", text)
    elif fact_type in {"preference", "interest", "constraint"}:
        text = re.sub(r"^(i prefer|prefer|interested in|i need|need|must have|require)\s+", "", text)
    return text.strip()


def semantic_tokens(fact_type: str, value: str | None) -> set[str]:
    text = normalize_fact_value(fact_type, value)
    if not text:
        return set()
    stopwords = {"to", "a", "an", "the", "and", "go", "into", "first", "for", "my", "be", "is"}
    return {token for token in re.findall(r"[a-z0-9]+", text) if token not in stopwords}


def are_semantic_duplicates(fact_type: str, left: str | None, right: str | None) -> bool:
    left_tokens = semantic_tokens(fact_type, left)
    right_tokens = semantic_tokens(fact_type, right)
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    if union == 0:
        return False
    similarity = overlap / union
    return similarity >= 0.8 or left_tokens.issubset(right_tokens) or right_tokens.issubset(left_tokens)


def _contains_phrase(text: str, *phrases: str) -> bool:
    return any(phrase in text for phrase in phrases)


def _preference_axes(value: str | None) -> dict[str, str]:
    text = normalize_text(value)
    axes: dict[str, str] = {}
    if not text:
        return axes

    if _contains_phrase(text, "remote", "work from home", "wfh"):
        axes["work_mode"] = "remote"
    elif _contains_phrase(text, "hybrid"):
        axes["work_mode"] = "hybrid"
    elif _contains_phrase(text, "on site", "onsite", "in person", "in-person"):
        axes["work_mode"] = "onsite"

    if _contains_phrase(text, "closer to campus", "close to campus", "near campus", "moving closer to campus", "move closer to campus"):
        axes["campus_distance"] = "near"
    elif _contains_phrase(text, "far from campus", "stay home", "commute from home", "away from campus"):
        axes["campus_distance"] = "far"

    if _contains_phrase(text, "backend", "back-end"):
        axes["role_focus"] = "backend"
    elif _contains_phrase(text, "frontend", "front-end"):
        axes["role_focus"] = "frontend"
    elif _contains_phrase(text, "full stack", "full-stack"):
        axes["role_focus"] = "fullstack"

    if _contains_phrase(text, "industry", "full time", "full-time"):
        axes["career_track"] = "industry"
    elif _contains_phrase(text, "phd", "academia", "research track"):
        axes["career_track"] = "academia"

    return axes


def values_conflict(fact_type: str, left: str | None, right: str | None) -> bool:
    left_normalized = normalize_fact_value(fact_type, left)
    right_normalized = normalize_fact_value(fact_type, right)
    if not left_normalized or not right_normalized:
        return False
    if left_normalized == right_normalized or are_semantic_duplicates(fact_type, left_normalized, right_normalized):
        return False

    if fact_type in {"preference", "constraint"}:
        left_axes = _preference_axes(left_normalized)
        right_axes = _preference_axes(right_normalized)
        for axis in set(left_axes) & set(right_axes):
            if left_axes[axis] != right_axes[axis]:
                return True
        return False

    return left_normalized != right_normalized


def split_conflict_groups(fact_type: str, items: list[dict[str, Any]]) -> tuple[list[list[dict[str, Any]]], list[dict[str, Any]]]:
    """Separate incompatible clusters from facts that can safely coexist."""
    groups: list[list[dict[str, Any]]] = []
    compatible: list[dict[str, Any]] = []
    for item in items:
        value = item.get("value")
        if not str(value or "").strip():
            compatible.append(item)
            continue

        placed = False
        for group in groups:
            if any(values_conflict(fact_type, value, existing.get("value")) for existing in group):
                group.append(item)
                placed = True
                break
        if placed:
            continue

        if any(values_conflict(fact_type, value, other.get("value")) for other in items if other is not item):
            groups.append([item])
        else:
            compatible.append(item)

    merged_groups: list[list[dict[str, Any]]] = []
    while groups:
        current = groups.pop(0)
        changed = True
        while changed:
            changed = False
            remaining: list[list[dict[str, Any]]] = []
            for group in groups:
                if any(values_conflict(fact_type, left.get("value"), right.get("value")) for left in current for right in group):
                    current.extend(group)
                    changed = True
                else:
                    remaining.append(group)
            groups = remaining
        deduped: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for item in current:
            item_id = str(item.get("id") or "")
            key = item_id or f"{fact_type}:{normalize_fact_value(fact_type, item.get('value'))}"
            if key in seen_ids:
                continue
            seen_ids.add(key)
            deduped.append(item)
        if len(deduped) > 1:
            merged_groups.append(deduped)
        else:
            compatible.extend(deduped)
    return merged_groups, compatible
