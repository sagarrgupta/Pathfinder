"""Picks which specialist persona should answer this turn.

The fashion demo reuses three internal keys: `academic` for shopping,
`career` for size/fit, and `general` for wardrobe/general fashion assistance.
Instead of hand-written keyword rules (which age badly as the
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
        "Fashion shopping and product discovery for any requested clothing or "
        "accessory category. Find web products using the consumer's preferences, "
        "budget, measurements, and the applicable product size guide."
    ),
    "career": (
        "Size and fit questions, comparing body measurements and units with "
        "brand or product size guides, garment dimensions, and fit preferences."
    ),
    "general": (
        "Wardrobe styling, combinations from owned garments for an occasion, "
        "consumer profiles, clothing photos, greetings, follow-ups, and "
        "fashion requests that span roles or do not belong to one specialist."
    ),
}

_ROUTING_PROMPT = """Classify a consumer's fashion query. Score each specialist 0–10.
The category names academic, career, and general are legacy routing identifiers;
use their descriptions below to determine their current fashion responsibilities.

Specialists:
{specialists}

Query: "{query}"
{context_line}

Return ONLY JSON, nothing else:
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

    We hint the router with a few fields from the consumer's profile to
    disambiguate shopping, size/fit, and wardrobe styling requests.
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
        "academic": "finding clothing and accessories",
        "career": "size and fit",
        "general": "wardrobe styling and fashion assistance",
    }.get(selected_specialist, "fashion assistance")
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
