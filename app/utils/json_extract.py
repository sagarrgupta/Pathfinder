"""Utilities for robustly extracting JSON payloads from model output."""

from __future__ import annotations

import json
import re
from typing import Any


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def parse_json_object(content: Any) -> dict[str, Any] | None:
    """Parse a JSON object from raw model output."""
    parsed = _parse_json_payload(content)
    return parsed if isinstance(parsed, dict) else None


def parse_json_array(content: Any) -> list[Any] | None:
    """Parse a JSON array from raw model output."""
    parsed = _parse_json_payload(content)
    return parsed if isinstance(parsed, list) else None


def _parse_json_payload(content: Any) -> Any | None:
    text = content if isinstance(content, str) else str(content or "")
    text = text.strip()
    if not text:
        return None

    direct = _try_loads(text)
    if direct is not None:
        return direct

    fence_match = _FENCE_RE.search(text)
    if fence_match:
        fenced = fence_match.group(1).strip()
        fenced_parsed = _try_loads(fenced)
        if fenced_parsed is not None:
            return fenced_parsed

    object_slice = _balanced_slice(text, "{", "}")
    if object_slice:
        obj = _try_loads(object_slice)
        if obj is not None:
            return obj

    array_slice = _balanced_slice(text, "[", "]")
    if array_slice:
        arr = _try_loads(array_slice)
        if arr is not None:
            return arr

    return None


def _try_loads(text: str) -> Any | None:
    try:
        return json.loads(text)
    except Exception:
        return None


def _balanced_slice(text: str, opener: str, closer: str) -> str:
    start = text.find(opener)
    if start < 0:
        return ""
    depth = 0
    for idx in range(start, len(text)):
        char = text[idx]
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return ""
