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
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.orchestrator")

_SYSTEM_PROMPT = """You are the Orchestrator of Pathfinder, an AI academic and career guidance system.

Your job is to analyze the user's query and decide which specialist agents should handle it.

Available agents:
- clarifier: Ask the user for more information when the query is ambiguous or missing key details
- doc_analyst: Process uploaded documents (PDFs) — extract text, create chunks, extract entities
- profile_manager: Query or update the student's knowledge graph profile (courses, skills, GPA, etc.)
- web_researcher: Search the web for external information (university requirements, job postings, courses available, etc.)
- academic_advisor: Provide academic guidance (major selection, course planning, university comparison)
- career_planner: Provide career guidance (job matching, skill gap analysis, career paths)
- interview_prep: Help with interview preparation (mock questions, answer feedback, company research)

Analyze the user's query and respond with a JSON object:
{
    "intent": "academic|career|interview|document|profile|general|greeting",
    "plan": ["agent1", "agent2", ...],
    "missing_info": [],
    "reasoning": "brief explanation of your routing decision"
}

Rules:
1. If the user uploaded files, ALWAYS include "doc_analyst" first.
2. If the query references anything personal (grades, skills, GPA, courses, profile, university, name, "my", "I"), include "profile_manager" FIRST.
3. If the query asks about specific courses, programs, universities, job listings, or anything factual that could be looked up, include "web_researcher".
4. Only route to "clarifier" if the query is genuinely ambiguous AND profile data cannot help resolve it.
5. For greetings or simple chat (like "hello", "hi", "thanks"), return intent "greeting" with an empty plan.
6. Always think about what information is needed and which agents provide it.
7. Profile_manager MUST come before agents that need profile data (academic_advisor, career_planner, interview_prep).
8. For academic, career, or interview queries, ALWAYS include profile_manager in the plan even if no profile is loaded yet — it will fetch data from the database.
9. NEVER return just ["clarifier"] if the student has profile data available.
10. For course recommendations or university comparisons, ALWAYS include "web_researcher" to get real, up-to-date information.
"""


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

    context = "\n".join(context_parts)

    # #region agent log
    import os, json as _json
    _log_path = "/Users/sagargupta/Library/CloudStorage/OneDrive-CaliforniaStateUniversity,Sacramento/Courses/CSC-500-Master's Project/Implementation-code copy/.cursor/debug.log"
    with open(_log_path, "a") as _f:
        _f.write(_json.dumps({"location": "orchestrator.py:entry", "message": "Orchestrator context", "data": {"query": query, "profile_context": profile_context, "has_profile": has_profile}, "hypothesisId": "A", "timestamp": __import__("time").time()}) + "\n")
    # #endregion

    response = await llm.ainvoke([
        SystemMessage(content=_SYSTEM_PROMPT),
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

    # Determine next node
    if intent == "greeting":
        next_node = "responder"
    elif plan:
        next_node = plan[0]
    else:
        next_node = "responder"

    # #region agent log
    with open(_log_path, "a") as _f:
        _f.write(_json.dumps({"location": "orchestrator.py:exit", "message": "Orchestrator decision", "data": {"intent": intent, "plan": plan, "next_node": next_node, "missing_info": missing_info, "raw_response": content[:500]}, "hypothesisId": "B", "timestamp": __import__("time").time()}) + "\n")
    # #endregion

    step_progress.append(f"Intent: {intent} — Plan: {' → '.join(plan) if plan else 'direct response'}")
    log.info("Orchestrator: intent=%s plan=%s next=%s", intent, plan, next_node)

    return {
        **state,
        "intent": intent,
        "plan": plan,
        "next_node": next_node,
        "missing_info": missing_info,
        "step_progress": step_progress,
    }
