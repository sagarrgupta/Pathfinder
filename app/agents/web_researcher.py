"""Node 6: Web Researcher.

Searches the web using the fallback chain when external information
is needed. Uses the LLM to generate smart, targeted search queries
based on the student's profile and question context.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage

from app.adapters.llm.lmstudio import get_text_llm
from app.adapters.web_search.fallback_chain import search
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.web_researcher")

_QUERY_GEN_PROMPT = """You are a search query optimizer. Generate 2-3 specific, targeted web search queries
to find information that will help answer this student's question.

Use their profile data to craft precise queries — include university name, program, specific skills, etc.
Each query should target a different angle or source of information.

Student Profile:
{profile_summary}

Student Question: {query}
Intent: {intent}

Return ONLY a JSON array of search query strings, nothing else.
Example: ["CSUS computer science masters course catalog 2026", "AI machine learning graduate courses California State Sacramento"]
"""


async def web_researcher(state: PathfinderState) -> PathfinderState:
    """Search the web with LLM-generated smart queries and add results to state."""
    query = state.get("query", "")
    intent = state.get("intent", "general")
    profile = state.get("profile_data", {})

    step_progress = list(state.get("step_progress", []))
    step_progress.append("Searching the web for relevant information...")

    # Generate smart, targeted search queries using LLM + profile context
    search_queries = await _generate_smart_queries(query, intent, profile)

    log.info("Web researcher: running %d queries: %s", len(search_queries), search_queries)

    # Execute each query through the fallback chain, aggregate results
    all_results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for sq in search_queries:
        try:
            results = await search(sq, max_results=3)
            for r in results:
                url = r.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_results.append(r)
        except Exception as exc:
            log.debug("Search query failed: %s — %s", sq[:60], exc)

    # Sort by score (highest first) and take top 5
    all_results.sort(key=lambda r: r.get("score", 0), reverse=True)
    results = all_results[:5]

    if results:
        step_progress.append(f"Found {len(results)} web results")
    else:
        step_progress.append("No relevant web results found")

    # Build citations from web results
    citations = list(state.get("citations", []))
    for r in results:
        citations.append({
            "source": r.get("url", ""),
            "content": r.get("content", "")[:200],
            "score": r.get("score", 0.0),
            "metadata": {"title": r.get("title", ""), "search_source": r.get("source", "")},
        })

    log.info("Web researcher: %d total results from %d queries", len(results), len(search_queries))

    return {
        **state,
        "web_results": results,
        "citations": citations,
        "step_progress": step_progress,
        "next_node": _determine_next(state),
    }


async def _generate_smart_queries(
    query: str, intent: str, profile: dict[str, Any]
) -> list[str]:
    """Use the LLM to generate targeted search queries based on profile context.

    Falls back to rule-based generation if the LLM call fails.
    """
    # Build a concise profile summary for the LLM
    profile_summary = _build_profile_summary(profile)

    try:
        llm = get_text_llm()
        response = await llm.ainvoke([
            SystemMessage(content="You are a search query optimizer. Generate targeted web search queries."),
            HumanMessage(content=_QUERY_GEN_PROMPT.format(
                profile_summary=profile_summary,
                query=query,
                intent=intent,
            )),
        ])

        content = response.content if isinstance(response.content, str) else str(response.content)
        content = content.strip()

        # Parse JSON array from response
        json_start = content.find("[")
        json_end = content.rfind("]") + 1
        if json_start >= 0 and json_end > json_start:
            queries = json.loads(content[json_start:json_end])
            if isinstance(queries, list) and all(isinstance(q, str) for q in queries):
                log.info("LLM-generated search queries: %s", queries[:3])
                return queries[:3]

    except Exception as exc:
        log.warning("Smart query generation failed, using fallback: %s", exc)

    # Fallback: rule-based query generation
    return _build_fallback_queries(query, intent, profile)


def _build_profile_summary(profile: dict[str, Any]) -> str:
    """Build a concise profile summary string for the query generation LLM."""
    parts = []
    personal = profile.get("personal", {})

    # Add all non-system personal properties
    skip = {"id", "created_at", "updated_at"}
    for key, value in personal.items():
        if key not in skip and value:
            parts.append(f"{key}: {value}")

    skills = profile.get("skills", [])
    if skills:
        parts.append("Skills: " + ", ".join(s.get("name", "") for s in skills[:5]))

    goals = profile.get("goals", [])
    if goals:
        parts.append("Goals: " + ", ".join(g.get("name", "") for g in goals[:3]))

    courses = profile.get("courses", [])
    if courses:
        parts.append(f"Completed {len(courses)} courses")

    experience = profile.get("experience", [])
    if experience:
        parts.append("Experience: " + ", ".join(e.get("name", "") for e in experience[:3]))

    return "\n".join(parts) if parts else "No profile data available"


def _build_fallback_queries(
    query: str, intent: str, profile: dict[str, Any]
) -> list[str]:
    """Rule-based fallback when LLM query generation fails."""
    queries = []
    personal = profile.get("personal", {})
    university = personal.get("university", "")
    program = personal.get("program", "")

    # Query 1: Question + university + program (most specific)
    if university and program:
        queries.append(f"{university} {program} {query}")

    # Query 2: Question + university
    if university:
        queries.append(f"{query} {university}")

    # Intent-specific queries
    if intent == "academic":
        if university:
            queries.append(f"{university} course catalog {program or ''} 2025 2026")
    elif intent == "career":
        skills = [s.get("name", "") for s in profile.get("skills", [])[:3]]
        if skills:
            queries.append(f"career path {' '.join(skills)}")
    elif intent == "interview":
        skills = [s.get("name", "") for s in profile.get("skills", [])[:3]]
        goals = [g.get("name", "") for g in profile.get("goals", [])[:2]]
        if skills or goals:
            queries.append(f"interview questions {' '.join(skills + goals)}")

    # Always include the raw query as a fallback
    queries.append(query)

    # Deduplicate and limit to 3
    seen = set()
    unique = []
    for q in queries:
        q_lower = q.strip().lower()
        if q_lower and q_lower not in seen:
            seen.add(q_lower)
            unique.append(q.strip())
    return unique[:3]


def _determine_next(state: PathfinderState) -> str:
    """Determine next node after web research."""
    plan = state.get("plan", [])
    try:
        idx = plan.index("web_researcher")
        if idx + 1 < len(plan):
            return plan[idx + 1]
    except ValueError:
        pass
    return "evaluator"
