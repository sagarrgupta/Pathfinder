"""Node 1: Input Guard.

Validates user input and blocks obvious SQL injection patterns.
"""

from __future__ import annotations

import logging
import re

from app.core.state import PathfinderState
from app.utils.progress import add_progress

log = logging.getLogger("pathfinder.agents.input_guard")

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

MAX_QUERY_LENGTH = 4000


async def input_guard(state: PathfinderState) -> PathfinderState:
    """Validate the user input and update state accordingly."""
    query = str(state.get("query", "") or "").strip()
    input_guard_enabled = bool(state.get("topic_guard_enabled", True))

    step_progress = list(state.get("step_progress", []))
    add_progress(
        step_progress,
        stage="Checking your question",
        message="Making sure everything looks good before I begin.",
    )

    # 1. Empty query check
    if not query:
        log.info("Blocked: empty query")
        return {
            **state,
            "is_blocked": True,
            "block_reason": "Please enter a question or message.",
            "step_progress": step_progress,
        }

    # 2. Length check
    if len(query) > MAX_QUERY_LENGTH:
        log.info("Blocked: query too long (%d chars)", len(query))
        return {
            **state,
            "is_blocked": True,
            "block_reason": f"Your message is too long ({len(query)} characters). Please keep it under {MAX_QUERY_LENGTH} characters.",
            "step_progress": step_progress,
        }

    # 3. SQL injection detection
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
