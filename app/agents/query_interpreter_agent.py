"""Capability agent: compact query understanding before triage."""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.system_context import build_step_system_prompt
from app.adapters.llm.lmstudio import get_text_llm
from app.core.state import PathfinderState

_PROMPT = build_step_system_prompt(
    step_name="query_interpreter",
    objective=(
        "Understand the user's request, preserve the original meaning, and provide a compact expanded helper query "
        "plus structured intent cues for later steps."
    ),
    relevant_capabilities=(
        "profile_memory_agent",
        "document_evidence_agent",
        "web_researcher",
        "academic_strategy_agent",
        "career_strategy_agent",
        "interview_coach_agent",
        "decision_comparison_agent",
    ),
    extra_rules=(
        "Never replace the original user query; only provide helper interpretation fields.",
        "Do not invent facts about the student.",
        "expanded_query should stay close to the user's meaning, but can add concise implied context.",
        "goal should describe what successful help looks like for this turn.",
        "constraints should be short phrases and only include constraints reasonably implied by the message.",
        "search_brief should be empty unless external research might be useful.",
        "For greetings or tiny chat, keep expanded_query very close to the original and leave most fields empty.",
    ),
    output_schema="""
Return ONLY JSON:
{
  "expanded_query": "short helper rewrite",
  "goal": "short goal",
  "constraints": ["short constraint"],
  "search_brief": "short web-research brief or empty string",
  "notes": "short interpretation note"
}
""",
)


def _fallback(query: str) -> dict[str, object]:
    return {
        "expanded_query": query.strip(),
        "goal": "",
        "constraints": [],
        "search_brief": "",
        "notes": "",
    }


async def query_interpreter_agent(state: PathfinderState) -> PathfinderState:
    query = state.get("query", "")
    step_progress = list(state.get("step_progress", []))
    step_progress.append("Understanding your request...")

    parsed = _fallback(query)
    try:
        llm = get_text_llm()
        response = await llm.ainvoke(
            [
                SystemMessage(content=_PROMPT),
                HumanMessage(content=query[:2000]),
            ]
        )
        content = response.content if isinstance(response.content, str) else str(response.content)
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            raw = json.loads(content[start:end])
            constraints = raw.get("constraints", [])
            if not isinstance(constraints, list):
                constraints = []
            parsed = {
                "expanded_query": str(raw.get("expanded_query", query)).strip() or query.strip(),
                "goal": str(raw.get("goal", "")).strip(),
                "constraints": [str(item).strip() for item in constraints if str(item).strip()][:4],
                "search_brief": str(raw.get("search_brief", "")).strip(),
                "notes": str(raw.get("notes", "")).strip(),
            }
    except Exception:
        pass

    step_progress.append("Request understanding ready")
    return {
        **state,
        "interpreted_query": str(parsed["expanded_query"]),
        "interpreted_goal": str(parsed["goal"]),
        "interpreted_constraints": list(parsed["constraints"]),
        "interpreted_search_brief": str(parsed["search_brief"]),
        "interpretation_notes": str(parsed["notes"]),
        "step_progress": step_progress,
    }
