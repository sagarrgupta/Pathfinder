"""Shared utility helpers."""

from __future__ import annotations

from typing import Any


def coerce_bounded_int(
    value: Any,
    *,
    default: int,
    minimum: int = 1,
    maximum: int,
) -> int:
    """Parse an integer and clamp it into the configured range."""
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(parsed, maximum))
