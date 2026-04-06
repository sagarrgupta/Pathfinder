"""Node 5: Profile Manager.

Handles all Neo4j knowledge graph interactions:
  - Load student profile
  - Semantic search over document chunks
  - Graph queries for structured data
  - CRUD operations on profile entities
  - Free-text profile input processing
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage

from app.adapters.llm.lmstudio import get_text_llm
from app.adapters.neo4j.graph_store import (
    ensure_student,
    get_full_profile,
    update_student,
)
from app.adapters.neo4j.vector_store import hybrid_search
from app.core.quality import (
    add_handoff_note,
    analyze_query_focus,
    build_evidence_pack,
    derive_decision_continuity,
    derive_recommendation_outcome_profile,
    build_session_memory_state,
    build_session_summary,
    build_source_policy,
    compact_session_state,
    complete_task,
    derive_student_operating_model,
    derive_student_strategy,
    start_task,
    infer_student_workflow,
    infer_target_entity,
    init_working_memory,
)
from app.core.prompts import PROFILE_MANAGER_TEXT_EXTRACTION_PROMPT
from app.core.state import PathfinderState
from app.services.memory_ingestion import ingest_memory
from app.services.retrieval import build_memory_pack
from app.services.runtime_recovery import recovery_for_profile_ingestion_failure
from app.services.transcript_state import primary_transcript_state

log = logging.getLogger("pathfinder.agents.profile_manager")

_PROFILE_SIGNAL_PATTERNS = [
    r"\b(i am|i'm|my name is)\b",
    r"\b(i study at|studying at|student at)\b",
    r"\b(my goal|i want to|i'm aiming for|my preference|i prefer)\b",
    r"\b(my gpa|gpa is|my semester|in my \d{1,2}(st|nd|rd|th)? semester)\b",
    r"\b(skills include|i know|i have experience|completed courses|no courses completed|none courses completed)\b",
]
_PROFILE_FIELD_HINTS = {
    "name",
    "university",
    "college",
    "school",
    "program",
    "major",
    "degree",
    "semester",
    "term",
    "gpa",
    "goal",
    "goals",
    "skills",
    "experience",
    "courses",
    "completed",
    "interests",
    "preference",
    "preferences",
}

_TEXT_EXTRACTION_PROMPT = PROFILE_MANAGER_TEXT_EXTRACTION_PROMPT


async def profile_manager(state: PathfinderState) -> PathfinderState:
    """Load profile, search documents, and enrich state with personal data."""
    query = state.get("query", "")
    student_id = state.get("student_id", "")
    session_id = state.get("session_id", "")

    step_progress = list(state.get("step_progress", []))
    step_progress.append("Checking your academic profile...")
    log.info("Profile manager starting for session=%s student=%s", session_id, student_id)

    # Ensure student exists
    await ensure_student(student_id)

    # In-turn memory ingestion: capture profile signals from the current user query
    # so this same turn can reason over freshly learned facts.
    query_ingested = False
    latest_ingestion_result: dict[str, Any] = {}
    recovery_events = list(state.get("recovery_events", []))
    if _should_ingest_current_query(query):
        try:
            ingest_result = await ingest_memory(
                student_id=student_id,
                source_type="chat_query",
                content=query,
                source_ref=f"chat:{session_id}",
                session_id=session_id,
                metadata={"entrypoint": "profile_manager.current_query", "auto_ingest": True},
            )
            signal_count = (
                len(ingest_result.get("candidate_facts", []))
                + len(ingest_result.get("memory_items", []))
                + len(ingest_result.get("promoted_entities", []))
                + (1 if ingest_result.get("student_updates") else 0)
            )
            if signal_count > 0:
                query_ingested = True
                step_progress.append("Captured profile signals from your current message...")
            latest_ingestion_result = {
                "ingested": True,
                "candidate_facts": len(ingest_result.get("candidate_facts", [])),
                "memory_items": len(ingest_result.get("memory_items", [])),
                "promoted_entities": len(ingest_result.get("promoted_entities", [])),
                "student_updates": sorted(list((ingest_result.get("student_updates", {}) or {}).keys())),
                "consolidation_needed": bool(ingest_result.get("consolidation_needed")),
            }
        except Exception as exc:
            log.warning("Current-query ingestion skipped due to error: %s", exc)
            latest_ingestion_result = {
                "ingested": False,
                "error": str(exc),
            }
            recovery_events.append(
                recovery_for_profile_ingestion_failure("chat_query", str(exc)).as_dict()
            )
    else:
        latest_ingestion_result = {
            "ingested": False,
            "reason": "query_not_profile_signal",
        }

    # Load full profile from KG
    profile = await get_full_profile(student_id)

    # Semantic search over stored documents
    step_progress.append("Searching your documents...")
    retrieved = await hybrid_search(
        query=query,
        k=5,
        student_id=student_id,
        session_id=session_id,
    )

    domain = state.get("intent", "general") or "general"
    memory_pack = await build_memory_pack(
        student_id=student_id,
        domain=domain,
        task_type=state.get("workflow", "general_guidance") or "general_guidance",
        reasoning_depth="standard",
        query=query,
        needs_web=False,
        force_refresh=query_ingested,
        profile_override=profile,
        documents_override=retrieved,
    )
    semantic_memory = memory_pack.get("semantic_memory", {})
    semantic_memory = semantic_memory if isinstance(semantic_memory, dict) else {}
    raw_conflicts = memory_pack.get("conflicts", [])
    conflicts = list(raw_conflicts) if isinstance(raw_conflicts, list) else []
    if not retrieved:
        raw_documents = memory_pack.get("documents", [])
        if isinstance(raw_documents, list) and raw_documents:
            retrieved = list(raw_documents)

    step_progress.append(
        f"Found {len(retrieved)} relevant document chunks, "
        f"{len(profile.get('courses', []))} courses, "
        f"{len(profile.get('skills', []))} skills in your profile"
    )

    log.info(
        "Profile manager: %d chunks, %d courses, %d skills",
        len(retrieved),
        len(profile.get("courses", [])),
        len(profile.get("skills", [])),
    )

    session_summary = build_session_summary(profile, state.get("messages", []), query)
    query_focus = analyze_query_focus(query)
    target_entity = infer_target_entity(profile, session_summary, query, query_focus)
    workflow = state.get("workflow") or infer_student_workflow(
        query,
        query_focus,
        state.get("files", []),
        target_entity,
    )
    student_strategy = derive_student_strategy(session_summary, profile, query)
    student_operating_model = derive_student_operating_model(session_summary, profile, query)
    recommendation_outcome_profile = derive_recommendation_outcome_profile(
        memory_pack.get("saved_recommendations", []) if isinstance(memory_pack.get("saved_recommendations", []), list) else []
    )
    decision_continuity = derive_decision_continuity(
        query,
        memory_pack.get("decision_records", []) if isinstance(memory_pack.get("decision_records", []), list) else [],
    )
    source_policy = build_source_policy(
        query_focus,
        target_entity,
        workflow,
        state.get("source_policy", {}).get("preferred_domains", []),
    )
    source_policy = _govern_source_policy_from_profile(source_policy, workflow, profile, semantic_memory)
    transcript_state = primary_transcript_state(state.get("transcript_states", []), semantic_memory)
    targeted_web_questions = _targeted_web_questions_from_state(
        query=query,
        workflow=workflow,
        profile=profile,
        semantic_memory=semantic_memory,
        transcript_state=transcript_state,
        source_policy=source_policy,
    )
    if targeted_web_questions:
        source_policy["targeted_web_questions"] = targeted_web_questions
    next_node = _determine_next(state)
    working_memory = init_working_memory(state.get("working_memory", {}))
    evidence_pack = build_evidence_pack(
        query=query,
        workflow=workflow,
        student_strategy=student_strategy,
        student_operating_model=student_operating_model,
        recommendation_outcome_profile=recommendation_outcome_profile,
        decision_continuity=decision_continuity,
        profile=profile,
        documents=retrieved,
        web_results=state.get("web_results", []),
        semantic_memory=semantic_memory,
        memory_pack=memory_pack,
        evidence_records=state.get("evidence_records", []),
        working_memory=working_memory,
        missing_information=state.get("missing_info", []),
    )
    working_memory = add_handoff_note(
        working_memory,
        from_node="profile_manager",
        to_node=next_node,
        contract="student_context",
        summary=(
            f"profile_courses={len(profile.get('courses', []))}; "
            f"profile_skills={len(profile.get('skills', []))}; "
            f"doc_chunks={len(retrieved)}"
        ),
    )
    task_graph = state.get("task_graph", [])
    for task_id in ("load_student_state", "load_conversation_state"):
        task_graph = start_task(task_graph, task_id)
    for task_id in ("load_student_state", "load_conversation_state", "determine_decision_goal"):
        task_graph = complete_task(task_graph, task_id)
    log.info("Profile manager completed; next=%s", next_node)
    compacted_session = compact_session_state(
        session_summary,
        working_memory,
        state.get("messages", []),
        state.get("short_memory_policy", {}),
    )

    return {
        **state,
        "profile_data": profile,
        "session_summary": session_summary,
        "target_entity": target_entity,
        "workflow": workflow,
        "student_strategy": student_strategy,
        "student_operating_model": student_operating_model,
        "recommendation_outcome_profile": recommendation_outcome_profile,
        "decision_continuity": decision_continuity,
        "source_policy": source_policy,
        "targeted_web_questions": targeted_web_questions,
        "working_memory": working_memory,
        "task_graph": task_graph,
        "recovery_events": recovery_events,
        "compacted_session": compacted_session,
        "session_memory": build_session_memory_state(
            session_summary,
            compacted_session,
            state.get("short_memory_policy", {}),
        ),
        "retrieved_documents": retrieved,
        "semantic_memory": semantic_memory,
        "memory_pack": memory_pack,
        "evidence_pack": evidence_pack,
        "latest_ingestion_result": latest_ingestion_result,
        "conflicts": conflicts,
        "step_progress": step_progress,
        "next_node": next_node,
    }


def _govern_source_policy_from_profile(
    source_policy: dict[str, Any],
    workflow: str,
    profile: dict[str, Any],
    semantic_memory: dict[str, Any],
) -> dict[str, Any]:
    governed = dict(source_policy) if isinstance(source_policy, dict) else {}
    transcript_present = any(
        str(doc.get("document_role", "") or doc.get("type", "")).strip().lower() == "transcript"
        or "transcript" in str(doc.get("filename", "")).strip().lower()
        for doc in (profile.get("documents", []) or [])
    )
    transcript_state_present = any(
        str(item.get("source_type", "")).strip().lower() == "transcript_state"
        for item in (semantic_memory.get("evidence", []) or [])
    )
    if workflow in {"academic_planning", "eligibility_check"} and (transcript_present or transcript_state_present):
        primary = list(governed.get("primary_source_types", []) or [])
        secondary = list(governed.get("secondary_source_types", []) or [])
        governed["primary_source_types"] = ["profile_doc"] + [item for item in primary if item != "profile_doc"]
        governed["secondary_source_types"] = [item for item in secondary if item != "profile_doc"]
        governed["prefer_profile_documents"] = True
        governed["preferred_document_roles"] = ["transcript", "degree_plan"]
        governed["governing_state_sources"] = ["transcript_state", "profile_state", "official_requirements"]
        governed["strict_primary_only"] = False
        governed["web_research_mode"] = "targeted"
        governed["max_web_passes"] = max(2, int(governed.get("max_web_passes", 1) or 1))
        rationale = str(governed.get("rationale", "") or "").strip()
        governed["rationale"] = (
            f"{rationale} Transcript-backed academic state is available, so uploaded profile documents should govern progression reasoning while official web research validates unresolved gaps."
        ).strip()
    return governed


def _targeted_web_questions_from_state(
    *,
    query: str,
    workflow: str,
    profile: dict[str, Any],
    semantic_memory: dict[str, Any],
    transcript_state: dict[str, Any] | None,
    source_policy: dict[str, Any],
) -> list[str]:
    if workflow not in {"academic_planning", "eligibility_check", "program_understanding"}:
        return []

    transcript_state = transcript_state or {}
    personal = profile.get("personal", {}) or {}
    institution = str(
        source_policy.get("target_institution", "")
        or personal.get("university", "")
        or personal.get("school", "")
        or ""
    ).strip()
    program = str(
        source_policy.get("target_program", "")
        or personal.get("program", "")
        or transcript_state.get("program", "")
        or ""
    ).strip()
    level = str(source_policy.get("target_level", "") or "").strip()

    questions: list[str] = []
    requirement_focus = _requirement_focus_from_query(query, workflow)
    requirement_phrase = _requirement_focus_phrase(requirement_focus)
    if transcript_state:
        questions.append(
            f"What are the official {requirement_phrase} "
            f"for {program or 'this program'} at {institution or 'the target university'}"
            f"{f' ({level})' if level else ''}?"
        )
        for course in (transcript_state.get("planned_courses", []) or [])[:3]:
            code = str(course.get("code", "") or course.get("name", "")).strip()
            if code:
                questions.append(
                    f"What are the official prerequisites, restrictions, sequencing rules, and typical offering details for {code} "
                    f"at {institution or 'the target university'}?"
                )
        milestones = [str(item.get("name", "")).strip() for item in (transcript_state.get("milestones", []) or [])[:2]]
        milestones = [item for item in milestones if item]
        if milestones:
            questions.append(
                f"What official rules, dependencies, or next-step requirements apply after {', '.join(milestones)} "
                f"in {program or 'this program'} at {institution or 'the target university'}?"
            )
    else:
        questions.append(
            f"What are the official {requirement_phrase} for {program or 'the student program'} "
            f"at {institution or 'the target university'}?"
        )

    if workflow == "academic_planning":
        questions.append(
            f"Based on official requirements, what requirement categories remain unresolved for this student question: {query.strip()}?"
        )

    evidence = semantic_memory.get("evidence", []) or []
    if not any(str(item.get("source_type", "")).strip().lower() in {"degree_page", "schedule_page"} for item in evidence):
        questions.append(
            f"Find the most authoritative official catalog or degree-requirements pages for {program or 'the program'} "
            f"at {institution or 'the target university'}."
        )

    deduped: list[str] = []
    seen: set[str] = set()
    for question in questions:
        cleaned = " ".join(question.split()).strip()
        lowered = cleaned.lower()
        if cleaned and lowered not in seen:
            seen.add(lowered)
            deduped.append(cleaned)
    return deduped[:4]


def _requirement_focus_from_query(query: str, workflow: str) -> str:
    lowered = str(query or "").casefold()
    if workflow == "eligibility_check":
        return "eligibility and policy requirements"
    if any(token in lowered for token in ("elective", "specialization", "concentration", "track", "breadth")):
        return "program, elective, and category requirements"
    if any(token in lowered for token in ("apply", "admission", "admit", "application")):
        return "admissions and qualification requirements"
    if any(token in lowered for token in ("graduate", "graduation", "finish", "complete degree", "units")):
        return "completion and graduation requirements"
    return "program progression requirements"


def _requirement_focus_phrase(focus: str) -> str:
    cleaned = " ".join(str(focus or "").split()).strip()
    return cleaned or "program requirements"


async def process_free_text(
    text: str, student_id: str
) -> dict[str, Any]:
    """Process free-text input from the My Profile page.

    Extracts entities and stores them in the KG.
    """
    try:
        result = await ingest_memory(
            student_id=student_id,
            source_type="profile_text",
            content=text,
            metadata={"entrypoint": "profile_manager.process_free_text"},
        )
        return {
            "entities_extracted": len(result.get("candidate_facts", [])) + len(result.get("promoted_entities", [])),
            "student_properties_updated": bool(result.get("student_updates")),
            "memory_items_created": len(result.get("memory_items", [])),
        }
    except Exception as exc:
        log.warning("Profile text ingestion failed, applying fallback updates only: %s", exc)
        fallback_updates = _fallback_student_updates(text)
        if fallback_updates:
            await update_student(student_id, **fallback_updates)
        return {
            "entities_extracted": 0,
            "student_properties_updated": bool(fallback_updates),
            "memory_items_created": 0,
            "warning": "ingestion_failed_fallback_applied",
            "updated_fields": sorted(list(fallback_updates.keys())),
            "recovery_events": [
                recovery_for_profile_ingestion_failure("profile_text", str(exc), fallback_updates).as_dict()
            ],
        }


def _determine_next(state: PathfinderState) -> str:
    """Determine next node after profile management."""
    plan = state.get("plan", [])
    try:
        idx = plan.index("profile_manager")
        if idx + 1 < len(plan):
            return plan[idx + 1]
    except ValueError:
        pass
    return "evaluator"


def _should_ingest_current_query(query: str) -> bool:
    """Only ingest current-turn messages that likely carry reusable student facts."""
    text = (query or "").strip()
    if len(text.split()) < 5:
        return False
    lowered = text.casefold()
    if lowered.endswith("?") and " my " not in f" {lowered} " and " i " not in f" {lowered} ":
        return False
    if any(re.search(pattern, lowered) for pattern in _PROFILE_SIGNAL_PATTERNS):
        return True
    return _looks_like_semistructured_profile_blob(text)


def _looks_like_semistructured_profile_blob(text: str) -> bool:
    """Detect key-value/list style profile dumps shared by students."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False

    structured_hits = 0
    for line in lines:
        key_match = re.match(r"^([A-Za-z][A-Za-z _/-]{1,30})\s*:\s*(.+)$", line)
        if key_match:
            key = key_match.group(1).strip().casefold()
            if key in _PROFILE_FIELD_HINTS:
                structured_hits += 1
                continue
        if re.match(r"^[-*]\s+.+$", line):
            lowered = line.casefold()
            if any(hint in lowered for hint in _PROFILE_FIELD_HINTS):
                structured_hits += 1
                continue

    token_count = len(text.split())
    return structured_hits >= 2 or (structured_hits >= 1 and token_count >= 20)


def _fallback_student_updates(text: str) -> dict[str, Any]:
    """Best-effort extraction of core student fields when full ingestion fails."""
    raw = (text or "").strip()
    if not raw:
        return {}
    lowered = raw.casefold()
    updates: dict[str, Any] = {}

    name_match = re.search(r"\bmy name is\s+([A-Za-z][A-Za-z .'-]{1,80})", raw, flags=re.IGNORECASE)
    if name_match:
        updates["name"] = name_match.group(1).strip()

    uni_match = re.search(r"\b(?:university|college|school)\s*[:\-]\s*([^\n.;]{3,120})", raw, flags=re.IGNORECASE)
    if uni_match:
        updates["university"] = uni_match.group(1).strip()

    program_match = re.search(r"\b(?:program|major|degree)\s*[:\-]\s*([^\n.;]{2,120})", raw, flags=re.IGNORECASE)
    if program_match:
        updates["program"] = program_match.group(1).strip()

    gpa_match = re.search(r"\bgpa\s*(?:is|=|:)?\s*([0-4](?:\.\d{1,2})?)", lowered)
    if gpa_match:
        updates["gpa"] = gpa_match.group(1)

    semester_match = re.search(r"\b(?:semester)\s*[:\-]\s*([^\n.;]{2,60})", raw, flags=re.IGNORECASE)
    if semester_match:
        updates["semester"] = semester_match.group(1).strip()
    elif "first semester" in lowered:
        updates["semester"] = "first semester"

    return updates
