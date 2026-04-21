"""Turn Neo4j driver values into plain Python / JSON-safe values.

The Neo4j Python driver returns custom types for dates, durations,
nodes, and relationships. Those blow up `json.dumps()` and confuse any
downstream code that just wants dicts / lists / scalars.

Every adapter method pipes its result through `sanitize_neo4j_value`
before handing it back, so the rest of the app never sees driver types.
As a small bonus, if a record carries a `metadata_json` string we also
parse it into a real `metadata` dict here — the LLM tool layer relies
on having structured metadata, not serialized JSON blobs.
"""

from __future__ import annotations

import json
from typing import Any

try:
    import neo4j.time as neo4j_time
except Exception:  # pragma: no cover
    neo4j_time = None  # type: ignore[assignment]


def sanitize_neo4j_value(value: Any) -> Any:
    """Recursively normalize anything the driver might return.

    Handles Neo4j's temporal types (DateTime / Date / Time / Duration)
    and walks into containers so nested structures also come out clean.
    For dicts, unpacks stringified `metadata_json` into a real dict
    under `metadata` so LLM-facing tools get structured data.
    """
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
