"""Deterministic request planning for obvious control-plane flows."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class RequestPlan:
    """High-confidence deterministic hints for a single request."""

    intent_hint: str = ""
    workflow_hint: str = ""
    advisor_mode: str = "adaptive"
    plan_hint: list[str] = field(default_factory=list)
    skip_llm_routing: bool = False
    has_files: bool = False
    has_url: bool = False
    is_greeting: bool = False
    is_profile_update: bool = False
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def build_request_plan(query: str, files: list[dict] | None = None, advisor_mode: str = "adaptive") -> RequestPlan:
    """Build deterministic routing hints for obvious non-ambiguous requests."""
    files = files or []
    lowered = (query or "").strip().lower()
    has_files = bool(files)
    has_url = "http://" in lowered or "https://" in lowered
    reasons: list[str] = []
    plan_hint: list[str] = []
    intent_hint = ""
    workflow_hint = ""
    normalized_mode = str(advisor_mode or "adaptive").strip().lower() or "adaptive"
    skip_llm_routing = False

    is_greeting = _is_greeting(lowered)
    if is_greeting and not has_files and not has_url:
        reasons.append("greeting_only")
        return RequestPlan(
            intent_hint="greeting",
            workflow_hint="general_guidance",
            advisor_mode=normalized_mode,
            plan_hint=[],
            skip_llm_routing=True,
            has_files=has_files,
            has_url=has_url,
            is_greeting=True,
            is_profile_update=False,
            reasons=reasons,
        )

    is_profile_update = _is_profile_update(lowered)
    if is_profile_update:
        reasons.append("direct_profile_update")
        intent_hint = "profile"
        workflow_hint = "student_state_update"
        plan_hint = ["profile_manager"]
        skip_llm_routing = True

    if has_files:
        reasons.append("file_upload_present")
        plan_hint = _prepend_unique(plan_hint, "doc_analyst")
        if not workflow_hint and _looks_like_document_request(lowered):
            workflow_hint = "document_guidance"

    if has_url:
        reasons.append("url_present")
        plan_hint = _prepend_unique(plan_hint, "web_researcher")
        if not workflow_hint and _looks_like_url_analysis(lowered):
            workflow_hint = "document_guidance"

    if normalized_mode != "adaptive":
        workflow_hint, mode_plan = _advisor_mode_plan(normalized_mode)
        if workflow_hint:
            reasons.append(f"advisor_mode:{normalized_mode}")
            for node in reversed(mode_plan):
                plan_hint = _prepend_unique(plan_hint, node)
            skip_llm_routing = True

    return RequestPlan(
        intent_hint=intent_hint,
        workflow_hint=workflow_hint,
        advisor_mode=normalized_mode,
        plan_hint=plan_hint,
        skip_llm_routing=skip_llm_routing,
        has_files=has_files,
        has_url=has_url,
        is_greeting=is_greeting,
        is_profile_update=is_profile_update,
        reasons=reasons,
    )


def _advisor_mode_plan(mode: str) -> tuple[str, list[str]]:
    mapping = {
        "semester_planning": ("academic_planning", ["profile_manager", "fact_extractor", "course_planner"]),
        "degree_audit": ("program_understanding", ["profile_manager", "fact_extractor", "program_advisor"]),
        "resume_review": ("document_guidance", ["doc_analyst", "profile_manager", "fact_extractor", "program_advisor"]),
        "internship_targeting": ("career_alignment", ["profile_manager", "fact_extractor", "career_matcher"]),
        "graduate_school_planning": ("program_understanding", ["profile_manager", "web_researcher", "fact_extractor", "program_advisor"]),
    }
    return mapping.get(mode, ("", []))


def _prepend_unique(items: list[str], value: str) -> list[str]:
    if value in items:
        return items
    return [value, *items]


def _is_greeting(query: str) -> bool:
    if not query:
        return False
    greetings = {
        "hi",
        "hello",
        "hey",
        "thanks",
        "thank you",
        "good morning",
        "good afternoon",
        "good evening",
    }
    return query in greetings or (len(query.split()) <= 3 and query.rstrip("!.?") in greetings)


def _is_profile_update(query: str) -> bool:
    if not query or "?" in query:
        return False
    if query.startswith(("what ", "how ", "which ", "can ", "could ", "should ", "find ", "search ", "summarize ", "compare ")):
        return False
    patterns = (
        "my gpa is",
        "my name is",
        "i am a",
        "i'm a",
        "i study at",
        "i'm interested in",
        "i am interested in",
        "i want to",
        "my goal is",
        "i prefer",
        "my skills are",
        "i know ",
    )
    return any(pattern in query for pattern in patterns)


def _looks_like_url_analysis(query: str) -> bool:
    return any(
        phrase in query
        for phrase in (
            "summarize",
            "summary",
            "read this",
            "review this",
            "explain this page",
            "analyze this page",
            "look at this url",
            "check this website",
        )
    )


def _looks_like_document_request(query: str) -> bool:
    return any(
        phrase in query
        for phrase in (
            "summarize my resume",
            "summarize my transcript",
            "read my resume",
            "read my transcript",
            "analyze my resume",
            "analyze my transcript",
            "review my resume",
            "review my transcript",
            "extract from my resume",
            "extract from my transcript",
        )
    )
