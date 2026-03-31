"""Node 2: Orchestrator.

Classifies user intent, checks what data is available, and creates an
execution plan (ordered list of nodes to invoke).
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage

from app.adapters.llm.lmstudio import get_text_llm
from app.adapters.neo4j.graph_store import get_full_profile
from app.core.state import PathfinderState
from app.prompts import Prompts
from app.utils.json_llm import parse_json_object

log = logging.getLogger("pathfinder.agents.orchestrator")


async def orchestrator(state: PathfinderState) -> PathfinderState:
    """Classify intent and create an execution plan."""
    query = state.get("query", "")
    files = state.get("files", [])
    student_id = state.get("student_id", "default")

    step_progress = list(state.get("step_progress", []))
    step_progress.append("Analyzing your question...")

    llm = get_text_llm()

    # Pre-check: does the student have profile data in Neo4j?
    try:
        existing_profile = await get_full_profile(student_id)
        all_ent = existing_profile.get("all_entities") or {}
        has_profile = bool(
            existing_profile.get("courses")
            or existing_profile.get("skills")
            or existing_profile.get("goals")
            or existing_profile.get("personal", {}).get("name")
            or any(all_ent.values())
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
    messages = state.get("messages", [])
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
        SystemMessage(content=Prompts.ORCHESTRATOR_SYSTEM),
        HumanMessage(content=f"Context:\n{context}\n\nUser query: {query}"),
    ])

    # Parse the LLM response
    try:
        content = response.content
        content_str = content if isinstance(content, str) else str(content)
        parsed = parse_json_object(content_str)
        if not parsed:
            parsed = {"intent": "general", "plan": ["profile_manager"], "missing_info": []}
    except AttributeError:
        log.warning("Failed to parse orchestrator response, using defaults")
        parsed = {"intent": "general", "plan": ["profile_manager"], "missing_info": []}

    intent = parsed.get("intent", "general")
    plan = parsed.get("plan", [])
    missing_info = parsed.get("missing_info", [])

    # ── Guardrail: ensure profile_manager is included for personal queries ──
    personal_intents = {"academic", "career", "interview", "profile"}
    if intent in personal_intents and "profile_manager" not in plan:
        plan.insert(0, "profile_manager")
        log.info("Guardrail: inserted profile_manager for %s intent", intent)

    # ── Guardrail: include web_researcher for recommendation queries ──
    recommendation_keywords = ["course", "recommend", "next semester", "should i take",
                               "university", "compare", "job", "position", "available"]
    query_lower = query.lower()
    if any(kw in query_lower for kw in recommendation_keywords):
        if "web_researcher" not in plan:
            # Insert web_researcher before advisory agents
            advisory = {"academic_advisor", "career_planner", "interview_prep"}
            insert_idx = len(plan)
            for i, node in enumerate(plan):
                if node in advisory:
                    insert_idx = i
                    break
            plan.insert(insert_idx, "web_researcher")
            log.info("Guardrail: inserted web_researcher for recommendation query")

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
    advisory_agents = {"academic_advisor", "career_planner", "interview_prep"}
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

    # ── Guardrail: intent MUST have a matching advisory agent ──
    # Without this, the plan can end at web_researcher with no agent
    # that actually generates a draft_answer.
    _intent_to_agent = {
        "career": "career_planner",
        "academic": "academic_advisor",
        "interview": "interview_prep",
        "research": "academic_advisor",  # research queries get academic_advisor to synthesize
    }
    if intent in _intent_to_agent:
        required_agent = _intent_to_agent[intent]
        if required_agent not in plan:
            plan.append(required_agent)
            log.info("Guardrail: inserted %s for %s intent", required_agent, intent)

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
        "academic_advisor": "Academic",
        "career_planner": "Career",
        "interview_prep": "Interview",
        "doc_analyst": "Documents",
        "clarifier": "Clarify",
    }
    plan_display = " → ".join(_plan_labels.get(p, p) for p in plan) if plan else "direct response"
    step_progress.append(f"Intent: {intent} — Plan: {plan_display}")
    log.info("Orchestrator: intent=%s plan=%s next=%s", intent, plan, next_node)

    return {
        **state,
        "intent": intent,
        "plan": plan,
        "next_node": next_node,
        "missing_info": missing_info,
        "step_progress": step_progress,
    }
