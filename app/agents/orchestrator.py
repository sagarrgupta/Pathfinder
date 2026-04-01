"""Node 2: Orchestrator.

Classifies user intent, checks what data is available, and creates an
execution plan (ordered list of nodes to invoke).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage

from app.adapters.llm.lmstudio import get_text_llm
from app.adapters.neo4j.graph_store import get_full_profile
from app.core.prompts import ORCHESTRATOR_SYSTEM_PROMPT
from app.core.quality import (
    add_handoff_note,
    analyze_query_focus,
    build_session_summary,
    infer_target_entity,
    build_source_policy,
    build_task_graph,
    compact_session_state,
    infer_student_workflow,
    init_working_memory,
    build_short_memory_policy,
    complete_task,
    start_task,
    fail_task,
)
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.orchestrator")


async def orchestrator(state: PathfinderState) -> PathfinderState:
    """Classify intent and create an execution plan."""
    query = state.get("query", "")
    files = state.get("files", [])
    student_id = state.get("student_id", "default")
    messages = state.get("messages", [])

    step_progress = list(state.get("step_progress", []))
    step_progress.append("Analyzing your question...")

    llm = get_text_llm()

    # Pre-check: does the student have profile data in Neo4j?
    try:
        existing_profile = await get_full_profile(student_id)
        has_profile = bool(
            existing_profile.get("courses")
            or existing_profile.get("skills")
            or existing_profile.get("goals")
            or existing_profile.get("personal", {}).get("name")
        )
        if has_profile:
            profile_summary_parts = []
            personal = existing_profile.get("personal", {})
            if personal.get("name"):
                profile_summary_parts.append(f"Name: {personal['name']}")
            if personal.get("university"):
                profile_summary_parts.append(f"University: {personal['university']}")
            if personal.get("gpa"):
                profile_summary_parts.append(f"GPA: {personal['gpa']}")
            courses = existing_profile.get("courses", [])
            if courses:
                course_names = ", ".join(c.get("name", c.get("code", "?")) for c in courses[:5])
                profile_summary_parts.append(f"{len(courses)} course(s): {course_names}")
            else:
                profile_summary_parts.append("No courses recorded yet")
            skills = existing_profile.get("skills", [])
            if skills:
                skill_names = ", ".join(s.get("name", "") for s in skills[:5])
                profile_summary_parts.append(f"Skills: {skill_names}")
            goals = existing_profile.get("goals", [])
            if goals:
                goal_names = ", ".join(g.get("name", "") for g in goals[:3])
                profile_summary_parts.append(f"Goals: {goal_names}")
            profile_context = "Student has profile data in database: " + "; ".join(profile_summary_parts)
        else:
            profile_context = "Student has no profile data yet — profile_manager will return empty."
    except Exception:
        has_profile = False
        profile_context = "Could not check profile status."

    # Build context about what data we have
    context_parts = []
    if files:
        context_parts.append(f"User uploaded {len(files)} file(s): {[f.get('filename', 'unknown') for f in files]}")
    context_parts.append(profile_context)

    # Add conversation history for follow-up awareness
    if len(messages) > 1:
        # Summarize recent conversation turns (skip current query)
        history_lines = []
        for msg in messages[:-1]:  # Everything except the current message
            if isinstance(msg, tuple):
                role, content = msg
                history_lines.append(f"{role}: {content[:150]}")
            elif hasattr(msg, "content"):
                role = getattr(msg, "type", "unknown")
                history_lines.append(f"{role}: {msg.content[:150]}")
        if history_lines:
            context_parts.append("Recent conversation:\n" + "\n".join(history_lines[-6:]))

    # Detect URLs in query
    if "http" in query.lower():
        context_parts.append("NOTE: The query contains URL(s) — web_researcher can fetch page content directly.")

    context = "\n".join(context_parts)

    response = await llm.ainvoke([
        SystemMessage(content=ORCHESTRATOR_SYSTEM_PROMPT),
        HumanMessage(content=f"Context:\n{context}\n\nUser query: {query}"),
    ])

    # Parse the LLM response
    try:
        content = response.content
        # Try to extract JSON from the response
        json_start = content.find("{")
        json_end = content.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            parsed = json.loads(content[json_start:json_end])
        else:
            parsed = {"intent": "general", "plan": ["profile_manager"], "missing_info": []}
    except (json.JSONDecodeError, AttributeError):
        log.warning("Failed to parse orchestrator response, using defaults")
        parsed = {"intent": "general", "plan": ["profile_manager"], "missing_info": []}

    intent = parsed.get("intent", "general")
    plan = parsed.get("plan", [])
    missing_info = parsed.get("missing_info", [])
    profile_snapshot = existing_profile if 'existing_profile' in locals() else {}
    session_summary = build_session_summary(profile_snapshot, messages, query)
    query_focus = analyze_query_focus(query)
    target_entity = infer_target_entity(profile_snapshot, session_summary, query, query_focus)
    workflow = infer_student_workflow(query, query_focus, files, target_entity)
    source_policy = build_source_policy(query_focus, target_entity, workflow)
    short_memory_policy = build_short_memory_policy(workflow, query_focus)
    task_graph = build_task_graph(query, workflow, query_focus, target_entity)
    task_graph = start_task(task_graph, "determine_decision_goal")
    task_graph = complete_task(task_graph, "determine_decision_goal")
    working_memory = init_working_memory(state.get("working_memory", {}))
    compacted_session = compact_session_state(session_summary, working_memory)

    # ── Guardrail: ensure profile_manager is included for personal queries ──
    personal_intents = {"academic", "career", "interview", "profile"}
    if intent in personal_intents and "profile_manager" not in plan:
        plan.insert(0, "profile_manager")
        log.info("Guardrail: inserted profile_manager for %s intent", intent)

    query_lower = query.lower()

    # ── Guardrail: include web_researcher for every turn-level plan ──
    if "web_researcher" not in plan:
        advisory = {"academic_advisor", "career_planner", "interview_prep"}
        insert_idx = len(plan)
        for i, node in enumerate(plan):
            if node in advisory:
                insert_idx = i
                break
        plan.insert(insert_idx, "web_researcher")
        log.info("Guardrail: inserted web_researcher for all workflows")

    # ── Guardrail: web_researcher must come before advisory agents ──
    if "web_researcher" in plan:
        wr_idx = plan.index("web_researcher")
        advisory_agents_for_order = {"academic_advisor", "career_planner", "interview_prep"}
        for agent in advisory_agents_for_order:
            if agent in plan:
                agent_idx = plan.index(agent)
                if agent_idx < wr_idx:
                    # Move web_researcher before this agent
                    plan.remove("web_researcher")
                    plan.insert(agent_idx, "web_researcher")
                    log.info("Guardrail: moved web_researcher before %s", agent)
                    break

    # ── Guardrail: profile_manager must come before advisory agents ──
    advisory_agents = {"academic_advisor", "program_advisor", "course_planner", "career_planner", "career_matcher", "interview_prep"}
    if "profile_manager" in plan:
        pm_idx = plan.index("profile_manager")
        for agent in advisory_agents:
            if agent in plan:
                agent_idx = plan.index(agent)
                if agent_idx < pm_idx:
                    plan.remove("profile_manager")
                    plan.insert(agent_idx, "profile_manager")
                    break

    # ── Guardrail: URL queries must include web_researcher ──
    if "http" in query_lower and "web_researcher" not in plan:
        plan.insert(0 if "profile_manager" not in plan else plan.index("profile_manager") + 1, "web_researcher")
        log.info("Guardrail: inserted web_researcher for URL query")

    workflow_plan = _plan_for_workflow(workflow, plan)
    if workflow_plan:
        plan = workflow_plan
        if workflow in {"academic_planning", "program_understanding", "eligibility_check", "comparison_guidance", "document_guidance"}:
            intent = "academic"
        elif workflow == "career_alignment":
            intent = "career"

    dependency_gate = _dependency_gate(workflow, state.get("dependency_status", {}))
    if dependency_gate:
        blocked_reasons = [dependency_gate]
        task_graph = fail_task(task_graph, "determine_decision_goal", reason=dependency_gate)
        working_memory = add_handoff_note(
            working_memory,
            from_node="orchestrator",
            to_node="responder",
            contract="dependency_gate",
            summary=dependency_gate,
        )
        step_progress.append("Dependency check failed — returning actionable runtime error")
        return {
            **state,
            "intent": intent,
            "plan": [],
            "next_node": "responder",
            "missing_info": missing_info,
            "session_summary": session_summary,
            "workflow": workflow,
            "target_entity": target_entity,
            "source_policy": source_policy,
            "task_graph": task_graph,
            "working_memory": working_memory,
            "compacted_session": compacted_session,
            "blocked_reasons": blocked_reasons,
            "stop_reason": "dependency_unavailable",
            "short_memory_policy": short_memory_policy,
            "draft_answer": dependency_gate,
            "step_progress": step_progress,
        }

    # Determine next node
    if intent == "greeting":
        next_node = "responder"
    elif plan:
        next_node = plan[0]
    else:
        next_node = "responder"

    _plan_labels = {
        "profile_manager": "Profile",
        "web_researcher": "Research",
        "fact_extractor": "Facts",
        "academic_advisor": "Academic",
        "program_advisor": "Program",
        "course_planner": "Courses",
        "career_planner": "Career",
        "career_matcher": "Career",
        "interview_prep": "Interview",
        "doc_analyst": "Documents",
        "clarifier": "Clarify",
    }
    plan_display = " → ".join(_plan_labels.get(p, p) for p in plan) if plan else "direct response"
    step_progress.append(f"Intent: {intent} — Workflow: {workflow} — Plan: {plan_display}")
    log.info("Orchestrator: intent=%s workflow=%s plan=%s next=%s", intent, workflow, plan, next_node)

    working_memory = add_handoff_note(
        working_memory,
        from_node="orchestrator",
        to_node=next_node,
        contract="workflow_plan",
        summary=f"Workflow={workflow}; plan={' -> '.join(plan) if plan else 'responder'}",
    )

    return {
        **state,
        "intent": intent,
        "plan": plan,
        "next_node": next_node,
        "missing_info": missing_info,
        "session_summary": session_summary,
        "workflow": workflow,
        "target_entity": target_entity,
        "source_policy": source_policy,
        "task_graph": task_graph,
        "working_memory": working_memory,
        "compacted_session": compacted_session,
        "short_memory_policy": short_memory_policy,
        "stop_reason": "",
        "step_progress": step_progress,
    }


def _workflow_needs_web_research(workflow: str, source_policy: dict[str, Any]) -> bool:
    if workflow == "student_state_update":
        return False
    if workflow in {"academic_planning", "program_understanding", "eligibility_check", "comparison_guidance", "career_alignment", "document_guidance"}:
        return True
    return bool(source_policy.get("requires_live_data")) or bool(source_policy.get("primary_source_types"))


def _is_course_planning_query(query_lower: str) -> bool:
    keywords = [
        "which courses", "what courses", "next semester", "enroll",
        "register", "take next", "course plan", "semester plan",
    ]
    return any(keyword in query_lower for keyword in keywords)


def _plan_for_workflow(workflow: str, plan: list[str]) -> list[str]:
    workflow_nodes = {
        "academic_planning": ["profile_manager", "web_researcher", "fact_extractor", "course_planner"],
        "program_understanding": ["profile_manager", "web_researcher", "fact_extractor", "program_advisor"],
        "eligibility_check": ["profile_manager", "web_researcher", "fact_extractor", "eligibility_reasoner"],
        "comparison_guidance": ["profile_manager", "web_researcher", "fact_extractor", "program_advisor"],
        "career_alignment": ["profile_manager", "web_researcher", "fact_extractor", "career_matcher"],
        "document_guidance": ["doc_analyst", "profile_manager", "web_researcher", "fact_extractor", "program_advisor"],
        "student_state_update": ["profile_manager", "web_researcher", "evaluator"],
        "general_guidance": _merge_ordered_plan(plan, ["profile_manager", "web_researcher"]),
    }
    ordered = workflow_nodes.get(workflow, plan or ["profile_manager"])
    if workflow in workflow_nodes and workflow != "general_guidance":
        # Keep workflow plans deterministic and dependency-safe.
        return ordered
    return _merge_ordered_plan(plan, ordered)


def _dependency_gate(workflow: str, dependency_status: dict[str, Any]) -> str:
    llm_status = str(dependency_status.get("llm", "unknown"))
    if llm_status != "connected":
        return (
            "LLM runtime is unavailable right now, so I cannot complete this advising turn. "
            "Please restart LM Studio and retry."
        )

    neo4j_status = str(dependency_status.get("neo4j", "unknown"))
    if neo4j_status != "connected":
        return (
            "Neo4j is unavailable, so profile/memory-backed advising is blocked. "
            "Please restart Neo4j and retry."
        )

    embeddings_status = str(dependency_status.get("embeddings", "unknown"))
    if workflow in {"academic_planning", "program_understanding", "eligibility_check", "comparison_guidance", "career_alignment", "document_guidance"} and embeddings_status != "connected":
        return (
            "Embedding service is unavailable, so evidence retrieval is blocked. "
            "Please start Ollama (embeddings) and retry."
        )

    return ""


def _ensure_quality_course_plan(plan: list[str]) -> list[str]:
    ordered = ["profile_manager", "web_researcher", "fact_extractor", "course_planner"]
    merged = _merge_ordered_plan(plan, ordered)
    return [item for item in merged if item not in {"program_advisor", "academic_advisor"}]


def _ensure_academic_fact_plan(plan: list[str]) -> list[str]:
    ordered = ["profile_manager", "web_researcher", "fact_extractor", "program_advisor"]
    return _merge_ordered_plan(plan, ordered)


def _merge_ordered_plan(plan: list[str], ordered: list[str]) -> list[str]:
    merged = []
    seen = set()
    for item in ordered + plan:
        if item not in seen:
            seen.add(item)
            merged.append(item)
    return merged


def _replace_agent(plan: list[str], old: str, new: str) -> list[str]:
    replaced = [new if item == old else item for item in plan]
    if new not in replaced:
        replaced.append(new)
    deduped = []
    seen = set()
    for item in replaced:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped
