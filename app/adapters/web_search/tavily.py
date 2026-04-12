"""Tavily AI search adapter."""

from __future__ import annotations

import logging
from typing import Any

from app.adapters.web_search._common import build_search_result, clamp_max_results, dedupe_results, normalize_query
from app.config.settings import settings

log = logging.getLogger("pathfinder.search.tavily")

    
async def search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Search using Tavily AI Search API."""
    query = normalize_query(query)
    max_results = clamp_max_results(max_results)
    if not query:
        return []
    if not settings.TAVILY_API_KEY:
        raise RuntimeError("TAVILY_API_KEY not configured")

    try:
        from tavily import AsyncTavilyClient

        client = AsyncTavilyClient(api_key=settings.TAVILY_API_KEY)
        response = await client.search(query=query, max_results=max_results)
        
        results: list[dict[str, Any]] = []
        for item in response.get("results", []):
            normalized = build_search_result(
                title=item.get("title", ""),
                url=item.get("url", ""),
                content=item.get("content", ""),
                score=float(item.get("score", 0.0) or 0.0),
                source="tavily",
            )
            if normalized:
                results.append(normalized)
        results = dedupe_results(results, max_results)
        log.info("Tavily returned %d results for: %s", len(results), query[:60])
        return results
        
    except Exception as exc:
        log.warning("Tavily search failed: %s", exc)
        raise
