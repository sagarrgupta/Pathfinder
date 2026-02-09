"""Tavily AI search adapter."""

from __future__ import annotations

import logging
from typing import Any

from app.config.settings import settings

log = logging.getLogger("pathfinder.search.tavily")

    
async def search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Search using Tavily AI Search API."""
    if not settings.TAVILY_API_KEY:
        raise RuntimeError("TAVILY_API_KEY not configured")

    try:
        from tavily import AsyncTavilyClient

        client = AsyncTavilyClient(api_key=settings.TAVILY_API_KEY)
        response = await client.search(query=query, max_results=max_results)
        
        results = []
        for item in response.get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", ""),
                "score": item.get("score", 0.0),
                "source": "tavily",
            })
        log.info("Tavily returned %d results for: %s", len(results), query[:60])
        return results
        
    except Exception as exc:
        log.warning("Tavily search failed: %s", exc)
        raise
