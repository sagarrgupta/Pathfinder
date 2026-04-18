"""Helpers for short, user-facing workflow progress updates."""

from __future__ import annotations

from typing import Any


def add_progress(
    steps: list[dict[str, str]],
    *,
    stage: str,
    message: str = "",
) -> list[dict[str, str]]:
    """Append one user-facing progress item unless it duplicates the last one."""
    normalized_stage = str(stage or "").strip()
    normalized_message = str(message or "").strip()
    if not normalized_stage:
        return steps

    entry = {"stage": normalized_stage, "message": normalized_message}
    if steps and isinstance(steps[-1], dict):
        last_stage = str(steps[-1].get("stage", "") or "").strip()
        last_message = str(steps[-1].get("message", "") or "").strip()
        if last_stage == normalized_stage and last_message == normalized_message:
            return steps

    steps.append(entry)
    return steps


def normalize_progress_entry(entry: Any, *, fallback_stage: str) -> dict[str, str]:
    """Normalize legacy/string progress values into the frontend shape."""
    if isinstance(entry, dict):
        stage = str(entry.get("stage", "") or fallback_stage).strip() or fallback_stage
        message = str(entry.get("message", "") or "").strip()
        return {"stage": stage, "message": message}

    text = str(entry or "").strip()
    return {"stage": fallback_stage, "message": text}
