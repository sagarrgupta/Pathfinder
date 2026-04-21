"""DuckDuckGo search provider — the no-API-key safety net.

Used last in the fallback chain so Pathfinder still has some web
search capability even when no paid providers are configured. Uses
the synchronous `ddgs` package; we run it in a worker thread to keep
the event loop clear.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.adapters.web_search._common import build_search_result, clamp_max_results, dedupe_results, normalize_query

log = logging.getLogger("pathfinder.search.duckduckgo")


def _sync_search(query: str, max_results: int) -> list[dict[str, Any]]:
    """Blocking DDGS call — meant to run inside `asyncio.to_thread`."""
    from ddgs import DDGS

    with DDGS() as ddgs:
        raw_results = ddgs.text(query, max_results=max_results)

    results: list[dict[str, Any]] = []
    for item in raw_results:
        normalized = build_search_result(
            title=item.get("title", ""),
            url=item.get("href", ""),
            content=item.get("body", ""),
            score=0.0,
            source="duckduckgo",
        )
        if normalized:
            results.append(normalized)
    return dedupe_results(results, max_results)


async def search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Async wrapper that shuttles the blocking DDGS call off the event loop."""
    query = normalize_query(query)
    max_results = clamp_max_results(max_results)
    if not query:
        return []
    try:
        results = await asyncio.to_thread(_sync_search, query, max_results)
        log.info("DuckDuckGo returned %d results for: %s", len(results), query[:60])
        return results

    except Exception as exc:
        log.warning("DuckDuckGo search failed: %s", exc)
        raise
