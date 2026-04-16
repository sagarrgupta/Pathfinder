"""Shared quality-oriented schemas and helpers.

This module centralizes the structured data used by the newer
quality pipeline: session summaries, evidence records, decision
payloads, and lightweight heuristics that multiple agents can share.
"""

from __future__ import annotations

import json
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
    student_strategy: dict[str, Any]
    recommendation_paths: list[dict[str, Any]]


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


class EvidencePack(TypedDict, total=False):
    """Normalized evidence envelope shared across retrieval and reasoning stages."""

    query: str
    workflow: str
    student_strategy: dict[str, Any]
    student_operating_model: dict[str, Any]
    recommendation_outcome_profile: dict[str, Any]
    decision_continuity: dict[str, Any]
    profile_records: dict[str, Any]
    document_records: list[dict[str, Any]]
    web_records: list[dict[str, Any]]
    semantic_memory: dict[str, Any]
    memory_pack: dict[str, Any]
    saved_recommendations: list[dict[str, Any]]
    decision_records: list[dict[str, Any]]
    evidence_records: list[EvidenceRecord]
    evidence_groups: EvidenceGroups
    missing_information: list[str]
    source_audit: list[SourceAuditEntry]
    retrieval_summary: dict[str, Any]
    retrieval_trace: list[dict[str, Any]]
    retrieval_diagnostics: dict[str, Any]


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
    require_institution_match: bool
    target_institution: str
    target_program: str
    target_level: str
    max_search_queries: int
    search_retries: int
    prefer_profile_documents: bool
    governing_state_sources: list[str]
    web_research_mode: str
    targeted_web_questions: list[str]
    max_web_passes: int


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


class SessionMemoryState(TypedDict, total=False):
    """Dedicated short/session-lived memory separate from durable advising state."""

    transcript_digest: dict[str, Any]
    carry_forward_context: dict[str, Any]
    lifecycle: dict[str, Any]


class StudentOperatingModel(TypedDict, total=False):
    """Lightweight behavioral model inferred from profile, goals, and recent phrasing."""

    risk_tolerance: str
    workload_preference: str
    internship_urgency: str
    academic_caution: str
    grad_school_seriousness: str
    certainty_preference: str
    planning_style: str
    confidence: float
    signals: list[str]


class TaskNode(TypedDict, total=False):
    """A dependency-aware internal task for the current turn."""

    id: str
    title: str
    kind: str
    depends_on: list[str]
    status: str
    required: bool
    ready: bool
    blocked_reason: str
    failure_reason: str


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
    handoff_notes: list[dict[str, Any]]


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
    wants_application_targeting: bool
    wants_university_selection: bool


class ShortMemoryPolicy(TypedDict, total=False):
    """Explicit policy for short-memory lifecycle in a session."""

    policy_version: str
    scope: str
    ttl_seconds: int
    max_recent_turns: int
    max_messages: int
    eviction_strategy: str
    compaction_trigger_turns: int
    quality_mode: str


_SEMESTER_PATTERNS = [
    (re.compile(r"\bfirst semester\b", re.I), "first semester"),
    (re.compile(r"\bsecond semester\b", re.I), "second semester"),
    (re.compile(r"\bthird semester\b", re.I), "third semester"),
    (re.compile(r"\bfourth semester\b", re.I), "fourth semester"),
]

# Matches common course code formats across different university systems:
# US-style: CSC 200, MATH-101, DATA 255B, CS 6400
# Broader: COMP9024, CSCI1234, etc.
_COURSE_CODE_RE = re.compile(r"\b[A-Z]{1,8}\s?-?\d{2,4}[A-Z]?\b")
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
    r"\b([A-Z]{1,8}\s?-?\d{2,4}[A-Z]?)\b(?:\s*[-:.\u2013]\s*|\s+)([A-Z][A-Za-z0-9&/,()' -]{3,100})"
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
    current = dict(existing) if isinstance(existing, dict) else {}
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
        "handoff_notes": list(current.get("handoff_notes", [])),
    }


def compact_session_state(
    session_summary: dict[str, Any] | None,
    working_memory: dict[str, Any] | None,
    messages: list[Any] | None = None,
    short_memory_policy: dict[str, Any] | None = None,
) -> CompactedSessionState:
    """Condense current summary and memory into long-term advising state."""
    summary = session_summary or {}
    memory = init_working_memory(working_memory)
    conversation_digest = _build_conversation_digest(
        messages or [],
        max_recent_turns=int((short_memory_policy or {}).get("max_recent_turns", 12) or 12),
    )
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
        "conversation_digest": conversation_digest,
    }


def build_session_memory_state(
    session_summary: dict[str, Any] | None,
    compacted_session: dict[str, Any] | None,
    short_memory_policy: dict[str, Any] | None = None,
) -> SessionMemoryState:
    """Build explicit session-scoped memory from transcript and current turn context."""
    summary = session_summary or {}
    compacted = compacted_session or {}
    raw_digest = compacted.get("conversation_digest", {}) if isinstance(compacted, dict) else {}
    digest = dict(raw_digest) if isinstance(raw_digest, dict) else {}
    carry_forward_context = {
        "institution": str(((summary.get("institution", {}) or {}).get("value", "")) or ""),
        "program": str(((summary.get("program", {}) or {}).get("value", "")) or ""),
        "standing": str(((summary.get("standing", {}) or {}).get("value", "")) or ""),
        "goals": list((summary.get("goals", {}) or {}).get("value", []) or [])[:4],
        "recent_decisions": list(compacted.get("recent_decisions", []) or [])[:5],
        "unresolved_blockers": list(compacted.get("unresolved_blockers", []) or [])[:5],
        "recent_corrections": list(compacted.get("corrections", []) or [])[:4],
    }
    lifecycle = {
        "policy_version": str((short_memory_policy or {}).get("policy_version", "")),
        "ttl_seconds": int((short_memory_policy or {}).get("ttl_seconds", 0) or 0),
        "max_recent_turns": int((short_memory_policy or {}).get("max_recent_turns", 0) or 0),
        "eviction_strategy": str((short_memory_policy or {}).get("eviction_strategy", "")),
        "compaction_trigger_turns": int((short_memory_policy or {}).get("compaction_trigger_turns", 0) or 0),
    }
    return {
        "transcript_digest": digest,
        "carry_forward_context": carry_forward_context,
        "lifecycle": lifecycle,
    }


def _build_conversation_digest(messages: list[Any], max_recent_turns: int = 12) -> dict[str, Any]:
    """Build a bounded digest of recent conversation turns for long-session continuity."""
    turns: list[dict[str, str]] = []
    for msg in messages:
        role = ""
        content = ""
        if isinstance(msg, tuple) and len(msg) == 2:
            role, content = str(msg[0]), str(msg[1])
        elif hasattr(msg, "content"):
            role = str(getattr(msg, "type", "") or getattr(msg, "role", ""))
            content = str(getattr(msg, "content", "") or "")
        if role not in {"human", "user", "assistant", "ai"}:
            continue
        normalized_role = "user" if role in {"human", "user"} else "assistant"
        snippet = " ".join(content.split())
        if not snippet:
            continue
        turns.append(
            {
                "role": normalized_role,
                "content": snippet[:220] + ("..." if len(snippet) > 220 else ""),
            }
        )

    total_turns = len(turns)
    kept_turns = turns[-max_recent_turns:] if max_recent_turns > 0 else []
    omitted_turns = max(0, total_turns - len(kept_turns))
    return {
        "total_turns_seen": total_turns,
        "kept_turns": len(kept_turns),
        "omitted_turns": omitted_turns,
        "recent_turns": kept_turns,
    }


def build_evidence_pack(
    *,
    query: str,
    workflow: str,
    student_strategy: dict[str, Any] | None,
    student_operating_model: dict[str, Any] | None,
    recommendation_outcome_profile: dict[str, Any] | None,
    decision_continuity: dict[str, Any] | None,
    profile: dict[str, Any] | None,
    documents: list[dict[str, Any]] | None,
    web_results: list[dict[str, Any]] | None,
    semantic_memory: dict[str, Any] | None,
    memory_pack: dict[str, Any] | None,
    evidence_records: list[EvidenceRecord] | None,
    working_memory: dict[str, Any] | None,
    missing_information: list[str] | None = None,
) -> EvidencePack:
    """Normalize mixed retrieval outputs into one shared evidence envelope."""
    normalized_profile = dict(profile) if isinstance(profile, dict) else {}
    normalized_documents = list(documents) if isinstance(documents, list) else []
    normalized_web = list(web_results) if isinstance(web_results, list) else []
    normalized_semantic = dict(semantic_memory) if isinstance(semantic_memory, dict) else {}
    normalized_memory_pack = dict(memory_pack) if isinstance(memory_pack, dict) else {}
    raw_saved_recommendations = normalized_memory_pack.get("saved_recommendations", []) or []
    normalized_saved_recommendations = list(raw_saved_recommendations) if isinstance(raw_saved_recommendations, list) else []
    raw_decision_records = normalized_memory_pack.get("decision_records", []) or []
    normalized_decision_records = list(raw_decision_records) if isinstance(raw_decision_records, list) else []
    normalized_records = list(evidence_records) if isinstance(evidence_records, list) else []
    normalized_working_memory = init_working_memory(working_memory)
    evidence_groups = group_evidence_records(normalized_records, normalized_profile)
    retrieval_summary = {
        "strategy": str(normalized_memory_pack.get("strategy", "")),
        "document_count": len(normalized_documents),
        "web_count": len(normalized_web),
        "candidate_fact_count": len(normalized_semantic.get("candidate_facts", []) or []),
        "memory_item_count": len(normalized_semantic.get("memory_items", []) or []),
        "evidence_record_count": len(normalized_records),
        "has_primary_official": any(
            record.get("trust_tier") == "primary_official" for record in normalized_records
        ),
    }
    return {
        "query": query,
        "workflow": workflow,
        "student_strategy": dict(student_strategy) if isinstance(student_strategy, dict) else {},
        "student_operating_model": dict(student_operating_model) if isinstance(student_operating_model, dict) else {},
        "recommendation_outcome_profile": dict(recommendation_outcome_profile) if isinstance(recommendation_outcome_profile, dict) else {},
        "decision_continuity": dict(decision_continuity) if isinstance(decision_continuity, dict) else {},
        "profile_records": normalized_profile,
        "document_records": normalized_documents,
        "web_records": normalized_web,
        "semantic_memory": normalized_semantic,
        "memory_pack": normalized_memory_pack,
        "saved_recommendations": normalized_saved_recommendations,
        "decision_records": normalized_decision_records,
        "evidence_records": normalized_records,
        "evidence_groups": evidence_groups,
        "missing_information": list(missing_information or []),
        "source_audit": list(normalized_working_memory.get("source_audit", [])),
        "retrieval_summary": retrieval_summary,
        "retrieval_trace": list(normalized_memory_pack.get("retrieval_trace", []) or []),
        "retrieval_diagnostics": (
            dict(normalized_memory_pack.get("retrieval_diagnostics", {}))
            if isinstance(normalized_memory_pack.get("retrieval_diagnostics", {}), dict)
            else {}
        ),
    }


def derive_student_strategy(
    summary: dict[str, Any] | None,
    profile: dict[str, Any] | None,
    query: str,
) -> dict[str, Any]:
    """Infer the student's current optimization strategy from profile and query."""
    summary = summary or {}
    profile = profile or {}
    query_lower = (query or "").casefold()
    goals = [str(goal).casefold() for goal in ((summary.get("goals", {}) or {}).get("value", []) or [])]
    preferences = summary.get("preferences", {}) or {}
    preference_values = preferences.get("value", {}) if isinstance(preferences, dict) else {}
    load_light = any(token in query_lower for token in ("lighter", "light workload", "less workload", "manageable", "not overload"))
    internship = any(token in query_lower for token in ("internship", "job", "industry", "career")) or any(
        any(token in goal for token in ("internship", "industry", "job", "career")) for goal in goals
    )
    grad_school = any(token in query_lower for token in ("grad school", "phd", "research", "ms cs", "admissions")) or any(
        any(token in goal for token in ("phd", "research", "graduate", "grad school", "masters")) for goal in goals
    )
    gpa_focus = any(token in query_lower for token in ("gpa", "grades", "raise my gpa", "protect my gpa"))
    speed_focus = any(token in query_lower for token in ("graduate fast", "finish fast", "graduate early", "finish quickly"))
    remote_preference = any(
        token in str(preference_values).casefold() for token in ("remote", "hybrid", "onsite")
    )
    priorities: list[str] = []
    if internship:
        priorities.append("internship_readiness")
    if grad_school:
        priorities.append("grad_school_preparation")
    if gpa_focus:
        priorities.append("gpa_protection")
    if load_light:
        priorities.append("workload_balance")
    if speed_focus:
        priorities.append("graduation_speed")
    if not priorities:
        priorities.append("balanced_progress")
    primary = priorities[0]
    return {
        "primary_priority": primary,
        "priorities": priorities,
        "prefers_lower_load": load_light,
        "career_oriented": internship,
        "grad_school_oriented": grad_school,
        "gpa_sensitive": gpa_focus,
        "remote_preference_known": remote_preference,
    }


def derive_student_operating_model(
    summary: dict[str, Any] | None,
    profile: dict[str, Any] | None,
    query: str,
) -> StudentOperatingModel:
    """Infer a lightweight behavioral model for how this student tends to make tradeoffs."""
    summary = summary or {}
    profile = profile or {}
    query_lower = (query or "").casefold()
    temporal_profile = (profile.get("temporal_profile", {}) or {})
    preferences = (summary.get("preferences", {}) or {}).get("value", {}) or {}
    preference_text = str(preferences).casefold()
    evolving_values = [
        str(item.get("value", "")).casefold()
        for item in (temporal_profile.get("evolving_facts", []) or [])
        if str(item.get("value", "")).strip()
    ]
    temporary_values = [
        str(item.get("value", "")).casefold()
        for item in (temporal_profile.get("temporary_facts", []) or [])
        if str(item.get("value", "")).strip()
    ]
    goals = [str(goal).casefold() for goal in ((summary.get("goals", {}) or {}).get("value", []) or [])]
    combined_text = " ".join([query_lower, preference_text, *evolving_values[:8], *temporary_values[:8], *goals[:6]])

    prefers_light = any(token in combined_text for token in ("lighter", "manageable", "not overload", "balance", "workload"))
    urgent_career = any(token in combined_text for token in ("internship", "job soon", "asap", "urgent", "industry first"))
    cautious = any(token in combined_text for token in ("safe", "safer", "careful", "protect gpa", "avoid risk"))
    aggressive = any(token in combined_text for token in ("ambitious", "fastest", "aggressive", "stretch", "top school"))
    exploration = any(token in combined_text for token in ("explore", "open to", "not sure", "considering"))
    grad_school_focus = any(token in combined_text for token in ("phd", "research", "graduate school", "grad school", "masters", "ms cs"))
    certainty_seeking = any(token in combined_text for token in ("safe", "best option", "most realistic", "certain", "sure", "definite"))

    risk_tolerance = "balanced"
    if cautious and not aggressive:
        risk_tolerance = "conservative"
    elif aggressive and not cautious:
        risk_tolerance = "ambitious"

    workload_preference = "balanced"
    if prefers_light:
        workload_preference = "lighter"
    elif aggressive and "heavy" in combined_text:
        workload_preference = "heavier_if_valuable"

    internship_urgency = "moderate"
    if urgent_career:
        internship_urgency = "high"
    elif any(token in combined_text for token in ("later", "eventually", "after graduation")):
        internship_urgency = "low"

    academic_caution = "moderate"
    if cautious or any(token in combined_text for token in ("gpa", "grades", "academic risk")):
        academic_caution = "high"
    elif aggressive and not prefers_light:
        academic_caution = "low"

    grad_school_seriousness = "moderate"
    if grad_school_focus and any(token in combined_text for token in ("phd", "research", "publication", "lab", "thesis")):
        grad_school_seriousness = "high"
    elif not grad_school_focus:
        grad_school_seriousness = "low"

    certainty_preference = "balanced"
    if certainty_seeking and not exploration:
        certainty_preference = "high"
    elif exploration and not certainty_seeking:
        certainty_preference = "low"

    planning_style = "structured"
    if exploration:
        planning_style = "exploratory"
    elif urgent_career or cautious:
        planning_style = "decisive"

    signals: list[str] = []
    if prefers_light:
        signals.append("prefers_manageable_workload")
    if urgent_career:
        signals.append("career_urgency_detected")
    if cautious:
        signals.append("risk_averse_language_detected")
    if aggressive:
        signals.append("ambitious_language_detected")
    if exploration:
        signals.append("exploratory_language_detected")
    if grad_school_focus:
        signals.append("grad_school_focus_detected")
    if certainty_seeking:
        signals.append("certainty_seeking_detected")

    return {
        "risk_tolerance": risk_tolerance,
        "workload_preference": workload_preference,
        "internship_urgency": internship_urgency,
        "academic_caution": academic_caution,
        "grad_school_seriousness": grad_school_seriousness,
        "certainty_preference": certainty_preference,
        "planning_style": planning_style,
        "confidence": round(min(0.9, 0.35 + 0.1 * len(signals)), 2),
        "signals": signals,
    }


def derive_recommendation_outcome_profile(
    saved_recommendations: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Summarize how the student tends to respond to saved recommendations over time."""
    items = [item for item in (saved_recommendations or []) if isinstance(item, dict)]
    counts = {
        "active": 0,
        "accepted": 0,
        "postponed": 0,
        "ignored": 0,
        "completed": 0,
    }
    preferred_types: dict[str, float] = {}
    recent_outcomes: list[str] = []
    for item in items:
        metadata = _metadata_dict(item.get("metadata"))
        outcome_status = str(metadata.get("outcome_status") or metadata.get("status") or "active").strip().lower()
        recommendation_type = str(item.get("memory_type", "saved_plan")).replace("saved_", "").strip().lower() or "plan"
        if outcome_status not in counts:
            counts[outcome_status] = 0
        counts[outcome_status] += 1
        recent_outcomes.append(outcome_status)
        weight = 0.0
        if outcome_status == "completed":
            weight = 1.0
        elif outcome_status == "accepted":
            weight = 0.7
        elif outcome_status == "postponed":
            weight = 0.15
        elif outcome_status == "ignored":
            weight = -0.35
        if weight:
            preferred_types[recommendation_type] = preferred_types.get(recommendation_type, 0.0) + weight

    completed = counts.get("completed", 0)
    accepted = counts.get("accepted", 0)
    postponed = counts.get("postponed", 0)
    ignored = counts.get("ignored", 0)
    total = max(1, len(items))
    follow_through_ratio = round((completed + accepted) / total, 2)
    deferral_ratio = round(postponed / total, 2)
    avoidance_ratio = round(ignored / total, 2)

    follow_through_style = "mixed"
    if follow_through_ratio >= 0.65:
        follow_through_style = "high_follow_through"
    elif deferral_ratio >= 0.35:
        follow_through_style = "prefers_small_commits"
    elif avoidance_ratio >= 0.3:
        follow_through_style = "selective_commitment"

    top_types = [
        recommendation_type
        for recommendation_type, _score in sorted(preferred_types.items(), key=lambda item: item[1], reverse=True)
        if _score > 0
    ][:3]

    signals: list[str] = []
    if follow_through_style == "high_follow_through":
        signals.append("student_usually_follows_through")
    if follow_through_style == "prefers_small_commits":
        signals.append("student_often_defers_large_plans")
    if follow_through_style == "selective_commitment":
        signals.append("student_ignores_low-fit_recommendations")
    if top_types:
        signals.append("preferred_recommendation_types:" + ",".join(top_types))

    return {
        "counts": counts,
        "follow_through_style": follow_through_style,
        "follow_through_ratio": follow_through_ratio,
        "deferral_ratio": deferral_ratio,
        "avoidance_ratio": avoidance_ratio,
        "preferred_recommendation_types": top_types,
        "recent_outcomes": recent_outcomes[:6],
        "signals": signals,
    }


def derive_decision_continuity(
    query: str,
    decision_records: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Determine whether the current query appears to continue an earlier saved decision."""
    records = [item for item in (decision_records or []) if isinstance(item, dict)]
    query_terms = {
        token.casefold()
        for token in re.findall(r"[a-z0-9]{3,}", str(query or ""))
    }
    ranked: list[tuple[float, dict[str, Any]]] = []
    for item in records:
        metadata = _metadata_dict(item.get("metadata"))
        text = " ".join(
            [
                str(metadata.get("title", "")),
                str(item.get("summary", "")),
                " ".join(str(label) for label in (metadata.get("recommendation_labels", []) or [])[:5]),
                str(metadata.get("next_best_action", "")),
            ]
        )
        text_terms = {
            token.casefold()
            for token in re.findall(r"[a-z0-9]{3,}", text)
        }
        overlap = len(query_terms & text_terms)
        score = overlap + float(item.get("retrieval_score", item.get("match_score", 0.0)) or 0.0)
        ranked.append((score, item))
    ranked.sort(key=lambda item: item[0], reverse=True)
    related = [item for score, item in ranked if score > 0.8][:3]
    latest = related[0] if related else {}
    latest_metadata = _metadata_dict(latest.get("metadata"))
    return {
        "is_continuation": bool(related),
        "related_count": len(related),
        "latest_title": str(latest_metadata.get("title", "") or latest.get("summary", "")) if latest else "",
        "latest_decision_type": str(latest_metadata.get("decision_type", "") or ""),
        "related_titles": [
            str(_metadata_dict(item.get("metadata")).get("title", "") or item.get("summary", "")).strip()
            for item in related
            if str(_metadata_dict(item.get("metadata")).get("title", "") or item.get("summary", "")).strip()
        ][:3],
    }


def append_unique_text(items: list[str], value: str) -> list[str]:
    """Append text to a list only if it is non-empty and not already present."""
    cleaned = (value or "").strip()
    if cleaned and cleaned not in items:
        items.append(cleaned)
    return items


def _metadata_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


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
    return _recompute_task_readiness(tasks)


def complete_task(task_graph: list[TaskNode], task_id: str) -> list[TaskNode]:
    """Mark a task as completed in the in-memory task graph."""
    return set_task_status(task_graph, task_id, "completed")


def start_task(task_graph: list[TaskNode], task_id: str) -> list[TaskNode]:
    """Mark a task as in progress if it exists in the task graph."""
    return set_task_status(task_graph, task_id, "in_progress")


def block_task(task_graph: list[TaskNode], task_id: str, required: bool | None = None) -> list[TaskNode]:
    """Mark a task as blocked in the in-memory task graph."""
    return set_task_status(task_graph, task_id, "blocked", required=required)


def fail_task(
    task_graph: list[TaskNode],
    task_id: str,
    *,
    reason: str = "",
    cascade_block_dependents: bool = True,
) -> list[TaskNode]:
    """Mark a task as failed and optionally cascade block required dependents."""
    updated = set_task_status(task_graph, task_id, "failed", reason=reason)
    if not cascade_block_dependents:
        return updated
    return _cascade_block_dependents(updated, task_id, reason=reason or f"Dependency {task_id} failed")


def set_task_status(
    task_graph: list[TaskNode],
    task_id: str,
    status: str,
    *,
    reason: str = "",
    required: bool | None = None,
) -> list[TaskNode]:
    """Set status for one task and recompute dependency readiness."""
    updated: list[TaskNode] = []
    for task in task_graph:
        copied = dict(task)
        if copied.get("id") == task_id:
            copied["status"] = status
            if required is not None:
                copied["required"] = required
            if status == "blocked":
                copied["blocked_reason"] = reason
            elif status == "failed":
                copied["failure_reason"] = reason
        updated.append(copied)
    return _recompute_task_readiness(updated)


def _cascade_block_dependents(task_graph: list[TaskNode], failed_task_id: str, *, reason: str = "") -> list[TaskNode]:
    updated = [dict(task) for task in task_graph]
    changed = True
    while changed:
        changed = False
        for task in updated:
            status = str(task.get("status", "pending"))
            if status in {"completed", "blocked", "failed"}:
                continue
            depends_on = [str(dep) for dep in task.get("depends_on", [])]
            if failed_task_id not in depends_on and not any(
                any(dep == t.get("id") and str(t.get("status", "")) in {"blocked", "failed"} for t in updated)
                for dep in depends_on
            ):
                continue
            if task.get("required", False):
                task["status"] = "blocked"
                if reason:
                    task["blocked_reason"] = reason
                changed = True
    return _recompute_task_readiness(updated)


def _recompute_task_readiness(task_graph: list[TaskNode]) -> list[TaskNode]:
    status_by_id = {str(task.get("id", "")): str(task.get("status", "pending")) for task in task_graph}
    updated: list[TaskNode] = []
    for task in task_graph:
        copied = dict(task)
        depends_on = [str(dep) for dep in copied.get("depends_on", [])]
        dependencies_ready = all(status_by_id.get(dep) == "completed" for dep in depends_on)
        copied["ready"] = copied.get("status", "pending") == "pending" and dependencies_ready
        updated.append(copied)
    return updated


def summarize_trace(state: dict[str, Any]) -> dict[str, Any]:
    """Build a compact trace summary suitable for `/chat` done metadata."""
    task_graph = state.get("task_graph", []) or []
    completed = [task.get("id", "") for task in task_graph if task.get("status") == "completed"]
    blocked = [task.get("id", "") for task in task_graph if task.get("status") == "blocked"]
    source_audit = list((state.get("working_memory", {}) or {}).get("source_audit", []))
    handoff_notes = list((state.get("working_memory", {}) or {}).get("handoff_notes", []))
    selected = sum(1 for entry in source_audit if entry.get("action") == "selected")
    rejected = sum(1 for entry in source_audit if entry.get("action") == "rejected")
    payload = state.get("decision_payload", {}) or {}
    recommendations = payload.get("recommended_items", []) if isinstance(payload, dict) else []
    supported = 0
    for item in recommendations:
        if not isinstance(item, dict):
            continue
        if item.get("support_codes"):
            supported += 1
            continue
        refs = item.get("support_refs", [])
        if isinstance(refs, list) and any(isinstance(ref, dict) and ref.get("url") for ref in refs):
            supported += 1
    support_coverage = (supported / len(recommendations)) if recommendations else 0.0

    session_summary = state.get("session_summary", {}) or {}
    memory_sources_used: list[str] = []
    if session_summary or state.get("session_memory"):
        memory_sources_used.append("short")
    if state.get("compacted_session") or state.get("memory_pack"):
        memory_sources_used.append("long")
    latest_ingestion_result = state.get("latest_ingestion_result", {}) or {}

    return {
        "target_entity": state.get("target_entity", {}),
        "workflow": state.get("workflow", ""),
        "quality_path": infer_quality_path(state),
        "completed_tasks": completed,
        "blocked_tasks": blocked,
        "selected_sources": selected,
        "rejected_sources": rejected,
        "handoff_count": len(handoff_notes),
        "blocked_reasons": state.get("blocked_reasons", []),
        "dependency_status": state.get("dependency_status", {}),
        "stop_reason": state.get("stop_reason", ""),
        "support_coverage": round(support_coverage, 3),
        "assumption_count": len(payload.get("assumptions", []) if isinstance(payload, dict) else []),
        "memory_sources_used": memory_sources_used,
        "short_memory_policy": state.get("short_memory_policy", {}) or {},
        "latest_ingestion_result": latest_ingestion_result,
    }


def build_short_memory_policy(workflow: str, query_focus: QueryFocus) -> ShortMemoryPolicy:
    """Build an explicit TTL+eviction policy for short-memory state."""
    ttl_by_workflow = {
        "academic_planning": 6 * 60 * 60,
        "program_understanding": 6 * 60 * 60,
        "eligibility_check": 6 * 60 * 60,
        "comparison_guidance": 4 * 60 * 60,
        "career_alignment": 4 * 60 * 60,
        "document_guidance": 3 * 60 * 60,
        "student_state_update": 12 * 60 * 60,
        "general_guidance": 3 * 60 * 60,
    }
    ttl_seconds = ttl_by_workflow.get(workflow, 3 * 60 * 60)
    if query_focus.get("wants_long_range_plan"):
        ttl_seconds = max(ttl_seconds, 8 * 60 * 60)
    if query_focus.get("wants_live_availability"):
        ttl_seconds = min(ttl_seconds, 3 * 60 * 60)

    return {
        "policy_version": "short-memory-v1",
        "scope": "session",
        "ttl_seconds": int(ttl_seconds),
        "max_recent_turns": 12,
        "max_messages": 48,
        "eviction_strategy": "ttl_then_lru_turns",
        "compaction_trigger_turns": 10,
        "quality_mode": "quality_first",
    }


def add_handoff_note(
    working_memory: dict[str, Any] | None,
    *,
    from_node: str,
    to_node: str,
    contract: str,
    summary: str,
) -> WorkingMemory:
    """Append a compact inter-node handoff note to shared working memory."""
    return add_working_memory_item(
        working_memory,
        "handoff_notes",
        {
            "from": from_node,
            "to": to_node,
            "contract": contract,
            "summary": summary,
        },
    )


def recent_handoff_context(
    working_memory: dict[str, Any] | None,
    *,
    to_node: str,
    limit: int = 6,
) -> list[dict[str, str]]:
    """Return recent handoff notes relevant to a target node."""
    memory = init_working_memory(working_memory)
    notes = [
        {
            "from": str(note.get("from", "")),
            "to": str(note.get("to", "")),
            "contract": str(note.get("contract", "")),
            "summary": str(note.get("summary", "")),
        }
        for note in memory.get("handoff_notes", [])
        if isinstance(note, dict)
    ]
    relevant = [note for note in notes if note.get("to") == to_node or note.get("to") == "*" or note.get("to") == ""]
    return relevant[-limit:]


def infer_evidence_tiers(
    source_url: str,
    source_type: str,
    program_text: str,
    level: str,
    title: str,
    excerpt: str,
    institution_text: str = "",
) -> tuple[TrustTier, FitTier, FreshnessTier]:
    """Infer trust, fit, and freshness tiers for an evidence record."""
    source_url = _to_text(source_url)
    title = _to_text(title)
    excerpt = _to_text(excerpt)
    program_text = _to_text(program_text)
    institution_text = _to_text(institution_text)

    domain = urlparse(source_url).netloc.lower()
    official_domain = _is_official_domain(domain)
    trust_tier: TrustTier
    if source_type == "profile_doc":
        trust_tier = "user_profile"
    elif official_domain and source_type in {
        "degree_page", "schedule_page", "admissions_page", "certificate_page",
    }:
        trust_tier = "primary_official" if source_type in {"degree_page", "schedule_page", "admissions_page"} else "secondary_official"
    elif official_domain:
        trust_tier = "secondary_official"
    else:
        trust_tier = "third_party"

    relevance_score = academic_source_relevance(
        title,
        excerpt,
        source_url,
        program_text,
        level,
        institution_text,
    )
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
    safe_url = _to_text(url)
    safe_title = _to_text(title)
    safe_content = _to_text(content)
    domain = urlparse(safe_url).netloc.lower()
    combined = f"{safe_title} {safe_content}".lower()

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
    application_signals = _application_targeting_signals(lowered)
    has_term_target = bool(re.search(r"\b(fall|spring|summer|winter)\s+20\d{2}\b", lowered))
    has_graduation_deadline = bool(
        re.search(r"\b(graduate|finish|complete)\s+(by|before)\b", lowered)
        or re.search(r"\bby\s+(fall|spring|summer|winter)\s+20\d{2}\b", lowered)
    )
    primary_focus = (
        "career"
        if any(word in lowered for word in ("job", "career", "role", "internship"))
        else "comparison"
        if (
            any(word in lowered for word in ("compare", "vs", "difference", "better"))
            or (application_signals["is_application_targeting"] and application_signals["wants_university_selection"])
        )
        else "summary"
        if any(word in lowered for word in ("summarize", "summary", "explain this page"))
        else "academic"
    )
    return {
        "primary": primary_focus,
        "wants_live_availability": any(
            word in lowered
            for word in ("open now", "available", "enroll", "register", "this semester", "offered", "open seats")
        ),
        "wants_requirements": any(
            word in lowered
            for word in ("requirement", "requirements", "prerequisite", "prerequisites", "units", "need for", "eligible", "qualify")
        ),
        "wants_comparison": any(word in lowered for word in ("compare", "vs", "better than", "difference between")),
        "wants_jobs": any(word in lowered for word in ("job", "career", "internship", "role", "fit me")),
        "wants_summary": any(word in lowered for word in ("summarize", "summary", "read this", "explain this page")),
        "wants_eligibility": any(word in lowered for word in ("can i", "am i eligible", "do i qualify", "can i take", "can i apply")),
        "wants_application_targeting": application_signals["is_application_targeting"],
        "wants_university_selection": (
            application_signals["wants_university_selection"]
            or any(
                phrase in lowered
                for phrase in (
                    "which universities",
                    "rank universities",
                    "realistic universities",
                    "safe moderate ambitious",
                    "safe, moderate, and ambitious",
                    "top universities",
                    "best universities",
                )
            )
        ),
        "wants_long_range_plan": (
            any(word in lowered for word in ("2 years", "two years", "graduate in", "graduation plan", "roadmap", "long term"))
            or (has_term_target and has_graduation_deadline)
            or ("semester wise" in lowered or "semester-wise" in lowered)
        ),
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
    planning_markers = (
        "plan", "semester wise", "semester-wise", "roadmap", "course sequence",
        "what should i take", "which courses", "finish by", "next course", "next class",
    )
    near_term_markers = (
        "next semester", "next term", "next quarter", "upcoming term", "upcoming semester",
        "this term", "this semester", "this quarter", "coming term",
    )

    if has_files or target_kind in {"document", "webpage"} or query_focus.get("wants_summary"):
        return "document_guidance"
    if query_focus.get("wants_application_targeting") or query_focus.get("wants_university_selection"):
        application_signals = _application_targeting_signals(lowered)
        if (
            application_signals["wants_university_selection"]
            or query_focus.get("wants_university_selection")
            or query_focus.get("wants_comparison")
        ):
            return "comparison_guidance"
        return "eligibility_check"
    if query_focus.get("wants_long_range_plan") or any(marker in lowered for marker in planning_markers):
        return "academic_planning"
    if any(marker in lowered for marker in near_term_markers):
        return "academic_planning"
    if query_focus.get("wants_jobs"):
        return "career_alignment"
    if query_focus.get("wants_comparison"):
        return "comparison_guidance"
    if query_focus.get("wants_eligibility"):
        return "eligibility_check"
    if any(word in lowered for word in ("elective", "what should i take", "course plan", "semester plan", "term plan")):
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

    is_application_targeting = bool(query_focus.get("wants_application_targeting"))
    wants_university_selection = bool(query_focus.get("wants_university_selection"))
    prefer_profile_documents = False
    governing_state_sources: list[str] = []
    web_research_mode = "broad"
    targeted_web_questions: list[str] = []
    max_web_passes = 1

    if workflow == "career_alignment" or primary == "career":
        primary_source_types: list[SourceType] = ["job_page", "profile_doc"]
        secondary_source_types: list[SourceType] = ["general_web"]
        prefer_pdfs = False
        tier_order = ["primary", "secondary"]
        rationale = "Career questions should prefer direct job postings and the student's own profile."
        fetch_budget = 5
        strict_primary_only = False
        prefer_profile_documents = True
        governing_state_sources = ["profile_state", "job_requirements"]
        web_research_mode = "broad"
    elif workflow == "document_guidance" or kind in {"webpage", "document"}:
        primary_source_types = ["general_web", "profile_doc"]
        secondary_source_types = ["degree_page", "admissions_page", "job_page"]
        prefer_pdfs = True
        tier_order = ["primary", "secondary"]
        rationale = "URL and document questions should prioritize the provided page or file before search."
        fetch_budget = 4
        strict_primary_only = False
        web_research_mode = "broad"
    elif workflow == "academic_planning" and requires_live_data:
        primary_source_types = ["schedule_page", "degree_page"]
        secondary_source_types = ["profile_doc", "certificate_page", "admissions_page", "general_web"]
        prefer_pdfs = False
        tier_order = ["primary", "secondary"]
        rationale = "Enrollment-style questions should prioritize live schedules first, then official program pages, while still considering transcript/degree documents."
        fetch_budget = 8
        strict_primary_only = True
        governing_state_sources = ["live_schedule", "official_requirements", "transcript_state"]
        web_research_mode = "targeted"
        max_web_passes = 2
    elif workflow == "academic_planning":
        primary_source_types = ["profile_doc", "degree_page", "admissions_page"]
        secondary_source_types = ["schedule_page", "certificate_page", "general_web"]
        prefer_pdfs = True
        tier_order = ["primary", "secondary"]
        rationale = "Academic progression questions should prefer transcript and degree documents first, then use targeted official web research to validate unresolved requirement gaps."
        fetch_budget = 6
        strict_primary_only = False
        prefer_profile_documents = True
        governing_state_sources = ["transcript_state", "profile_state", "official_requirements"]
        web_research_mode = "targeted"
        max_web_passes = 2
    elif workflow == "comparison_guidance":
        primary_source_types = ["degree_page", "admissions_page", "profile_doc"]
        secondary_source_types = ["schedule_page", "certificate_page", "general_web"]
        prefer_pdfs = True
        tier_order = ["primary", "secondary"]
        rationale = "Comparison questions should prioritize official program/admissions sources for each option and use secondary sources only as support."
        fetch_budget = 8 if (is_application_targeting or wants_university_selection) else 7
        strict_primary_only = False if (is_application_targeting or wants_university_selection) else True
        web_research_mode = "broad"
    elif workflow == "eligibility_check":
        primary_source_types = ["profile_doc", "degree_page", "admissions_page"]
        secondary_source_types = ["schedule_page", "certificate_page", "general_web"]
        prefer_pdfs = True
        tier_order = ["primary", "secondary"]
        rationale = "Eligibility questions should prefer student documents first, then use targeted official requirement checks to resolve blockers."
        fetch_budget = 7
        strict_primary_only = False
        prefer_profile_documents = True
        governing_state_sources = ["transcript_state", "official_requirements", "profile_state"]
        web_research_mode = "targeted"
        max_web_passes = 2
    elif kind == "certificate":
        primary_source_types = ["certificate_page", "degree_page"]
        secondary_source_types = ["admissions_page", "general_web"]
        prefer_pdfs = True
        tier_order = ["primary", "secondary"]
        rationale = "Certificate questions should prioritize official certificate and related program pages."
        fetch_budget = 6
        strict_primary_only = False
        web_research_mode = "broad"
    else:
        primary_source_types = ["degree_page", "admissions_page", "profile_doc"]
        secondary_source_types = ["certificate_page", "schedule_page", "general_web"]
        prefer_pdfs = True
        tier_order = ["primary", "secondary"]
        rationale = "Program and requirements questions should prioritize official program pages, admissions pages, and official PDFs."
        fetch_budget = 7
        strict_primary_only = True
        web_research_mode = "broad"

    target_institution = str(target_entity.get("institution", "") or "")
    target_program = str(target_entity.get("program", "") or "")
    target_level = str(target_entity.get("level", "") or "")
    require_institution_match = workflow in {
        "academic_planning",
        "program_understanding",
        "eligibility_check",
    } or primary == "academic"
    if not target_institution:
        require_institution_match = False
    if workflow == "comparison_guidance":
        # Comparison and application-targeting often require cross-institution retrieval.
        require_institution_match = False

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
        "require_institution_match": require_institution_match,
        "target_institution": target_institution,
        "target_program": target_program,
        "target_level": target_level,
        "max_search_queries": 6 if primary == "academic" else 5,
        "search_retries": 2 if primary in {"academic", "career", "comparison"} else 1,
        "prefer_profile_documents": prefer_profile_documents,
        "governing_state_sources": governing_state_sources,
        "web_research_mode": web_research_mode,
        "targeted_web_questions": targeted_web_questions,
        "max_web_passes": max_web_passes,
    }


def _application_targeting_signals(lowered_query: str) -> dict[str, bool]:
    """Detect broad admission/application targeting intent across many phrasings."""
    apply_verbs = {
        "apply", "admit", "admission", "eligible", "qualify", "shortlist", "target", "fit", "suitable",
    }
    institution_selectors = {
        "which university", "which universities", "where should i apply", "where can i apply",
        "best universities", "top universities", "universities should i apply",
    }
    degree_targets = {
        "phd", "ph.d", "doctoral", "doctorate", "doctor of philosophy", "research program",
    }
    profile_evidence_terms = {
        "transcript", "resume", "profile", "gpa", "cgpa", "research", "publication", "project", "scores",
    }

    has_apply_verb = any(token in lowered_query for token in apply_verbs)
    has_degree_target = any(token in lowered_query for token in degree_targets)
    has_profile_context = any(token in lowered_query for token in profile_evidence_terms)
    has_university_selector = any(phrase in lowered_query for phrase in institution_selectors) or (
        "university" in lowered_query and any(word in lowered_query for word in ("which", "where", "best", "top"))
    )
    has_field_selector = "field" in lowered_query and any(word in lowered_query for word in ("which", "what", "best", "suitable"))

    score = 0
    score += 2 if has_apply_verb else 0
    score += 2 if has_degree_target else 0
    score += 1 if has_profile_context else 0
    score += 1 if has_university_selector else 0
    score += 1 if has_field_selector else 0

    is_application_targeting = score >= 3 and has_degree_target and (has_apply_verb or has_profile_context)
    return {
        "is_application_targeting": is_application_targeting,
        "wants_university_selection": has_university_selector,
        "wants_field_mapping": has_field_selector,
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
    tool_call_log = list(state.get("tool_call_log", []) or [])
    successful_tools = [
        str(item.get("tool", "") or "")
        for item in tool_call_log
        if isinstance(item, dict) and item.get("status") == "ok"
    ]
    if not successful_tools:
        return "direct"

    path = []
    if any(
        name in {
            "get_student_summary",
            "list_entity_types",
            "typed_node_lookup",
            "typed_relation_lookup",
            "fetch_node_by_id",
            "fetch_relation_detail",
            "view_durable_memory_summary",
            "search_memory_semantic",
        }
        for name in successful_tools
    ):
        path.append("graph")
    if any(name in {"search_documents_semantic", "fetch_document_snippet", "list_document_groups"} for name in successful_tools):
        path.append("docs")
    if any(name in {"search_web", "fetch_url", "find_official_sources"} for name in successful_tools):
        path.append("web")
    if state.get("confidence_score") is not None:
        path.append("validated")
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
    graduate_score, undergraduate_score = _academic_level_scores(" ".join(texts).lower())
    if graduate_score >= 2 and graduate_score > undergraduate_score:
        return "graduate"
    if undergraduate_score >= 2 and undergraduate_score > graduate_score:
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
    institution_text: str = "",
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
    if keywords and not overlap:
        score -= 0.9

    if looks_like_course_catalog_source(title, url) and overlap:
        score += 0.6

    graduate_score, undergraduate_score = _academic_level_scores(combined)

    if level == "graduate":
        if graduate_score >= 1:
            score += 0.8
        if undergraduate_score >= 2 and graduate_score == 0:
            score -= 1.3
    elif level == "undergraduate":
        if undergraduate_score >= 1:
            score += 0.7
        if graduate_score >= 2 and undergraduate_score == 0:
            score -= 1.0

    score += institution_alignment_score(title, content, url, institution_text)

    return score


def is_academic_source_relevant(
    title: str,
    content: str,
    url: str,
    program_text: str,
    level: str,
    institution_text: str = "",
) -> bool:
    """Return True when an academic source is sufficiently relevant to the student's program."""
    return academic_source_relevance(title, content, url, program_text, level, institution_text) >= 1.0


def institution_alignment_score(
    title: str,
    content: str,
    url: str,
    institution_text: str,
) -> float:
    """Score how well a source aligns with the target institution context."""
    institution = (institution_text or "").strip().lower()
    if not institution:
        return 0.0

    combined = " ".join([title or "", content[:900] if content else "", url or ""]).lower()
    target_tokens = _institution_keywords(institution)
    target_signature_tokens = _institution_signature_tokens(institution)
    if not target_tokens:
        return 0.0

    overlap = [token for token in target_tokens if token in combined]
    score = min(1.8, 0.7 * len(overlap))

    if target_signature_tokens:
        matched_signature = [token for token in target_signature_tokens if token in combined]
        signature_ratio = len(matched_signature) / max(1, len(target_signature_tokens))
        score += 1.2 * signature_ratio
        if signature_ratio < 0.4:
            score -= 0.9

    target_acronym = _institution_acronym(institution)
    normalized_combined = combined.replace("-", "").replace("_", "")
    if target_acronym:
        if target_acronym in normalized_combined:
            score += 0.6
        elif re.search(r"\bcsu[a-z]{1,3}\b", normalized_combined) and target_acronym.startswith("csu"):
            score -= 1.0

    mentioned_institutions = {
        " ".join(match.group(1).split()).strip(" ,.-").lower()
        for match in _INSTITUTION_RE.finditer(combined)
    }
    target_overlap_found = False
    for mentioned in mentioned_institutions:
        mentioned_tokens = _institution_keywords(mentioned)
        if set(mentioned_tokens) & set(target_tokens):
            target_overlap_found = True
            continue
        if mentioned_tokens:
            score -= 1.2

    if mentioned_institutions and not target_overlap_found and not overlap:
        score -= 0.8

    return score


def _institution_keywords(text: str) -> list[str]:
    ignore = {
        "university", "college", "institute", "school",
        "state", "california", "the", "of", "at", "and",
    }
    tokens: list[str] = []
    for token in re.findall(r"[a-z]{3,}", text.lower()):
        if token in ignore or token in tokens:
            continue
        tokens.append(token)
    return tokens


def _institution_signature_tokens(text: str) -> list[str]:
    """Return stronger institution tokens for context matching."""
    ignore = {"university", "college", "institute", "school", "the", "of", "at", "and"}
    tokens: list[str] = []
    for token in re.findall(r"[a-z]{3,}", text.lower()):
        if token in ignore or token in tokens:
            continue
        tokens.append(token)
    return tokens


def _institution_acronym(text: str) -> str:
    words = [
        word
        for word in re.findall(r"[A-Za-z]+", text.lower())
        if word not in {"the", "of", "at", "and"}
    ]
    if not words:
        return ""
    return "".join(word[0] for word in words)[:6]


def looks_like_course_catalog_source(title: str, url: str) -> bool:
    combined = f"{title} {url}".lower()
    return any(
        phrase in combined
        for phrase in ("courses-a-z", "course catalog", "course descriptions", "/courses/", "/catalog/", "/academics/", " class schedule ")
    )


def course_code_matches_level(
    code: str,
    level: str,
    title: str = "",
    content: str = "",
) -> bool:
    """Conservatively filter only when there is strong evidence of a level mismatch."""
    normalized_level = str(level or "").strip().lower()
    if normalized_level not in {"graduate", "undergraduate"}:
        return True

    match = re.search(r"(\d{3})", code or "")
    if not match:
        return True

    number = int(match.group(1))
    combined = f"{title} {content}".lower()
    if number >= 100:
        return True
    graduate_score, undergraduate_score = _academic_level_scores(combined)
    if any(token in combined for token in ("prereq", "prerequisite", "foundation", "deficien", "admission", "requirement")):
        return True
    if normalized_level == "graduate":
        if graduate_score >= 1:
            return True
        if undergraduate_score >= 2:
            return False
    elif normalized_level == "undergraduate":
        if undergraduate_score >= 1:
            return True
        if graduate_score >= 2 and any(token in combined for token in ("graduate only", "doctoral", "masters", "phd")):
            return False
    return True


def _academic_level_scores(text: str) -> tuple[int, int]:
    lowered = str(text or "").lower()
    graduate_score = 0
    undergraduate_score = 0

    graduate_terms = (
        "graduate", "master", "masters", "doctoral", "doctorate", "phd", "ph.d",
        "postgraduate", "post-grad", "graduate diploma", "m.s", "m.eng", "m.tech", "mba",
    )
    undergraduate_terms = (
        "undergraduate", "bachelor", "bachelors", "baccalaureate", "associate",
        "freshman", "sophomore", "junior", "senior", "year 1", "year 2", "year 3", "year 4",
        "minor", "major", "b.s", "b.a", "b.tech",
    )

    for term in graduate_terms:
        if term in lowered:
            graduate_score += 1
    for term in undergraduate_terms:
        if term in lowered:
            undergraduate_score += 1

    if re.search(r"\bms\b", lowered):
        graduate_score += 1
    if re.search(r"\bbs\b", lowered):
        undergraduate_score += 1

    return graduate_score, undergraduate_score


def _contains_any_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(term)}\b", text or "", re.I) for term in terms)


def _to_text(value: Any) -> str:
    """Normalize unknown values (including bytes) to safe strings."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    if value is None:
        return ""
    return str(value)


def _is_official_domain(domain: str) -> bool:
    normalized = (domain or "").strip().lower()
    if not normalized:
        return False
    if normalized.endswith(".edu") or normalized.endswith(".gov"):
        return True
    return bool(re.search(r"\.ac\.[a-z]{2,}$", normalized))


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
        blockers.append("No completed courses are recorded yet for the current academic stage.")
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
