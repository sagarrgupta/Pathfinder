"""Shared quality-oriented schemas and helpers.

This module centralizes the structured data used by the newer
quality pipeline: session summaries, evidence records, decision
payloads, and lightweight heuristics that multiple agents can share.
"""

from __future__ import annotations

import re
from typing import Any, Literal, TypedDict
from urllib.parse import urlparse


SourceType = Literal[
    "degree_page",
    "schedule_page",
    "admissions_page",
    "certificate_page",
    "job_page",
    "profile_doc",
    "general_web",
]

EntityType = Literal[
    "course",
    "requirement",
    "certificate",
    "prerequisite",
    "availability",
    "deadline",
    "job_role",
    "skill",
    "program_constraint",
    "program_policy",
    "graduation_constraint",
    "admission_constraint",
    "classification_constraint",
    "role_requirement",
    "preferred_skill",
    "required_skill",
    "work_mode_constraint",
    "location_constraint",
    "experience_requirement",
    "student_preference",
    "student_correction",
]

TimeScope = Literal["catalog", "live_schedule", "timeless", "unclear"]
TrustTier = Literal["primary_official", "secondary_official", "third_party", "user_profile"]
FitTier = Literal["direct", "adjacent", "weak"]
FreshnessTier = Literal["live", "catalog", "timeless", "unclear"]
StudentWorkflow = Literal[
    "academic_planning",
    "program_understanding",
    "eligibility_check",
    "comparison_guidance",
    "career_alignment",
    "document_guidance",
    "student_state_update",
    "general_guidance",
]


class EvidenceRecord(TypedDict, total=False):
    """Structured fact extracted from a source."""

    source_type: SourceType
    entity_type: EntityType
    value: dict[str, Any]
    source_url: str
    source_title: str
    excerpt: str
    confidence: float
    time_scope: TimeScope
    trust_tier: TrustTier
    fit_tier: FitTier
    freshness_tier: FreshnessTier


class AnswerSupportRef(TypedDict, total=False):
    """Reference from a recommendation/claim to supporting evidence."""

    title: str
    url: str
    excerpt: str
    source_type: SourceType
    entity_type: EntityType


class DecisionPayload(TypedDict, total=False):
    """Structured decision produced by a specialist planner."""

    decision_type: str
    answer_outline: list[str]
    recommended_items: list[dict[str, Any]]
    blocked_or_uncertain_items: list[dict[str, Any]]
    assumptions: list[str]
    next_best_action: str
    source_refs: list[AnswerSupportRef]
    ranking_rationale: list[str]
    blocked_reasons: list[str]


class EvidenceGroups(TypedDict, total=False):
    """Typed buckets of extracted evidence for downstream planners."""

    requirements: list[EvidenceRecord]
    courses: list[EvidenceRecord]
    constraints: list[EvidenceRecord]
    availability: list[EvidenceRecord]
    certificates: list[EvidenceRecord]
    deadlines: list[EvidenceRecord]
    job_roles: list[EvidenceRecord]
    job_requirements: list[EvidenceRecord]
    missing_skills: list[EvidenceRecord]
    profile_skills: list[EvidenceRecord]
    policies: list[EvidenceRecord]
    student_facts: list[EvidenceRecord]
    other: list[EvidenceRecord]


class TargetEntity(TypedDict, total=False):
    """Normalized entity the current query is primarily about."""

    kind: str
    name: str
    institution: str
    program: str
    level: str


class SourcePolicy(TypedDict, total=False):
    """Policy describing which sources should be preferred for the query."""

    primary_source_types: list[SourceType]
    secondary_source_types: list[SourceType]
    preferred_domains: list[str]
    allow_secondary_sources: bool
    prefer_pdfs: bool
    requires_live_data: bool
    tier_order: list[str]
    rationale: str
    fetch_budget: int
    strict_primary_only: bool


class SessionSummary(TypedDict, total=False):
    """Compact machine-readable view of the active conversation state."""

    institution: dict[str, Any]
    program: dict[str, Any]
    standing: dict[str, Any]
    completed_courses: dict[str, Any]
    current_skills: dict[str, Any]
    goals: dict[str, Any]
    preferences: dict[str, Any]
    unresolved_blockers: list[str]
    assumptions: list[str]
    recent_corrections: list[str]
    recent_decisions: list[str]


class CompactedSessionState(TypedDict, total=False):
    """Condensed long-term student advising state."""

    stable_facts: dict[str, Any]
    evolving_goals: list[str]
    preferences: dict[str, Any]
    corrections: list[str]
    recent_decisions: list[str]
    unresolved_blockers: list[str]
    verified_findings: list[str]


class TaskNode(TypedDict, total=False):
    """A dependency-aware internal task for the current turn."""

    id: str
    title: str
    kind: str
    depends_on: list[str]
    status: str
    required: bool


class SourceAuditEntry(TypedDict, total=False):
    """Why a source was selected or rejected."""

    url: str
    title: str
    source_type: SourceType | str
    action: str
    reason: str
    score: float
    trust_tier: TrustTier
    fit_tier: FitTier
    freshness_tier: FreshnessTier


class WorkingMemory(TypedDict, total=False):
    """Shared structured memory accumulated across nodes in a turn."""

    facts_confirmed: list[dict[str, Any]]
    facts_secondary: list[dict[str, Any]]
    unresolved_conflicts: list[dict[str, Any]]
    missing_primary_evidence: list[str]
    active_assumptions: list[str]
    planner_blockers: list[str]
    source_audit: list[SourceAuditEntry]
    ranking_rationale: list[str]
    dropped_claims: list[str]
    recent_decisions: list[str]


class DependencyStatus(TypedDict, total=False):
    """Health snapshot for external systems relevant to a turn."""

    neo4j: str
    llm: str
    embeddings: str
    web_search: str


class QueryFocus(TypedDict, total=False):
    """Coarse-grained interpretation of what kind of evidence matters most."""

    primary: str
    wants_live_availability: bool
    wants_requirements: bool
    wants_comparison: bool
    wants_jobs: bool
    wants_summary: bool
    wants_eligibility: bool
    wants_long_range_plan: bool


_SEMESTER_PATTERNS = [
    (re.compile(r"\bfirst semester\b", re.I), "first semester"),
    (re.compile(r"\bsecond semester\b", re.I), "second semester"),
    (re.compile(r"\bthird semester\b", re.I), "third semester"),
    (re.compile(r"\bfourth semester\b", re.I), "fourth semester"),
]

_COURSE_CODE_RE = re.compile(r"\b[A-Z]{2,4}\s?-?\d{3}[A-Z]?\b")
_UNIT_RE = re.compile(r"\b(\d{1,2})\s+units?\b", re.I)
_TERM_RE = re.compile(r"\b(fall|spring|summer|winter)\s+20\d{2}\b", re.I)
_DEADLINE_RE = re.compile(r"\b(deadline|due|apply by|application closes?)\b", re.I)
_INSTITUTION_RE = re.compile(
    r"\b((?:[A-Z][\w&'.-]*\s+){0,8}(?:University|College|Institute|School)(?:\s*[-,]\s*[A-Z][\w&'.-]+)*)\b"
)
_PROGRAM_HINT_RE = re.compile(
    r"\b(?:majoring in|studying|program(?:me)?(?: is| in)?|degree(?: is| in)?|pursuing|doing)\s+([A-Za-z][A-Za-z0-9&/,\- ]{2,80})",
    re.I,
)
_GOAL_PATTERNS = [
    re.compile(r"\b(?:want to become|want to be|want to work as|become|work as)\s+([A-Za-z][A-Za-z0-9 /&-]{2,80})", re.I),
    re.compile(r"\bgoal is to\s+([A-Za-z][A-Za-z0-9 /&-]{2,80})", re.I),
    re.compile(r"\binterested in\s+([A-Za-z][A-Za-z0-9 /&-]{2,80})", re.I),
]
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)


_GENERIC_PROGRAM_WORDS = {
    "program", "major", "minor", "degree", "studies", "study", "science", "arts",
    "master", "masters", "bachelor", "bachelors", "graduate", "undergraduate",
    "doctorate", "doctoral", "curriculum",
}
_COURSE_ENTRY_RE = re.compile(
    r"\b([A-Z]{2,4}\s?-?\d{3}[A-Z]?)\b(?:\s*[-:.\u2013]\s*|\s+)([A-Z][A-Za-z0-9&/,()' -]{3,100})"
)


def build_session_summary(
    profile: dict[str, Any], messages: list[Any], query: str
) -> SessionSummary:
    """Build a compact summary from profile data and conversation turns."""
    personal = profile.get("personal", {}) if profile else {}
    message_texts = [str(query)]
    recent_corrections: list[str] = []

    for msg in messages[-10:]:
        if isinstance(msg, tuple) and len(msg) == 2:
            role, content = msg
            if role in {"human", "user"}:
                message_texts.append(str(content))
        elif hasattr(msg, "content"):
            role = getattr(msg, "type", "")
            if role in {"human", "user"}:
                message_texts.append(str(msg.content))

    combined = "\n".join(message_texts)

    institution_name = personal.get("university") or _extract_institution(combined)
    program_name = personal.get("program") or _extract_program(combined)
    standing = personal.get("semester") or _extract_semester(combined)
    completed_courses = _extract_completed_courses(profile, combined)
    current_skills = [s.get("name", "") for s in profile.get("skills", []) if s.get("name")]
    goals = _extract_goals(profile, combined)
    preferences = _extract_preferences(combined)
    unresolved_blockers = _extract_blockers(combined, standing, completed_courses)
    recent_decisions = _extract_recent_decisions(messages)

    if re.search(r"\bnot\b", combined, re.I) and institution_name:
        recent_corrections.append(f"Use {institution_name} as the current institution context.")

    return {
        "institution": {
            "known": bool(institution_name),
            "value": institution_name or "",
        },
        "program": {
            "known": bool(program_name),
            "value": program_name or "",
        },
        "standing": {
            "known": bool(standing),
            "value": standing or "",
        },
        "completed_courses": {
            "known": True,
            "value": completed_courses,
        },
        "current_skills": {
            "known": bool(current_skills),
            "value": current_skills,
        },
        "goals": {
            "known": bool(goals),
            "value": goals,
        },
        "preferences": {
            "known": bool(preferences),
            "value": preferences,
        },
        "unresolved_blockers": unresolved_blockers,
        "assumptions": [
            "Latest user correction wins over older conversation context.",
        ],
        "recent_corrections": recent_corrections,
        "recent_decisions": recent_decisions,
    }


def init_working_memory(existing: dict[str, Any] | None = None) -> WorkingMemory:
    """Return a normalized working memory object with all expected keys."""
    current = dict(existing or {})
    return {
        "facts_confirmed": list(current.get("facts_confirmed", [])),
        "facts_secondary": list(current.get("facts_secondary", [])),
        "unresolved_conflicts": list(current.get("unresolved_conflicts", [])),
        "missing_primary_evidence": list(current.get("missing_primary_evidence", [])),
        "active_assumptions": list(current.get("active_assumptions", [])),
        "planner_blockers": list(current.get("planner_blockers", [])),
        "source_audit": list(current.get("source_audit", [])),
        "ranking_rationale": list(current.get("ranking_rationale", [])),
        "dropped_claims": list(current.get("dropped_claims", [])),
        "recent_decisions": list(current.get("recent_decisions", [])),
    }


def compact_session_state(
    session_summary: dict[str, Any] | None,
    working_memory: dict[str, Any] | None,
) -> CompactedSessionState:
    """Condense current summary and memory into long-term advising state."""
    summary = session_summary or {}
    memory = init_working_memory(working_memory)
    stable_facts = {
        "institution": ((summary.get("institution", {}) or {}).get("value", "")),
        "program": ((summary.get("program", {}) or {}).get("value", "")),
        "standing": ((summary.get("standing", {}) or {}).get("value", "")),
        "completed_courses": ((summary.get("completed_courses", {}) or {}).get("value", [])),
        "current_skills": ((summary.get("current_skills", {}) or {}).get("value", [])),
    }
    raw_preferences = (summary.get("preferences", {}) or {}).get("value", {})
    if isinstance(raw_preferences, dict):
        preferences = dict(raw_preferences)
    elif isinstance(raw_preferences, list):
        preferences = {value: True for value in raw_preferences if isinstance(value, str)}
    else:
        preferences = {}

    return {
        "stable_facts": stable_facts,
        "evolving_goals": list((summary.get("goals", {}) or {}).get("value", [])),
        "preferences": preferences,
        "corrections": list(summary.get("recent_corrections", [])),
        "recent_decisions": list(summary.get("recent_decisions", [])) + list(memory.get("recent_decisions", [])),
        "unresolved_blockers": list(summary.get("unresolved_blockers", [])) + list(memory.get("planner_blockers", [])),
        "verified_findings": [
            str(item.get("source_title", ""))
            for item in memory.get("facts_confirmed", [])
            if isinstance(item, dict) and item.get("source_title")
        ][:10],
    }


def append_unique_text(items: list[str], value: str) -> list[str]:
    """Append text to a list only if it is non-empty and not already present."""
    cleaned = (value or "").strip()
    if cleaned and cleaned not in items:
        items.append(cleaned)
    return items


def add_working_memory_item(
    working_memory: dict[str, Any] | None,
    bucket: str,
    item: Any,
) -> WorkingMemory:
    """Append an item into a working-memory bucket while preserving structure."""
    memory = init_working_memory(working_memory)
    values = list(memory.get(bucket, []))
    key = repr(item)
    seen = {repr(value) for value in values}
    if key not in seen:
        values.append(item)
    memory[bucket] = values
    return memory


def build_task_graph(
    query: str,
    workflow: str,
    query_focus: QueryFocus,
    target_entity: TargetEntity,
) -> list[TaskNode]:
    """Build a workflow-driven internal task graph for the current user goal."""
    tasks: list[TaskNode] = [
        {"id": "load_student_state", "title": "Load student state", "kind": "load_student_state", "depends_on": [], "status": "pending", "required": True},
        {"id": "load_conversation_state", "title": "Load conversation state", "kind": "load_conversation_state", "depends_on": [], "status": "pending", "required": True},
        {"id": "determine_decision_goal", "title": "Determine decision goal", "kind": "determine_decision_goal", "depends_on": ["load_student_state", "load_conversation_state"], "status": "pending", "required": True},
    ]

    primary = query_focus.get("primary", "")
    needs_research = workflow not in {"student_state_update", "general_guidance"} or bool(_URL_RE.search(query or ""))
    if needs_research:
        tasks.append({"id": "retrieve_primary_sources", "title": "Retrieve primary sources", "kind": "retrieve_primary_sources", "depends_on": ["determine_decision_goal"], "status": "pending", "required": True})
        tasks.append({"id": "retrieve_secondary_sources", "title": "Retrieve secondary sources", "kind": "retrieve_secondary_sources", "depends_on": ["retrieve_primary_sources"], "status": "pending", "required": False})

    if query_focus.get("wants_live_availability"):
        tasks.append({"id": "retrieve_live_schedule", "title": "Retrieve live schedule", "kind": "retrieve_live_schedule", "depends_on": ["retrieve_primary_sources"], "status": "pending", "required": False})

    if workflow in {"academic_planning", "program_understanding", "eligibility_check", "comparison_guidance", "document_guidance"}:
        tasks.extend([
            {"id": "extract_requirements", "title": "Extract requirements", "kind": "extract_requirements", "depends_on": ["retrieve_primary_sources"], "status": "pending", "required": True},
            {"id": "extract_courses", "title": "Extract courses", "kind": "extract_courses", "depends_on": ["retrieve_primary_sources"], "status": "pending", "required": workflow in {"academic_planning", "eligibility_check"}},
            {"id": "extract_constraints", "title": "Extract constraints", "kind": "extract_constraints", "depends_on": ["retrieve_primary_sources"], "status": "pending", "required": False},
            {"id": "extract_deadlines_or_policies", "title": "Extract deadlines or policies", "kind": "extract_deadlines_or_policies", "depends_on": ["retrieve_primary_sources"], "status": "pending", "required": workflow in {"program_understanding", "eligibility_check"}},
            {"id": "compare_to_student_state", "title": "Compare to student state", "kind": "compare_to_student_state", "depends_on": ["extract_requirements", "load_student_state"], "status": "pending", "required": workflow != "program_understanding"},
            {"id": "check_blockers", "title": "Check blockers", "kind": "check_blockers", "depends_on": ["compare_to_student_state"], "status": "pending", "required": False},
            {"id": "rank_options", "title": "Rank options", "kind": "rank_options", "depends_on": ["check_blockers" if workflow != "program_understanding" else "extract_requirements"], "status": "pending", "required": workflow in {"academic_planning", "comparison_guidance", "career_alignment"}},
        ])
    elif workflow == "career_alignment":
        tasks.extend([
            {"id": "extract_job_requirements", "title": "Extract job requirements", "kind": "extract_job_requirements", "depends_on": ["retrieve_primary_sources"], "status": "pending", "required": True},
            {"id": "compare_to_student_state", "title": "Compare to student state", "kind": "compare_to_student_state", "depends_on": ["extract_job_requirements", "load_student_state"], "status": "pending", "required": True},
            {"id": "check_blockers", "title": "Check blockers", "kind": "check_blockers", "depends_on": ["compare_to_student_state"], "status": "pending", "required": False},
            {"id": "rank_options", "title": "Rank options", "kind": "rank_options", "depends_on": ["check_blockers"], "status": "pending", "required": True},
        ])
    else:
        tasks.append({"id": "rank_options", "title": "Rank options", "kind": "rank_options", "depends_on": ["determine_decision_goal"], "status": "pending", "required": False})

    tasks.append({"id": "render_final_answer", "title": "Render final answer", "kind": "render_final_answer", "depends_on": ["rank_options"], "status": "pending", "required": True})
    return tasks


def complete_task(task_graph: list[TaskNode], task_id: str) -> list[TaskNode]:
    """Mark a task as completed in the in-memory task graph."""
    updated: list[TaskNode] = []
    for task in task_graph:
        copied = dict(task)
        if copied.get("id") == task_id:
            copied["status"] = "completed"
        updated.append(copied)
    return updated


def block_task(task_graph: list[TaskNode], task_id: str, required: bool | None = None) -> list[TaskNode]:
    """Mark a task as blocked in the in-memory task graph."""
    updated: list[TaskNode] = []
    for task in task_graph:
        copied = dict(task)
        if copied.get("id") == task_id:
            copied["status"] = "blocked"
            if required is not None:
                copied["required"] = required
        updated.append(copied)
    return updated


def summarize_trace(state: dict[str, Any]) -> dict[str, Any]:
    """Build a compact trace summary suitable for `/chat` done metadata."""
    task_graph = state.get("task_graph", []) or []
    completed = [task.get("id", "") for task in task_graph if task.get("status") == "completed"]
    blocked = [task.get("id", "") for task in task_graph if task.get("status") == "blocked"]
    source_audit = list((state.get("working_memory", {}) or {}).get("source_audit", []))
    selected = sum(1 for entry in source_audit if entry.get("action") == "selected")
    rejected = sum(1 for entry in source_audit if entry.get("action") == "rejected")
    return {
        "target_entity": state.get("target_entity", {}),
        "workflow": state.get("workflow", ""),
        "quality_path": infer_quality_path(state),
        "completed_tasks": completed,
        "blocked_tasks": blocked,
        "selected_sources": selected,
        "rejected_sources": rejected,
        "blocked_reasons": state.get("blocked_reasons", []),
        "dependency_status": state.get("dependency_status", {}),
    }


def infer_evidence_tiers(
    source_url: str,
    source_type: str,
    program_text: str,
    level: str,
    title: str,
    excerpt: str,
) -> tuple[TrustTier, FitTier, FreshnessTier]:
    """Infer trust, fit, and freshness tiers for an evidence record."""
    domain = urlparse(source_url or "").netloc.lower()
    trust_tier: TrustTier
    if source_type == "profile_doc":
        trust_tier = "user_profile"
    elif domain.endswith(".edu") or domain.endswith(".gov") or source_type in {
        "degree_page", "schedule_page", "admissions_page", "certificate_page",
    }:
        trust_tier = "primary_official" if source_type in {"degree_page", "schedule_page", "admissions_page"} else "secondary_official"
    else:
        trust_tier = "third_party"

    relevance_score = academic_source_relevance(title, excerpt, source_url, program_text, level)
    if relevance_score >= 2.0:
        fit_tier: FitTier = "direct"
    elif relevance_score >= 1.0:
        fit_tier = "adjacent"
    else:
        fit_tier = "weak"

    freshness_map = {
        "live_schedule": "live",
        "catalog": "catalog",
        "timeless": "timeless",
        "unclear": "unclear",
    }
    source_freshness = "live" if source_type == "schedule_page" else freshness_map.get(
        classify_web_source(source_url, title, excerpt)[1],
        "unclear",
    )
    return trust_tier, fit_tier, source_freshness  # type: ignore[return-value]


def record_source_audit(
    working_memory: dict[str, Any] | None,
    entry: SourceAuditEntry,
) -> WorkingMemory:
    """Append a source selection/rejection audit entry."""
    return add_working_memory_item(working_memory, "source_audit", entry)


def classify_web_source(url: str, title: str, content: str) -> tuple[SourceType, TimeScope]:
    """Classify a fetched web source into a coarse evidence bucket."""
    domain = urlparse(url).netloc.lower()
    combined = f"{title} {content}".lower()

    if any(word in combined for word in ("schedule of classes", "class schedule", "open seats", "section", "course schedule", "registration")):
        return "schedule_page", "live_schedule"
    if "admission" in combined or "apply" in combined:
        return "admissions_page", "timeless"
    if "certificate" in combined:
        return "certificate_page", "catalog"
    if (
        "job" in combined
        or "intern" in combined
        or "position" in combined
        or "hiring" in combined
        or domain.endswith("indeed.com")
        or domain.endswith("linkedin.com")
        or domain.startswith("jobs.")
    ):
        return "job_page", "unclear"
    if any(word in combined for word in (
        "program requirements",
        "degree requirements",
        "curriculum",
        "course requirements",
        "bachelor of",
        "master of",
        "doctor of",
        "ms in ",
        "bs in ",
        "ba in ",
        "ma in ",
    )):
        return "degree_page", "catalog"
    return "general_web", "unclear"


def analyze_query_focus(query: str) -> QueryFocus:
    """Infer the evidence focus implied by the user's question."""
    lowered = query.lower()
    return {
        "primary": (
            "career"
            if any(word in lowered for word in ("job", "career", "role", "internship"))
            else "comparison"
            if any(word in lowered for word in ("compare", "vs", "difference", "better"))
            else "summary"
            if any(word in lowered for word in ("summarize", "summary", "explain this page"))
            else "academic"
        ),
        "wants_live_availability": any(
            word in lowered
            for word in ("open now", "available", "enroll", "register", "this semester", "next semester", "offered", "open seats")
        ),
        "wants_requirements": any(
            word in lowered
            for word in ("requirement", "requirements", "prerequisite", "prerequisites", "units", "need for", "eligible", "qualify")
        ),
        "wants_comparison": any(word in lowered for word in ("compare", "vs", "better than", "difference between")),
        "wants_jobs": any(word in lowered for word in ("job", "career", "internship", "role", "fit me")),
        "wants_summary": any(word in lowered for word in ("summarize", "summary", "read this", "explain this page")),
        "wants_eligibility": any(word in lowered for word in ("can i", "am i eligible", "do i qualify", "can i take", "can i apply")),
        "wants_long_range_plan": any(word in lowered for word in ("2 years", "two years", "graduate in", "graduation plan", "roadmap", "long term")),
    }


def infer_student_workflow(
    query: str,
    query_focus: QueryFocus,
    files: list[Any] | None = None,
    target_entity: TargetEntity | None = None,
) -> StudentWorkflow:
    """Infer the general advising workflow for the current turn."""
    lowered = (query or "").lower()
    target_kind = (target_entity or {}).get("kind", "")
    has_files = bool(files)

    if has_files or target_kind in {"document", "webpage"} or query_focus.get("wants_summary"):
        return "document_guidance"
    if query_focus.get("wants_jobs"):
        return "career_alignment"
    if query_focus.get("wants_comparison"):
        return "comparison_guidance"
    if query_focus.get("wants_long_range_plan") or any(word in lowered for word in ("finish in", "graduate in", "two year", "2 year", "semester wise")):
        return "academic_planning"
    if query_focus.get("wants_eligibility"):
        return "eligibility_check"
    if any(word in lowered for word in ("elective", "next semester", "what should i take", "course plan", "semester plan")):
        return "academic_planning"
    if any(word in lowered for word in ("requirement", "policy", "prerequisite", "admission", "breadth", "core", "program")):
        return "program_understanding"
    if any(word in lowered for word in ("my gpa", "my university", "my program", "i am", "i study at")):
        return "student_state_update"
    return "general_guidance"


def build_support_ref(record: EvidenceRecord) -> AnswerSupportRef:
    """Convert an evidence record into a support ref."""
    return {
        "title": record.get("source_title", ""),
        "url": record.get("source_url", ""),
        "excerpt": record.get("excerpt", ""),
        "source_type": record.get("source_type", "general_web"),
        "entity_type": record.get("entity_type", "requirement"),
    }


def group_evidence_records(
    evidence_records: list[EvidenceRecord],
    profile: dict[str, Any] | None = None,
) -> EvidenceGroups:
    """Bucket evidence into typed groups for planner reasoning."""
    grouped: EvidenceGroups = {
        "requirements": [],
        "courses": [],
        "constraints": [],
        "availability": [],
        "certificates": [],
        "deadlines": [],
        "job_roles": [],
        "job_requirements": [],
        "missing_skills": [],
        "profile_skills": [],
        "policies": [],
        "student_facts": [],
        "other": [],
    }

    known_skills = {
        skill.get("name", "").strip().lower()
        for skill in (profile or {}).get("skills", [])
        if skill.get("name")
    }

    for record in evidence_records:
        entity_type = record.get("entity_type", "")
        value = record.get("value", {}) or {}

        if entity_type == "requirement":
            grouped["requirements"].append(record)
        elif entity_type == "course":
            grouped["courses"].append(record)
        elif entity_type == "availability":
            grouped["availability"].append(record)
        elif entity_type in {"program_constraint", "prerequisite"}:
            grouped["constraints"].append(record)
        elif entity_type in {"program_policy", "graduation_constraint", "admission_constraint", "classification_constraint"}:
            grouped["policies"].append(record)
        elif entity_type == "certificate":
            grouped["certificates"].append(record)
        elif entity_type == "deadline":
            grouped["deadlines"].append(record)
        elif entity_type == "job_role":
            grouped["job_roles"].append(record)
        elif entity_type == "skill":
            skill_name = str(value.get("name", "")).strip().lower()
            if record.get("source_type") == "profile_doc" or (skill_name and skill_name in known_skills):
                grouped["profile_skills"].append(record)
                grouped["student_facts"].append(record)
            else:
                grouped["job_requirements"].append(record)
                if skill_name and skill_name not in known_skills:
                    grouped["missing_skills"].append(record)
        elif entity_type in {"student_preference", "student_correction"}:
            grouped["student_facts"].append(record)
        else:
            grouped["other"].append(record)

    return grouped


def infer_target_entity(
    profile: dict[str, Any] | None,
    session_summary: dict[str, Any] | None,
    query: str,
    query_focus: QueryFocus | None = None,
) -> TargetEntity:
    """Infer the main entity the user is asking about."""
    query_focus = query_focus or analyze_query_focus(query)
    institution = ((session_summary or {}).get("institution", {}) or {}).get("value", "")
    program = infer_target_program(profile, session_summary, query)
    level = infer_target_level(profile, session_summary, query)
    primary = query_focus.get("primary", "academic")
    lowered = (query or "").lower()

    if _URL_RE.search(query or ""):
        kind = "document" if any(ext in lowered for ext in (".pdf", "pdf")) else "webpage"
        name = query.strip()
    elif primary == "career":
        kind = "job_role" if query_focus.get("wants_jobs") else "career_profile"
        name = _extract_goalish_name(query) or "career target"
    elif primary == "comparison":
        kind = "comparison_target"
        name = program or institution or "comparison target"
    elif primary == "summary":
        kind = "webpage" if any(word in lowered for word in ("page", "url", "website")) else "document"
        name = query.strip()
    else:
        if any(word in lowered for word in ("certificate", "specialization")):
            kind = "certificate"
        elif any(word in lowered for word in ("admission", "eligible", "requirements", "program")):
            kind = "program"
        else:
            kind = "program"
        name = program or institution or "academic program"

    return {
        "kind": kind,
        "name": name,
        "institution": institution,
        "program": program,
        "level": level,
    }


def build_source_policy(
    query_focus: QueryFocus,
    target_entity: TargetEntity,
    workflow: StudentWorkflow = "general_guidance",
    preferred_domains: list[str] | None = None,
) -> SourcePolicy:
    """Build a retrieval/extraction policy from query focus and target entity."""
    primary = query_focus.get("primary", "academic")
    kind = target_entity.get("kind", "")
    requires_live_data = bool(query_focus.get("wants_live_availability"))

    if workflow == "career_alignment" or primary == "career":
        primary_source_types: list[SourceType] = ["job_page", "profile_doc"]
        secondary_source_types: list[SourceType] = ["general_web"]
        prefer_pdfs = False
        tier_order = ["primary", "secondary"]
        rationale = "Career questions should prefer direct job postings and the student's own profile."
        fetch_budget = 5
        strict_primary_only = False
    elif workflow == "document_guidance" or kind in {"webpage", "document"}:
        primary_source_types = ["general_web", "profile_doc"]
        secondary_source_types = ["degree_page", "admissions_page", "job_page"]
        prefer_pdfs = True
        tier_order = ["primary", "secondary"]
        rationale = "URL and document questions should prioritize the provided page or file before search."
        fetch_budget = 4
        strict_primary_only = False
    elif workflow == "academic_planning" and requires_live_data:
        primary_source_types = ["schedule_page", "degree_page"]
        secondary_source_types = ["certificate_page", "admissions_page", "general_web"]
        prefer_pdfs = False
        tier_order = ["primary", "secondary"]
        rationale = "Enrollment-style questions should prioritize live schedules first, then official program pages."
        fetch_budget = 8
        strict_primary_only = True
    elif workflow == "comparison_guidance":
        primary_source_types = ["degree_page", "admissions_page", "profile_doc"]
        secondary_source_types = ["certificate_page", "general_web"]
        prefer_pdfs = True
        tier_order = ["primary", "secondary"]
        rationale = "Comparison questions should prioritize official pages for each option and use secondary sources only as support."
        fetch_budget = 7
        strict_primary_only = True
    elif workflow == "eligibility_check":
        primary_source_types = ["degree_page", "admissions_page", "profile_doc"]
        secondary_source_types = ["schedule_page", "certificate_page", "general_web"]
        prefer_pdfs = True
        tier_order = ["primary", "secondary"]
        rationale = "Eligibility questions should prioritize official requirements, constraints, and admissions/program policy pages."
        fetch_budget = 7
        strict_primary_only = True
    elif kind == "certificate":
        primary_source_types = ["certificate_page", "degree_page"]
        secondary_source_types = ["admissions_page", "general_web"]
        prefer_pdfs = True
        tier_order = ["primary", "secondary"]
        rationale = "Certificate questions should prioritize official certificate and related program pages."
        fetch_budget = 6
        strict_primary_only = False
    else:
        primary_source_types = ["degree_page", "admissions_page", "profile_doc"]
        secondary_source_types = ["certificate_page", "schedule_page", "general_web"]
        prefer_pdfs = True
        tier_order = ["primary", "secondary"]
        rationale = "Program and requirements questions should prioritize official program pages, admissions pages, and official PDFs."
        fetch_budget = 7
        strict_primary_only = True

    return {
        "primary_source_types": primary_source_types,
        "secondary_source_types": secondary_source_types,
        "preferred_domains": list(preferred_domains or []),
        "allow_secondary_sources": True,
        "prefer_pdfs": prefer_pdfs,
        "requires_live_data": requires_live_data,
        "tier_order": tier_order,
        "rationale": rationale,
        "fetch_budget": fetch_budget,
        "strict_primary_only": strict_primary_only,
    }


def _extract_goalish_name(text: str) -> str:
    for pattern in _GOAL_PATTERNS:
        match = pattern.search(text or "")
        if match:
            return match.group(1).strip(" .,:;-")
    return ""


def extract_course_codes(text: str) -> list[str]:
    """Extract normalized course codes from arbitrary text."""
    codes = []
    for match in _COURSE_CODE_RE.findall(text or ""):
        normalized = match.replace("-", " ").replace("  ", " ").strip().upper()
        if normalized not in codes:
            codes.append(normalized)
    return codes


def extract_course_entries(text: str) -> list[dict[str, str]]:
    """Extract likely course code/title pairs from catalog-like text."""
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in _COURSE_ENTRY_RE.finditer(text or ""):
        code = match.group(1).replace("-", " ").replace("  ", " ").strip().upper()
        name = match.group(2).strip(" .,:;-")
        if len(name) < 4:
            continue
        key = f"{code}|{name.lower()}"
        if key in seen:
            continue
        seen.add(key)
        entries.append({"code": code, "name": name})
    return entries


def extract_units(text: str) -> list[int]:
    """Extract unit counts from text."""
    units = []
    for match in _UNIT_RE.findall(text or ""):
        value = int(match)
        if value not in units:
            units.append(value)
    return units


def extract_terms(text: str) -> list[str]:
    """Extract academic term references from text."""
    terms = []
    for match in _TERM_RE.findall(text or ""):
        # regex finds only first group; use finditer for full phrase
        pass
    for m in _TERM_RE.finditer(text or ""):
        term = m.group(0).title()
        if term not in terms:
            terms.append(term)
    return terms


def has_deadline_language(text: str) -> bool:
    """Return True if the text looks deadline-oriented."""
    return bool(_DEADLINE_RE.search(text or ""))


def infer_quality_path(state: dict[str, Any]) -> str:
    """Return a compact label that describes the evidence path used."""
    path = []
    if state.get("profile_data"):
        path.append("profile")
    if state.get("web_results"):
        path.append("web")
    if state.get("evidence_records"):
        path.append("facts")
    if state.get("decision_payload"):
        path.append("planner")
    if state.get("confidence_score") is not None:
        path.append("eval")
    if state.get("workflow"):
        path.append(str(state.get("workflow")))
    return "+".join(path) if path else "direct"


def infer_target_program(
    profile: dict[str, Any] | None,
    session_summary: dict[str, Any] | None,
    query: str = "",
) -> str:
    """Infer the student's target academic program from structured context."""
    summary_program = ((session_summary or {}).get("program", {}) or {}).get("value", "")
    if summary_program:
        return str(summary_program)
    personal = (profile or {}).get("personal", {}) if profile else {}
    if personal.get("program"):
        return str(personal.get("program"))
    return _extract_program(query or "")


def infer_target_level(
    profile: dict[str, Any] | None,
    session_summary: dict[str, Any] | None,
    query: str = "",
) -> str:
    """Infer whether the academic context is graduate, undergraduate, or unknown."""
    texts = [
        infer_target_program(profile, session_summary, query),
        str(((session_summary or {}).get("standing", {}) or {}).get("value", "")),
        str(((profile or {}).get("personal", {}) or {}).get("program", "")),
        query or "",
    ]
    combined = " ".join(texts).lower()
    if any(word in combined for word in ("master", "masters", "ms ", "m.s", "graduate", "phd", "doctoral")):
        return "graduate"
    if any(word in combined for word in ("bachelor", "bs ", "b.s", "undergraduate", "freshman", "sophomore")):
        return "undergraduate"
    return "unknown"


def program_keywords(program_text: str) -> list[str]:
    """Extract meaningful program tokens for relevance matching."""
    tokens = []
    for token in re.findall(r"[a-z]{3,}", (program_text or "").lower()):
        if token not in _GENERIC_PROGRAM_WORDS and token not in tokens:
            tokens.append(token)
    return tokens


def academic_source_relevance(
    title: str,
    content: str,
    url: str,
    program_text: str,
    level: str,
) -> float:
    """Score how relevant an academic source is to the student's program context."""
    combined = " ".join([title or "", content[:800] if content else "", url or ""]).lower()
    score = 0.0

    normalized_program = (program_text or "").strip().lower()
    if normalized_program and normalized_program in combined:
        score += 2.0

    keywords = program_keywords(program_text)
    overlap = [token for token in keywords if token in combined]
    score += min(1.8, len(overlap) * 0.7)

    if looks_like_course_catalog_source(title, url) and overlap:
        score += 0.6

    if level == "graduate":
        if _contains_any_term(combined, ("graduate", "master", "masters", "doctoral", "phd")) or "m.s" in combined or "ms " in combined:
            score += 0.8
        if _contains_any_term(combined, ("undergraduate", "baccalaureate", "bachelor", "minor")) or "b.s" in combined or "bs " in combined:
            score -= 1.3
    elif level == "undergraduate":
        if _contains_any_term(combined, ("undergraduate", "bachelor", "baccalaureate", "minor")):
            score += 0.7
        if _contains_any_term(combined, ("graduate", "master", "masters", "doctoral", "phd")):
            score -= 1.0

    return score


def is_academic_source_relevant(
    title: str,
    content: str,
    url: str,
    program_text: str,
    level: str,
) -> bool:
    """Return True when an academic source is sufficiently relevant to the student's program."""
    return academic_source_relevance(title, content, url, program_text, level) >= 1.0


def looks_like_course_catalog_source(title: str, url: str) -> bool:
    combined = f"{title} {url}".lower()
    return any(
        phrase in combined
        for phrase in ("courses-a-z", "course catalog", "course descriptions", "computer science (", "/courses/", "/csc", " class schedule ")
    )


def course_code_matches_level(
    code: str,
    level: str,
    title: str = "",
    content: str = "",
) -> bool:
    """Conservatively filter course codes that are implausible for the target level."""
    if level != "graduate":
        return True

    match = re.search(r"(\d{3})", code or "")
    if not match:
        return True

    number = int(match.group(1))
    combined = f"{title} {content}".lower()
    if number >= 200:
        return True
    if _contains_any_term(combined, ("graduate", "master", "masters", "doctoral", "phd")) or "m.s" in combined or "ms " in combined:
        return True
    return False


def _contains_any_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(term)}\b", text or "", re.I) for term in terms)


def _extract_institution(text: str) -> str:
    for match in _INSTITUTION_RE.finditer(text or ""):
        candidate = " ".join(match.group(1).split()).strip(" ,.-")
        if len(candidate.split()) >= 2:
            return candidate
    return ""


def _extract_program(text: str) -> str:
    for pattern in _PROGRAM_HINT_RE.finditer(text or ""):
        candidate = pattern.group(1).strip(" .,:;-")
        candidate = re.split(r"\b(?:at|in)\s+(?:[A-Z][\w&'.-]*\s+){0,8}(?:University|College|Institute|School)\b", candidate, maxsplit=1)[0]
        candidate = candidate.strip(" .,:;-")
        if candidate:
            return candidate
    return ""


def _extract_semester(text: str) -> str:
    for pattern, value in _SEMESTER_PATTERNS:
        if pattern.search(text):
            return value
    return ""


def _extract_completed_courses(profile: dict[str, Any], text: str) -> list[str]:
    courses = []
    for course in profile.get("courses", [])[:20]:
        code = course.get("code") or course.get("name")
        if code:
            courses.append(str(code))
    if re.search(r"\bnone courses completed\b|\bno courses completed\b|\bnone completed\b", text, re.I):
        return []
    return courses


def _extract_goals(profile: dict[str, Any], text: str) -> list[str]:
    goals = [g.get("name", "") for g in profile.get("goals", []) if g.get("name")]
    for pattern in _GOAL_PATTERNS:
        for match in pattern.finditer(text or ""):
            candidate = match.group(1).strip(" .,:;-")
            candidate = re.split(r"\b(?:at|for|because)\b", candidate, maxsplit=1)[0].strip(" .,:;-")
            candidate = re.sub(r"^(?:an?|the)\s+", "", candidate, flags=re.I)
            if candidate and candidate not in goals:
                goals.append(candidate)
    return goals


def _extract_preferences(text: str) -> dict[str, Any]:
    preferences: dict[str, Any] = {}
    if re.search(r"\bremote\b", text, re.I):
        preferences["work_mode"] = "remote"
    if re.search(r"\bin person\b|\bon campus\b", text, re.I):
        preferences["attendance"] = "in_person"
    if re.search(r"\bonline\b", text, re.I):
        preferences["attendance"] = "online"
    return preferences


def _extract_blockers(text: str, standing: str, completed_courses: list[str]) -> list[str]:
    blockers = []
    if standing and "first" in standing and not completed_courses:
        blockers.append("No completed graduate courses are recorded yet.")
    if re.search(r"\bdeficienc(y|ies)\b", text, re.I):
        blockers.append("The student may have deficiency-removal requirements.")
    return blockers


def _extract_recent_decisions(messages: list[Any]) -> list[str]:
    decisions: list[str] = []
    for msg in messages[-8:]:
        content = ""
        role = ""
        if isinstance(msg, tuple) and len(msg) == 2:
            role, content = str(msg[0]), str(msg[1])
        elif hasattr(msg, "content"):
            role = getattr(msg, "type", "")
            content = str(getattr(msg, "content", ""))
        if role in {"ai", "assistant"} and any(
            phrase in content.lower()
            for phrase in ("recommended", "best option", "next step", "you should", "i suggest")
        ):
            snippet = content.strip().splitlines()[0][:160]
            if snippet and snippet not in decisions:
                decisions.append(snippet)
    return decisions[:5]
