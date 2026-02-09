"""Node 6: Web Researcher.

Searches the web using the fallback chain when external information
is needed. Uses the LLM to generate smart, targeted search queries
based on the student's profile and question context.

When the user provides specific URLs, those pages are fetched directly
and their content is used as the primary data source.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage

from app.adapters.llm.lmstudio import get_text_llm
from app.adapters.web_search.fallback_chain import search
from app.adapters.web_search.url_fetcher import extract_urls, fetch_url_content
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

_QUERY_GEN_URL_PROMPT = """You are a search query optimizer. The student has provided specific URL(s) in their question.
The URL content is already being fetched directly. Generate 1-2 supplementary search queries.

IMPORTANT — Decide whether to incorporate the student's profile based on the question:
- If the question is about the URL content itself (e.g., "summarize this page", "read reviews on this site"),
  focus queries ONLY on the URL's topic. Do NOT add the student's university or profile.
- If the question connects the URL to the student personally (e.g., "is this school good for me",
  "based on my skills, which programs fit", "compare this with my university"),
  then USE the student's profile to craft relevant queries.

Student Profile:
{profile_summary}

URLs already being fetched: {urls}
Student Question: {query}
Intent: {intent}

Return ONLY a JSON array of search query strings, nothing else.
Example (URL-only): ["Boston University graduate school reviews 2026", "Boston University graduate program student experience"]
Example (profile-relevant): ["Boston University vs CSUS computer science masters", "Boston University CS program career outcomes software engineer"]
"""


async def web_researcher(state: PathfinderState) -> PathfinderState:
    """Search the web with LLM-generated smart queries and add results to state."""
    query = state.get("query", "")
    intent = state.get("intent", "general")
    profile = state.get("profile_data", {})

    step_progress = list(state.get("step_progress", []))
    step_progress.append("Searching the web for relevant information...")

    all_results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    # ── Step 1: Detect and directly fetch any URLs in the query ──────
    user_urls = extract_urls(query)

    if user_urls:
        log.info("Web researcher: detected %d URL(s) in query: %s", len(user_urls), user_urls)
        step_progress.append(f"Fetching content from {len(user_urls)} URL(s)...")

        for url in user_urls:
            result = await fetch_url_content(url)
            if result:
                seen_urls.add(url)
                all_results.append(result)
                log.info("Fetched URL content: %s (%d chars)", url, len(result.get("content", "")))
            else:
                log.warning("Could not fetch URL: %s", url)
                step_progress.append(f"Could not access {url}")

    # ── Step 2: Generate search queries ──────────────────────────────
    # If user provided URLs, use the URL-aware prompt that gives the LLM
    # both the profile and URLs — the LLM decides whether profile context
    # is relevant based on the nature of the question.
    # Otherwise, use the standard profile-aware prompt.
    if user_urls:
        search_queries = await _generate_url_aware_queries(query, intent, user_urls, profile)
    else:
        search_queries = await _generate_smart_queries(query, intent, profile)

    log.info("Web researcher: running %d queries: %s", len(search_queries), search_queries)

    # ── Step 3: Execute search queries through the fallback chain ────
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

    # Sort by score (highest first) and take top results
    # Direct URL fetches (score=1.0) will naturally rank first
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

    log.info("Web researcher: %d total results from %d queries + %d direct URLs",
             len(results), len(search_queries), len(user_urls))

    return {
        **state,
        "web_results": results,
        "citations": citations,
        "step_progress": step_progress,
        "next_node": _determine_next(state),
    }


async def _generate_url_aware_queries(
    query: str, intent: str, urls: list[str], profile: dict[str, Any]
) -> list[str]:
    """Generate supplementary search queries when the user provided URLs.

    Provides the LLM with both the URLs and the student's profile.
    The LLM decides whether to incorporate profile context based on
    the nature of the question.
    """
    profile_summary = _build_profile_summary(profile)

    try:
        llm = get_text_llm()
        response = await llm.ainvoke([
            SystemMessage(content="You are a search query optimizer. Generate supplementary search queries."),
            HumanMessage(content=_QUERY_GEN_URL_PROMPT.format(
                profile_summary=profile_summary,
                urls=", ".join(urls),
                query=query,
                intent=intent,
            )),
        ])

        content = response.content if isinstance(response.content, str) else str(response.content)
        content = content.strip()

        json_start = content.find("[")
        json_end = content.rfind("]") + 1
        if json_start >= 0 and json_end > json_start:
            queries = json.loads(content[json_start:json_end])
            if isinstance(queries, list) and all(isinstance(q, str) for q in queries):
                log.info("URL-aware search queries: %s", queries[:2])
                return queries[:2]

    except Exception as exc:
        log.warning("URL-aware query generation failed: %s", exc)

    # Fallback: extract a simple query from the URL itself
    return [query]


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
