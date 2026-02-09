"""Node 1: Input Guard.

Validates user input, detects prompt injection attempts, and
optionally enforces topic restrictions (academic/career only).
"""

from __future__ import annotations

import logging
import re

from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.input_guard")

# ── Patterns for prompt injection detection ─────────────────────
_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions|prompts)",
    r"you\s+are\s+now\s+a",
    r"disregard\s+(all\s+)?(previous|your)",
    r"forget\s+(everything|all|your\s+instructions)",
    r"system\s*:\s*",
    r"<\s*system\s*>",
    r"jailbreak",
    r"do\s+anything\s+now",
]

# ── Off-topic detection keywords ────────────────────────────────
# Broader keyword set to reduce false positives on legitimate queries
_ALLOWED_TOPICS = {
    # Academic
    "academic", "university", "college", "course", "class", "grade",
    "gpa", "transcript", "major", "minor", "degree", "school",
    "program", "graduate", "undergraduate", "phd", "master", "bachelor",
    "semester", "credit", "prerequisite", "elective", "curriculum",
    "professor", "advisor", "department", "thesis", "dissertation",
    "admission", "application", "scholarship", "financial", "tuition",
    # Career
    "career", "job", "internship", "resume", "interview", "skill",
    "project", "research", "certification", "work", "experience",
    "salary", "hire", "hiring", "recruit", "apply", "position", "role",
    "company", "startup", "promotion", "portfolio", "linkedin",
    # Tech
    "developer", "engineer", "data", "science", "computer", "software",
    "programming", "coding", "technology", "ai", "ml", "machine",
    "learning", "web", "mobile", "cloud", "database", "api",
    "backend", "frontend", "fullstack", "devops", "security", "design",
    # Companies
    "google", "amazon", "microsoft", "apple", "meta", "nvidia",
    "netflix", "tesla", "openai", "intel", "ibm", "oracle", "adobe",
    # General interaction
    "hello", "hi", "hey", "thanks", "thank", "help", "profile",
    "document", "upload", "file", "what", "how", "can", "should",
    "recommend", "suggest", "compare", "analyze", "plan", "goal",
    "review", "summarize", "read", "find", "search", "show", "tell",
    "list", "give", "explain", "describe", "check", "look", "open",
    # Study / learning
    "study", "learn", "practice", "prepare", "improve", "train",
    "book", "resource", "tutorial", "workshop", "bootcamp", "online",
}

# URLs always pass — the user explicitly wants web content analyzed
_URL_PATTERN = re.compile(r"https?://", re.IGNORECASE)

MAX_QUERY_LENGTH = 4000


async def input_guard(state: PathfinderState) -> PathfinderState:
    """Validate the user input and update state accordingly."""
    query = state.get("query", "").strip()
    topic_guard_enabled = state.get("topic_guard_enabled", True)

    step_progress = list(state.get("step_progress", []))
    step_progress.append("Validating your input...")

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

    # 3. Prompt injection detection
    query_lower = query.lower()
    for pattern in _INJECTION_PATTERNS:
        if re.search(pattern, query_lower):
            log.warning("Blocked: prompt injection detected — pattern=%s", pattern)
            return {
                **state,
                "is_blocked": True,
                "block_reason": "I detected an unusual pattern in your message. Please rephrase your question.",
                "step_progress": step_progress,
            }

    # 4. Topic guardrail (if enabled)
    if topic_guard_enabled:
        # URLs always pass — the user wants Pathfinder to analyze web content
        has_url = bool(_URL_PATTERN.search(query))

        # Has uploaded files → always relevant
        has_files = bool(state.get("files"))

        if not has_url and not has_files:
            words = set(re.findall(r"\w+", query_lower))
            if not words.intersection(_ALLOWED_TOPICS):
                log.info("Blocked: off-topic query")
                return {
                    **state,
                    "is_blocked": True,
                    "block_reason": (
                        "I'm designed to help with academic and career guidance. "
                        "Your question doesn't seem related to these topics. "
                        "You can disable topic filtering in Settings if you'd like to chat freely."
                    ),
                    "step_progress": step_progress,
                }

    step_progress.append("Input validated ✓")
    log.info("Input guard passed for query: %s", query[:60])
    return {
        **state,
        "is_blocked": False,
        "block_reason": "",
        "step_progress": step_progress,
    }
