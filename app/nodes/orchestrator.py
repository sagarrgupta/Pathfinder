"""Picks which specialist persona should answer this turn.

Pathfinder has three specialist prompts — `academic`, `career`, and
`general`. Instead of hand-written keyword rules (which age badly as the
product grows), we ask the local LLM to score each one on a 0–10 scale
and pick the winner. The scoring prompt is kept tiny so it's fast and
cheap. On failure we fall back to `general`, which is the catch-all.

Downstream, `specialist_runner` reads `state["selected_specialist"]` and
loads the matching system prompt from `app.core.prompts`.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage

from app.adapters.llm.lmstudio import get_text_llm
from app.adapters.neo4j.graphDB import GraphDB
from app.core.state import PathfinderState
from app.tools.graph_tools import get_driver as get_graph_driver
from app.utils.json_extract import parse_json_object
from app.utils.progress import add_progress

log = logging.getLogger("pathfinder.agents.orchestrator")

_SPECIALIST_DESCRIPTIONS: dict[str, str] = {
    "academic": (
        "Academic records, degree progress, institutional policies, "
        "academic deadlines, courses, grades, graduation requirements, "
        "enrollment, and eligibility."
    ),
    "career": (
        "Career planning, job search, professional development, "
        "skill assessment, market-oriented advice, resume and interview help."
    ),
    "general": (
        "Profile management, uploaded documents, cross-domain requests, "
        "greetings, follow-ups, memory-aware questions, and anything "
        "that does not clearly belong to a single specialist."
    ),
}

_ROUTING_PROMPT = """You are a query classifier. Given a student's query and optional context, score how relevant each specialist is on a scale of 0 to 10.

Specialists:
{specialists}

Student query: "{query}"
{context_line}

Return ONLY a JSON object with scores, nothing else:
{{"academic": <0-10>, "career": <0-10>, "general": <0-10>}}"""

_LIGHT_CONVERSATION_RE = re.compile(
    r"^\s*(hi|hello|hey|yo|good morning|good afternoon|good evening|thanks|thank you|bye|goodbye|see you)\b[!. ]*$",
    re.IGNORECASE,
)

async def _llm_route(query: str, context_hint: str) -> dict[str, float]:
    """Ask the LLM to rate how well each specialist fits this query.

    Returns a `{name: score}` mapping. We default to a neutral
    `general=5` on any error so the flow never hard-fails on routing —
    a wrong specialist is recoverable, a crash is not.
    """
    specialists_block = "\n".join(
        f"- {name}: {desc}" for name, desc in _SPECIALIST_DESCRIPTIONS.items()
    )
    context_line = f"Context: {context_hint}" if context_hint else ""
    prompt = _ROUTING_PROMPT.format(
        specialists=specialists_block,
        query=query,
        context_line=context_line,
    )
    try:
        llm = get_text_llm("none")
        result = await llm.ainvoke([HumanMessage(content=prompt)])
        text = result.content if isinstance(result.content, str) else str(result.content)
        parsed = parse_json_object(text)
        if isinstance(parsed, dict):
            scores: dict[str, float] = {}
            for key in ("academic", "career", "general"):
                val = parsed.get(key, 0)
                try:
                    scores[key] = float(val)
                except (TypeError, ValueError):
                    scores[key] = 0.0
            return scores
    except Exception as exc:
        log.warning("LLM routing failed (%s), falling back to heuristic", exc)
    return {"academic": 0.0, "career": 0.0, "general": 5.0}

async def orchestrator(state: PathfinderState) -> PathfinderState:
    """Score the query against all specialists and pick the winner.

    We hint the router with a few fields from the student's profile so it
    can tell the difference between (say) an academic question from a
    current student and the same wording from someone exploring careers.
    Ties favor `general` since it's the safe fallback.
    """
    query = str(state.get("query", "") or "")
    student_id = str(state.get("student_id", "") or "")

    # Pull a handful of profile fields as routing context. The full profile
    # is never sent here; just enough to disambiguate ambiguous wording.
    student = await GraphDB(await get_graph_driver()).get_student(student_id=student_id) or {}
    fields = [f"{k}={v}" for k, v in list(student.items())[:4] if v]
    context_hint = f"Profile: {', '.join(fields)}" if fields else ""

    routing_scores = await _llm_route(query, context_hint)
    routing_method = "llm"

    # Highest score wins; on a tie, prefer `general` (safer default).
    selected_specialist = max(
        routing_scores.items(),
        key=lambda item: (item[1], item[0] == "general"),
    )[0]
    top_score = float(routing_scores.get(selected_specialist, 0.0) or 0.0)

    # Build a short human-readable explanation for the replay/debug view.
    if top_score <= 0.0 and _LIGHT_CONVERSATION_RE.match(str(query or "").strip()):
        routing_reason = "Light conversational turn — routed to general."
    elif top_score <= 0.0:
        routing_reason = "No strong signal — routed to general as fallback."
    else:
        routing_reason = (
            f"Selected {selected_specialist} via {routing_method} routing "
            f"(score {top_score:.1f})."
        )

    # Friendly SSE progress line so the UI can say "focusing on X" instead
    # of "orchestrator" while the backend thinks.
    step_progress = list(state.get("step_progress", []))
    specialist_label = {
        "academic": "academic planning",
        "career": "career planning",
        "general": "general guidance",
    }.get(selected_specialist, "the best guidance path")
    add_progress(
        step_progress,
        stage="Choosing the best approach",
        message=f"Focusing on {specialist_label} for this question.",
    )

    log.info(
        "Orchestrator selected specialist=%s method=%s scores=%s",
        selected_specialist, routing_method, routing_scores,
    )
    return {
        **state,
        "selected_specialist": selected_specialist,
        "routing_scores": routing_scores,
        "routing_reason": routing_reason,
        "step_progress": step_progress,
    }
