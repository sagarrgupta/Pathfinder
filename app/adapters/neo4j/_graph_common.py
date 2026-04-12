"""Shared utility helpers for the Neo4j graph store."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import neo4j.time as neo4j_time

_GRAPH_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def sanitize(value: Any) -> Any:
    """Convert Neo4j-specific types to Python-native types recursively."""
    if isinstance(value, neo4j_time.DateTime):
        return value.to_native().isoformat()
    if isinstance(value, neo4j_time.Date):
        return value.to_native().isoformat()
    if isinstance(value, neo4j_time.Time):
        return str(value)
    if isinstance(value, neo4j_time.Duration):
        return str(value)
    if isinstance(value, dict):
        sanitized = {k: sanitize(v) for k, v in value.items()}
        metadata_json = sanitized.get("metadata_json")
        if isinstance(metadata_json, str) and metadata_json.strip():
            try:
                sanitized["metadata"] = json.loads(metadata_json)
            except Exception:
                sanitized.setdefault("metadata", {})
        elif isinstance(sanitized.get("metadata"), str):
            try:
                sanitized["metadata"] = json.loads(str(sanitized["metadata"]))
            except Exception:
                pass
        return sanitized
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    return value


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def merge_unique_strings(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            text = str(item or "").strip()
            key = text.casefold()
            if text and key not in seen:
                seen.add(key)
                merged.append(text)
    return merged


def metadata_json(metadata: dict[str, Any] | None) -> str:
    try:
        return json.dumps(metadata or {}, ensure_ascii=True)
    except Exception:
        return "{}"


def metadata_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def metadata_fields(metadata: dict[str, Any] | None) -> dict[str, str]:
    """Return the canonical metadata payload for graph writes."""
    encoded = metadata_json(metadata)
    return {"metadata_json": encoded}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_name(value: str | None) -> str:
    text = re.sub(r"[^\w\s/+&,-]", "", (value or "").strip())
    text = re.sub(r"\s+", " ", text)
    return text.casefold()


def validate_graph_identifier(value: str, kind: str) -> str:
    """Validate dynamic Cypher identifiers used for labels/relationships."""
    text = str(value or "").strip()
    if not _GRAPH_IDENTIFIER_RE.fullmatch(text):
        raise ValueError(f"Invalid {kind}: {value!r}")
    return text


def record_map(record: Any, field: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
    """Extract and sanitize a projected map field from one Neo4j record."""
    if not record:
        return dict(default or {})
    value = record.get(field)
    if not isinstance(value, dict):
        return dict(default or {})
    return sanitize(dict(value))
