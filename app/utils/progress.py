"""Helpers for short, user-facing workflow progress updates.

Progress is emitted along two paths:

1. **Buffered path** — every call to `add_progress` appends an entry to the
   node's `step_progress` list. The list is returned with the node's state
   update and ends up in the replay artifact.
2. **Live path** — if a live emitter is registered for the current async
   context (via `set_live_emitter`), each appended entry is also pushed to
   that emitter immediately. This lets a SSE handler stream progress out of
   a long-running node without waiting for the node to return.

The live path is opt-in: nodes never know whether one is registered, they
just call `add_progress` and the registered emitter (if any) sees the
entries in real time.
"""

from __future__ import annotations

import contextvars
from typing import Any, Callable


LiveEmitter = Callable[[dict[str, str]], None]


_live_emitter: contextvars.ContextVar[LiveEmitter | None] = contextvars.ContextVar(
    "pathfinder_live_progress_emitter",
    default=None,
)


def set_live_emitter(emitter: LiveEmitter | None) -> contextvars.Token:
    """Install a callback that gets every new progress entry in real time.

    The `/chat` SSE handler calls this at the top of a turn with a
    closure that enqueues messages onto the outbound stream. Because
    the emitter is stored on a `ContextVar`, it's automatically scoped
    to the current task — nodes running for a different session in the
    same process don't see each other's emitter.

    Returns the reset token, which the caller must feed back into
    `reset_live_emitter` in a `finally` block so emitters don't leak
    between turns.
    """
    return _live_emitter.set(emitter)


def reset_live_emitter(token: contextvars.Token) -> None:
    """Undo a prior `set_live_emitter`, restoring whatever was installed before."""
    _live_emitter.reset(token)


def add_progress(
    steps: list[dict[str, str]],
    *,
    stage: str,
    message: str = "",
) -> list[dict[str, str]]:
    """Record one progress line; stream it live if an emitter is installed.

    De-duplicates back-to-back identical entries so nodes don't
    accidentally spam the stream with the same "Searching..." line
    on every loop iteration. The in-memory list is also what ends
    up in the replay artifact, which gives us an exact record of
    what the user saw during the turn.
    """
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

    emitter = _live_emitter.get()
    if emitter is not None:
        try:
            emitter(dict(entry))
        except Exception:
            # Live path is best-effort; never let a stream consumer break a node.
            pass

    return steps


def normalize_progress_entry(entry: Any, *, fallback_stage: str) -> dict[str, str]:
    """Coerce a progress entry into the `{"stage", "message"}` shape the UI wants.

    Older state objects / replay files sometimes carry raw strings
    instead of dicts; we tolerate both so re-reading old replays
    doesn't blow up the list view.
    """
    if isinstance(entry, dict):
        stage = str(entry.get("stage", "") or fallback_stage).strip() or fallback_stage
        message = str(entry.get("message", "") or "").strip()
        return {"stage": stage, "message": message}

    text = str(entry or "").strip()
    return {"stage": fallback_stage, "message": text}
