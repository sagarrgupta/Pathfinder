"""First stop in the chat flow — sanity-checks the user's question.

We refuse to spend LLM tokens on obviously-bad input: empty messages, huge
pastes, and patterns that look like SQL injection. Anything blocked here
jumps straight to the responder with a short explanation. Everything else
flows on to the orchestrator.

This is intentionally a cheap, deterministic step (regex only — no LLM).
"""

from __future__ import annotations

import logging
import re

from app.core.state import PathfinderState
from app.utils.progress import add_progress

log = logging.getLogger("pathfinder.agents.input_guard")

# Classic SQL-injection signatures. We never execute user text as SQL, but
# these patterns are still a reliable signal of abusive/malformed intent and
# cheap to block at the edge before any LLM work happens.
_SQLI_PATTERNS = [
    r"(?i)\bunion\b\s+\bselect\b",
    r"(?i)\bdrop\b\s+\btable\b",
    r"(?i)\binsert\b\s+\binto\b",
    r"(?i)\bdelete\b\s+\bfrom\b",
    r"(?i)\bupdate\b\s+\w+\s+\bset\b",
    r"(?i)\bor\b\s+1\s*=\s*1\b",
    r"(?i)'\s*or\s*'1'\s*=\s*'1",
    r"(?i)--",
    r"(?i)/\*.*\*/",
]

# Hard upper bound on query size. Anything much larger is almost certainly a
# paste-bomb and would waste the model's context window.
MAX_QUERY_LENGTH = 4000


async def input_guard(state: PathfinderState) -> PathfinderState:
    """Decide whether this turn should proceed or be stopped immediately.

    Sets `is_blocked=True` with a `block_reason` when the query is unsafe,
    empty, or too long. The workflow's conditional edge (see
    `app/core/workflow.py`) routes blocked turns straight to the responder
    so the user sees a clean refusal instead of a long silence.
    """
    query = str(state.get("query", "") or "").strip()
    input_guard_enabled = bool(state.get("topic_guard_enabled", True))

    step_progress = list(state.get("step_progress", []))
    add_progress(
        step_progress,
        stage="Checking your question",
        message="Making sure everything looks good before I begin.",
    )

    # Reject empty submissions — nothing to answer.
    if not query:
        log.info("Blocked: empty query")
        return {
            **state,
            "is_blocked": True,
            "block_reason": "Please enter a question or message.",
            "step_progress": step_progress,
        }

    # Reject oversize submissions before they hit the LLM.
    if len(query) > MAX_QUERY_LENGTH:
        log.info("Blocked: query too long (%d chars)", len(query))
        return {
            **state,
            "is_blocked": True,
            "block_reason": f"Your message is too long ({len(query)} characters). Please keep it under {MAX_QUERY_LENGTH} characters.",
            "step_progress": step_progress,
        }

    # Probe for SQL-injection-shaped inputs; this flag can be disabled per
    # turn (e.g., for admin testing) via `topic_guard_enabled`.
    query_lower = query.lower()
    if input_guard_enabled:
        for pattern in _SQLI_PATTERNS:
            if re.search(pattern, query_lower):
                log.warning("Blocked: SQL injection pattern detected — pattern=%s", pattern)
                return {
                    **state,
                    "is_blocked": True,
                    "block_reason": "I detected a potentially unsafe query pattern. Please rephrase your message.",
                    "step_progress": step_progress,
                }

    log.info("Input guard passed for query: %s", query[:60])
    return {
        **state,
        "is_blocked": False,
        "block_reason": "",
        "step_progress": step_progress,
    }
