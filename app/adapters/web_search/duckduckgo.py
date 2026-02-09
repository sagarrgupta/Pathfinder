"""DuckDuckGo search adapter (free, no API key needed)."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("pathfinder.search.duckduckgo")


async def search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Search using DuckDuckGo (last resort, always available)."""
    try:
        from duckduckgo_search import AsyncDDGS

        async with AsyncDDGS() as ddgs:
            raw_results = await ddgs.atext(query, max_results=max_results)

        results = []
        for item in raw_results:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("href", ""),
                "content": item.get("body", ""),
                "score": 0.0,
                "source": "duckduckgo",
            })
        log.info("DuckDuckGo returned %d results for: %s", len(results), query[:60])
        return results

    except Exception as exc:
        log.warning("DuckDuckGo search failed: %s", exc)
        raise
