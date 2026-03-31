"""Capability agent: convert reasoning into next-step actions and follow-up loops."""

from __future__ import annotations

import datetime as dt

from langchain_core.messages import HumanMessage, SystemMessage

from app.adapters.llm.lmstudio import get_text_llm
from app.adapters.neo4j.graph_store import store_memory_item
from app.core.state import PathfinderState

_PROMPT = """Create a short action plan and follow-up loop for the student.

Return ONLY JSON:
{
  "title": "short title",
  "actions": ["...", "...", "..."],
  "follow_up_prompt": "one sentence the system can ask later",
  "priority": 0.0 to 1.0
}

Rules:
- Actions must be concrete and student-facing.
- Keep 2-4 actions.
- The follow-up prompt should help the student resume progress in a later session.
"""


async def plan_action_agent(state: PathfinderState) -> PathfinderState:
    """Build an action plan and save it for future cross-session follow-up."""
    query = state.get("query", "")
    llm = get_text_llm()
    response = await llm.ainvoke(
        [
            SystemMessage(content=_PROMPT),
            HumanMessage(
                content=(
                    f"Question: {query}\n"
                    f"Intent: {state.get('intent', 'general')}\n"
                    f"Missing info: {state.get('missing_info', [])}\n"
                    f"Rationale: {state.get('answer_rationale', [])}\n"
                    f"Draft answer: {state.get('draft_answer', '')[:2500]}"
                )
            ),
        ]
    )
    content = response.content if isinstance(response.content, str) else str(response.content)
    title = query[:120] or "Saved plan"
    actions = list(state.get("recommended_actions", []))
    follow_up_prompt = ""
    priority = 0.75
    try:
        import json

        json_start = content.find("{")
        json_end = content.rfind("}") + 1
        parsed = json.loads(content[json_start:json_end])
        title = parsed.get("title") or title
        actions = parsed.get("actions") or actions
        follow_up_prompt = parsed.get("follow_up_prompt", "")
        priority = float(parsed.get("priority", priority))
    except Exception:
        if not actions:
            actions = [
                f"Review the recommendation against your current goal: {query[:80]}",
                "Validate any specifics against cited sources before acting",
                "Return with updated progress so Pathfinder can refine the plan",
            ]
        follow_up_prompt = "What progress have you made on the last plan, and what should we adjust next?"

    actions = actions[:4]
    next_review_at = (dt.datetime.utcnow() + dt.timedelta(days=7)).isoformat() + "Z"
    step_progress = list(state.get("step_progress", []))
    step_progress.append("Built action-oriented next steps")
    saved = await store_memory_item(
        state.get("student_id", ""),
        "saved_plan",
        f"Plan for: {title}",
        source_ref=state.get("session_id"),
        confidence=max(0.6, float(state.get("confidence_score", 0.65) or 0.65)),
        salience=max(0.75, min(1.0, priority)),
        status="resolved",
        time_scope="long_term",
        tags=["plan", "follow_up", state.get("intent", "general"), state.get("task_type", "general")],
        metadata={
            "title": title,
            "actions": actions,
            "source_query": query,
            "source_session_id": state.get("session_id"),
            "status": "active",
            "follow_up_prompt": follow_up_prompt,
            "next_review_at": next_review_at,
            "priority": priority,
        },
    )
    execution_trace = list(state.get("execution_trace", []))
    execution_trace.append(
        {
            "agent": "plan_action_agent",
            "saved_plan_id": saved.get("id"),
            "next_review_at": next_review_at,
        }
    )
    return {
        **state,
        "recommended_actions": actions,
        "step_progress": step_progress,
        "execution_trace": execution_trace,
    }
