"""Shared Neo4j sanitization helpers for adapter return values."""

from __future__ import annotations

import json
from typing import Any

try:
    import neo4j.time as neo4j_time
except Exception:  # pragma: no cover
    neo4j_time = None  # type: ignore[assignment]


def sanitize_neo4j_value(value: Any) -> Any:
    """Convert Neo4j-specific values into plain Python/JSON-safe values."""
    if neo4j_time is not None:
        if isinstance(value, neo4j_time.DateTime):
            return value.to_native().isoformat()
        if isinstance(value, neo4j_time.Date):
            return value.to_native().isoformat()
        if isinstance(value, neo4j_time.Time):
            return str(value)
        if isinstance(value, neo4j_time.Duration):
            return str(value)
    if isinstance(value, dict):
        sanitized = {str(key): sanitize_neo4j_value(item) for key, item in value.items()}
        metadata_json = sanitized.get("metadata_json")
        if isinstance(metadata_json, str) and metadata_json.strip():
            try:
                sanitized["metadata"] = json.loads(metadata_json)
            except Exception:
                sanitized.setdefault("metadata", {})
        elif isinstance(sanitized.get("metadata"), str):
            try:
                parsed = json.loads(str(sanitized["metadata"]))
                if isinstance(parsed, dict):
                    sanitized["metadata"] = parsed
            except Exception:
                pass
        return sanitized
    if isinstance(value, list):
        return [sanitize_neo4j_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_neo4j_value(item) for item in value]
    if isinstance(value, set):
        return [sanitize_neo4j_value(item) for item in value]
    return value
