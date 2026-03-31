"""Node 1: Input Guard.

Validates user input, detects prompt injection attempts, and
optionally enforces topic restrictions (academic/career only).
"""

from __future__ import annotations

import json
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.system_context import build_step_system_prompt
from app.adapters.llm.lmstudio import get_text_llm
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
    "company", "startup", "promotion", "portfolio", "linkedin", "jobs", "roles",
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
    "document", "upload", "file", "recommend", "suggest", "compare", "analyze", "plan", "goal", "name",
    "review", "summarize",
    # Study / learning
    "study", "learn", "practice", "prepare", "improve", "train",
    "book", "resource", "tutorial", "workshop", "bootcamp", "online",
    # Preferences / profile updates
    "prefer", "preference", "preferences", "goal", "goals", "interest", "interested", "plans",
}

# URLs always pass — the user explicitly wants web content analyzed
_URL_PATTERN = re.compile(r"https?://", re.IGNORECASE)
_PROFILE_INTRO_PATTERNS = [
    r"^\s*i am [a-z][a-z\s\-.']{0,80}$",
    r"^\s*i'm [a-z][a-z\s\-.']{0,80}$",
    r"^\s*my name is [a-z][a-z\s\-.']{0,80}$",
    r"^\s*this is [a-z][a-z\s\-.']{0,80}$",
]
_PROFILE_UPDATE_PATTERNS = [
    r"^\s*my goal is\b.+$",
    r"^\s*i prefer\b.+$",
    r"^\s*my preference is\b.+$",
    r"^\s*i want to\b.+$",
    r"^\s*i want\b.+$",
    r"^\s*i am interested in\b.+$",
    r"^\s*i'm interested in\b.+$",
]
_PROFILE_MEMORY_PATTERNS = [
    r"\bwhat do you know about me\b",
    r"\bwhat do you remember about me\b",
    r"\bwho am i\b",
    r"\bwhat's my name\b",
    r"\bwhich university do i study at\b",
    r"\bwhat is my (goal|program|major|university|gpa)\b",
    r"\bwhat's my (goal|program|major|university|gpa)\b",
]
_CAPABILITY_QUERY_PATTERNS = [
    r"\bwhat can you do\b",
    r"\bwhat do you do\b",
    r"\bhow can you help\b",
    r"\bwhat can pathfinder do\b",
    r"\bwhat are you able to do\b",
]

MAX_QUERY_LENGTH = 4000

_TOPIC_GUARD_PROMPT = build_step_system_prompt(
    step_name="input_guard.topic_guard",
    objective=(
        "Decide whether a borderline user message is within Pathfinder's scope for academic, career, "
        "student-profile, document, or related planning guidance."
    ),
    relevant_capabilities=("profile_memory_agent", "document_evidence_agent", "web_researcher"),
    extra_rules=(
        "Allow messages that are plausibly about academics, career guidance, student profile, planning, documents, schools, programs, jobs, internships, interviews, or related decision-making.",
        "Allow short personal-profile messages like introductions, goals, preferences, and follow-up questions about the user's situation.",
        "Block only when the message is clearly unrelated small talk or a truly unrelated domain.",
        "Be conservative about blocking; if it plausibly belongs in Pathfinder, allow it.",
    ),
    output_schema="""
Return ONLY JSON:
{
  "allow": true,
  "reason": "short explanation"
}
""",
)


async def _dynamic_topic_guard(query: str) -> dict[str, object]:
    llm = get_text_llm()
    try:
        response = await llm.ainvoke(
            [
                SystemMessage(content=_TOPIC_GUARD_PROMPT),
                HumanMessage(content=query[:1200]),
            ]
        )
        content = response.content if isinstance(response.content, str) else str(response.content)
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(content[start:end])
            return {
                "allow": bool(parsed.get("allow", False)),
                "reason": str(parsed.get("reason", "")).strip(),
            }
    except Exception as exc:
        log.warning("Dynamic topic guard failed: %s", exc)
    return {"allow": False, "reason": ""}


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
        is_profile_intro = any(re.match(pattern, query_lower) for pattern in _PROFILE_INTRO_PATTERNS)
        is_profile_update = any(re.match(pattern, query_lower) for pattern in _PROFILE_UPDATE_PATTERNS)
        is_profile_memory_query = any(re.search(pattern, query_lower) for pattern in _PROFILE_MEMORY_PATTERNS)
        is_capability_query = any(re.search(pattern, query_lower) for pattern in _CAPABILITY_QUERY_PATTERNS)
        short_benign_query = len(re.findall(r"\w+", query_lower)) <= 6 and bool(re.fullmatch(r"[\w\s?'!.,-]+", query_lower))

        if not has_url and not has_files and not is_profile_intro and not is_profile_update and not is_profile_memory_query and not is_capability_query:
            words = set(re.findall(r"\w+", query_lower))
            if not words.intersection(_ALLOWED_TOPICS):
                dynamic_guard = await _dynamic_topic_guard(query)
                if not dynamic_guard.get("allow", False):
                    if short_benign_query:
                        log.info("Allowing short benign query despite uncertain topic guard")
                        step_progress.append("Input validated ✓")
                        return {
                            **state,
                            "is_blocked": False,
                            "block_reason": "",
                            "step_progress": step_progress,
                        }
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
                log.info("Dynamic topic guard allowed borderline query: %s", dynamic_guard.get("reason", ""))

    step_progress.append("Input validated ✓")
    log.info("Input guard passed for query: %s", query[:60])
    return {
        **state,
        "is_blocked": False,
        "block_reason": "",
        "step_progress": step_progress,
    }
