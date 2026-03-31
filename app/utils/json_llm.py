"""Parse JSON objects and arrays from LLM text output."""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger("pathfinder.json_llm")


def parse_json_object(text: str) -> dict[str, Any] | None:
    """Extract the first JSON object from *text* (handles leading/trailing prose)."""
    if not text or not isinstance(text, str):
        return None
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end <= start:
        return None
    try:
        out = json.loads(text[start:end])
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        log.debug("parse_json_object failed (object), trying repair")
        return None


def parse_json_array(text: str) -> list[Any] | None:
    """Extract the first JSON array from *text*."""
    if not text or not isinstance(text, str):
        return None
    start = text.find("[")
    end = text.rfind("]") + 1
    if start < 0 or end <= start:
        return None
    try:
        out = json.loads(text[start:end])
        return out if isinstance(out, list) else None
    except json.JSONDecodeError:
        return None
