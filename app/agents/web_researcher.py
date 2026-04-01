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
from urllib.parse import urlparse

from langchain_core.messages import SystemMessage, HumanMessage

from app.adapters.llm.lmstudio import get_text_llm
from app.adapters.web_search.fallback_chain import search
from app.adapters.web_search.url_fetcher import extract_urls, fetch_url_content
from app.core.quality import (
    add_working_memory_item,
    academic_source_relevance,
    analyze_query_focus,
    classify_web_source,
    complete_task,
    infer_evidence_tiers,
    infer_target_level,
    infer_target_program,
    init_working_memory,
    record_source_audit,
)
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.web_researcher")

_QUERY_GEN_PROMPT = """You are a search query optimizer. Generate 2-3 specific, targeted web search queries
to find information that will help answer this student's question.

Use their profile data to craft precise queries — include university name, program, specific skills, etc.
Each query should target a different angle or source of information.
Prefer exact institution names from the profile or recent conversation.
Do NOT substitute a similar university or campus.
If the question is about course enrollment, prioritize official catalog, schedule, or department pages.

Student Profile:
{profile_summary}

Student Question: {query}
Intent: {intent}

Return ONLY a JSON array of search query strings, nothing else.
Example: ["official university course catalog data science masters", "site:university.edu program requirements next semester"]
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
    session_summary = state.get("session_summary", {})
    query_focus = analyze_query_focus(query)
    target_program = infer_target_program(profile, session_summary, query)
    target_level = infer_target_level(profile, session_summary, query)
    preferred_domains = _preferred_domains(profile, query)
    source_policy = state.get("source_policy", {})
    if source_policy.get("preferred_domains"):
        preferred_domains = list(dict.fromkeys(list(source_policy.get("preferred_domains", [])) + preferred_domains))
    working_memory = init_working_memory(state.get("working_memory", {}))
    task_graph = state.get("task_graph", [])

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
                source_type, time_scope = classify_web_source(
                    result.get("url", ""),
                    result.get("title", ""),
                    result.get("content", ""),
                )
                trust_tier, fit_tier, freshness_tier = infer_evidence_tiers(
                    result.get("url", ""),
                    source_type,
                    target_program,
                    target_level,
                    result.get("title", ""),
                    result.get("content", ""),
                )
                working_memory = record_source_audit(working_memory, {
                    "url": result.get("url", ""),
                    "title": result.get("title", ""),
                    "source_type": source_type,
                    "action": "selected",
                    "reason": "Direct URL provided by the user.",
                    "score": 10.0,
                    "trust_tier": trust_tier,
                    "fit_tier": fit_tier,
                    "freshness_tier": freshness_tier,
                })
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

    search_queries = _expand_queries(search_queries, query, intent, preferred_domains, source_policy)

    log.info("Web researcher: running %d queries: %s", len(search_queries), search_queries)

    # ── Step 3: Execute search queries through the fallback chain ────
    for sq in search_queries:
        try:
            max_results = 6 if intent in {"academic", "research"} else 4
            results = await search(sq, max_results=max_results)
            for r in results:
                url = r.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    enriched = dict(r)
                    enriched["score"] = _result_score(
                        enriched, query, preferred_domains, query_focus, target_program, target_level, source_policy
                    )
                    all_results.append(enriched)
        except Exception as exc:
            log.debug("Search query failed: %s — %s", sq[:60], exc)

    # ── Step 4: Fetch full content for the strongest search hits ─────
    fetched_results = list(all_results)
    candidates = sorted(all_results, key=lambda r: r.get("score", 0), reverse=True)
    fetch_budget = int(source_policy.get("fetch_budget", 8 if intent in {"academic", "research"} else 5))

    strict_official = bool(source_policy.get("strict_primary_only")) and query_focus.get("primary") == "academic"
    if strict_official:
        filtered_candidates = []
        for candidate in candidates:
            source_type, _ = classify_web_source(
                candidate.get("url", ""),
                candidate.get("title", ""),
                candidate.get("content", ""),
            )
            trust_tier, fit_tier, freshness_tier = infer_evidence_tiers(
                candidate.get("url", ""),
                source_type,
                target_program,
                target_level,
                candidate.get("title", ""),
                candidate.get("content", ""),
            )
            if trust_tier == "third_party":
                working_memory = record_source_audit(working_memory, {
                    "url": candidate.get("url", ""),
                    "title": candidate.get("title", ""),
                    "source_type": source_type,
                    "action": "rejected",
                    "reason": "Third-party source rejected for strict academic planning.",
                    "score": float(candidate.get("score", 0.0) or 0.0),
                    "trust_tier": trust_tier,
                    "fit_tier": fit_tier,
                    "freshness_tier": freshness_tier,
                })
                continue
            filtered_candidates.append(candidate)
        candidates = filtered_candidates

    for candidate in candidates[:fetch_budget]:
        url = candidate.get("url", "")
        if not url or candidate.get("source") == "direct_url":
            continue
        fetched = await fetch_url_content(url)
        if fetched:
            fetched["score"] = max(candidate.get("score", 0.0), 0.0) + 0.35
            source_type, time_scope = classify_web_source(
                fetched.get("url", ""),
                fetched.get("title", ""),
                fetched.get("content", ""),
            )
            if source_policy.get("primary_source_types") and source_type in source_policy.get("primary_source_types", []):
                fetched["score"] += 0.5
            trust_tier, fit_tier, freshness_tier = infer_evidence_tiers(
                fetched.get("url", ""),
                source_type,
                target_program,
                target_level,
                fetched.get("title", ""),
                fetched.get("content", ""),
            )
            fetched["metadata"] = {
                "title": candidate.get("title", ""),
                "search_source": candidate.get("source", ""),
                "fetched_from_search": True,
                "source_type": source_type,
                "time_scope": time_scope,
                "selection_reason": _selection_reason(source_type, query_focus),
                "trust_tier": trust_tier,
                "fit_tier": fit_tier,
                "freshness_tier": freshness_tier,
            }
            fetched_results.append(fetched)
            working_memory = record_source_audit(working_memory, {
                "url": fetched.get("url", ""),
                "title": fetched.get("title", ""),
                "source_type": source_type,
                "action": "selected",
                "reason": _selection_reason(source_type, query_focus),
                "score": float(fetched.get("score", 0.0) or 0.0),
                "trust_tier": trust_tier,
                "fit_tier": fit_tier,
                "freshness_tier": freshness_tier,
            })
        else:
            source_type, time_scope = classify_web_source(
                candidate.get("url", ""),
                candidate.get("title", ""),
                candidate.get("content", ""),
            )
            trust_tier, fit_tier, freshness_tier = infer_evidence_tiers(
                candidate.get("url", ""),
                source_type,
                target_program,
                target_level,
                candidate.get("title", ""),
                candidate.get("content", ""),
            )
            working_memory = record_source_audit(working_memory, {
                "url": candidate.get("url", ""),
                "title": candidate.get("title", ""),
                "source_type": source_type,
                "action": "rejected",
                "reason": "Page fetch failed or returned no usable content.",
                "score": float(candidate.get("score", 0.0) or 0.0),
                "trust_tier": trust_tier,
                "fit_tier": fit_tier,
                "freshness_tier": freshness_tier,
            })

    # Sort by score (highest first) and keep a deeper evidence pool
    fetched_results.sort(key=lambda r: r.get("score", 0), reverse=True)
    results = _dedupe_results(fetched_results)[:8]

    if query_focus.get("primary") == "academic":
        official_results = []
        secondary_results = []
        for result in results:
            source_type, _ = classify_web_source(result.get("url", ""), result.get("title", ""), result.get("content", ""))
            trust_tier, fit_tier, _ = infer_evidence_tiers(
                result.get("url", ""),
                source_type,
                target_program,
                target_level,
                result.get("title", ""),
                result.get("content", ""),
            )
            if trust_tier == "primary_official" and fit_tier != "weak":
                official_results.append(result)
            elif trust_tier != "third_party" or not strict_official:
                secondary_results.append(result)
            else:
                working_memory = record_source_audit(working_memory, {
                    "url": result.get("url", ""),
                    "title": result.get("title", ""),
                    "source_type": source_type,
                    "action": "rejected",
                    "reason": "Removed from final evidence pool because a stronger official source exists.",
                    "score": float(result.get("score", 0.0) or 0.0),
                    "trust_tier": trust_tier,
                    "fit_tier": fit_tier,
                    "freshness_tier": "live" if source_type == "schedule_page" else "unclear",
                })
        results = (official_results + secondary_results)[:8]

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

    task_graph = complete_task(task_graph, "retrieve_primary_sources")
    if query_focus.get("wants_live_availability"):
        if any(classify_web_source(r.get("url", ""), r.get("title", ""), r.get("content", ""))[0] == "schedule_page" for r in results):
            task_graph = complete_task(task_graph, "retrieve_live_schedule")
        else:
            working_memory = add_working_memory_item(working_memory, "missing_primary_evidence", "No live official schedule source was found for this enrollment-style query.")

    return {
        **state,
        "web_results": results,
        "citations": citations,
        "working_memory": working_memory,
        "task_graph": task_graph,
        "source_audit": working_memory.get("source_audit", []),
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


def _preferred_domains(profile: dict[str, Any], query: str) -> list[str]:
    """Infer official or high-trust domains from the student's context."""
    domains: list[str] = []
    personal = profile.get("personal", {})
    candidates = [
        personal.get("website"),
        personal.get("university_website"),
        personal.get("portal_url"),
        personal.get("email"),
    ]

    for url_or_email in candidates:
        domain = _extract_domain_candidate(url_or_email or "")
        if domain and domain not in domains:
            domains.append(domain)

    for url in extract_urls(query):
        domain = _extract_domain_candidate(url)
        if domain and domain not in domains:
            domains.append(domain)

    return domains[:4]


def _expand_queries(
    search_queries: list[str], query: str, intent: str, preferred_domains: list[str], source_policy: dict[str, Any]
) -> list[str]:
    """Add deterministic official-site queries to the model-generated query set."""
    expanded = list(search_queries)

    if intent in {"academic", "research"} and preferred_domains:
        domain = preferred_domains[0]
        expanded.append(f"site:{domain} {query}")
        expanded.append(f"site:{domain} official catalog {query}")
        expanded.append(f"site:{domain} schedule requirements {query}")
        if source_policy.get("prefer_pdfs"):
            expanded.append(f"site:{domain} filetype:pdf {query}")

    expanded.append(query)

    unique: list[str] = []
    seen: set[str] = set()
    for q in expanded:
        cleaned = q.strip()
        lowered = cleaned.lower()
        if cleaned and lowered not in seen:
            seen.add(lowered)
            unique.append(cleaned)
    return unique[:6]


def _result_score(
    result: dict[str, Any],
    query: str,
    preferred_domains: list[str],
    query_focus: dict[str, Any],
    target_program: str = "",
    target_level: str = "unknown",
    source_policy: dict[str, Any] | None = None,
) -> float:
    """Heuristic ranking for search results before full-page fetch."""
    score = float(result.get("score", 0.0) or 0.0)
    url = result.get("url", "")
    title = (result.get("title", "") or "").lower()
    content = (result.get("content", "") or "").lower()
    domain = urlparse(url).netloc.lower()
    query_terms = [term for term in query.lower().split() if len(term) > 2]
    source_type, time_scope = classify_web_source(url, result.get("title", ""), result.get("content", ""))
    source_policy = source_policy or {}

    if any(domain.endswith(pref) for pref in preferred_domains):
        score += 2.0
    elif domain.endswith(".edu"):
        score += 0.6

    matched_terms = sum(1 for term in query_terms if term in title or term in content)
    score += min(1.5, matched_terms * 0.15)

    if any(word in title for word in ("catalog", "schedule", "curriculum", "computer science", "graduate")):
        score += 0.5

    if query_focus.get("primary") == "academic":
        score += academic_source_relevance(
            result.get("title", ""),
            result.get("content", ""),
            url,
            target_program,
            target_level,
        )

    if source_type in source_policy.get("primary_source_types", []):
        score += 1.2
    elif source_type in source_policy.get("secondary_source_types", []):
        score += 0.3
    elif source_policy.get("primary_source_types"):
        score -= 0.6

    if source_policy.get("prefer_pdfs") and url.lower().endswith(".pdf"):
        score += 0.8

    score += _source_type_bonus(source_type, time_scope, query_focus)
    score -= _source_type_penalty(source_type, query_focus)

    return score


def _source_type_bonus(source_type: str, time_scope: str, query_focus: dict[str, Any]) -> float:
    bonus = 0.0
    primary = query_focus.get("primary", "")

    if primary == "academic":
        if query_focus.get("wants_live_availability"):
            if source_type == "schedule_page":
                bonus += 3.4
            elif source_type == "degree_page":
                bonus += 0.7
            elif source_type == "certificate_page":
                bonus += 0.3
        elif query_focus.get("wants_requirements"):
            if source_type == "degree_page":
                bonus += 2.3
            elif source_type == "admissions_page":
                bonus += 1.5
            elif source_type == "certificate_page":
                bonus += 0.4
        else:
            if source_type == "degree_page":
                bonus += 2.0
            elif source_type == "schedule_page":
                bonus += 0.8
            elif source_type == "certificate_page":
                bonus += 0.5

    if primary == "career":
        if source_type == "job_page":
            bonus += 2.2
        elif source_type == "general_web":
            bonus += 0.4

    if primary == "comparison":
        if source_type in {"degree_page", "admissions_page"}:
            bonus += 1.8

    if primary == "summary":
        if source_type != "general_web":
            bonus += 0.8

    if time_scope == "live_schedule" and query_focus.get("wants_live_availability"):
        bonus += 0.7

    return bonus


def _source_type_penalty(source_type: str, query_focus: dict[str, Any]) -> float:
    penalty = 0.0
    primary = query_focus.get("primary", "")

    if primary == "academic" and query_focus.get("wants_requirements") and source_type == "certificate_page":
        penalty += 0.8
    if primary == "academic" and query_focus.get("wants_live_availability") and source_type == "degree_page":
        penalty += 0.8
    if primary == "academic" and not query_focus.get("wants_live_availability") and source_type == "schedule_page":
        penalty += 0.2
    if primary == "career" and source_type in {"degree_page", "certificate_page"}:
        penalty += 0.6

    return penalty


def _selection_reason(source_type: str, query_focus: dict[str, Any]) -> str:
    primary = query_focus.get("primary", "")
    if primary == "academic" and query_focus.get("wants_live_availability") and source_type == "schedule_page":
        return "Selected because the query asks about current availability."
    if primary == "academic" and source_type == "degree_page":
        return "Selected as a primary official program source."
    if primary == "career" and source_type == "job_page":
        return "Selected as a direct role-matching source."
    if source_type == "certificate_page":
        return "Selected as a secondary specialization source."
    return "Selected as a relevant supporting source."


def _dedupe_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the highest-scoring result for each URL."""
    deduped: dict[str, dict[str, Any]] = {}
    for result in results:
        url = result.get("url", "")
        if not url:
            continue
        existing = deduped.get(url)
        if not existing or result.get("score", 0) > existing.get("score", 0):
            deduped[url] = result
    return list(deduped.values())


def _extract_domain_candidate(value: str) -> str:
    text = (value or "").strip().lower()
    if not text:
        return ""
    if "@" in text and "://" not in text:
        text = text.split("@", 1)[1]
    if "://" not in text:
        text = f"https://{text}"
    domain = urlparse(text).netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


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
