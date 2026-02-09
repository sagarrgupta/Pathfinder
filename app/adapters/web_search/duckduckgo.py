"""DuckDuckGo search adapter (free, no API key needed).

Uses the `ddgs` package (formerly `duckduckgo-search`).
The sync DDGS client is wrapped with asyncio.to_thread so it
doesn't block the event loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger("pathfinder.search.duckduckgo")


def _sync_search(query: str, max_results: int) -> list[dict[str, Any]]:
    """Run the synchronous DDGS text search."""
    from ddgs import DDGS

    ddgs = DDGS()
    raw_results = ddgs.text(query, max_results=max_results)

    results = []
    for item in raw_results:
        results.append({
            "title": item.get("title", ""),
            "url": item.get("href", ""),
            "content": item.get("body", ""),
            "score": 0.0,
            "source": "duckduckgo",
        })
    return results


async def search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Search using DuckDuckGo (last resort, always available)."""
    try:
        results = await asyncio.to_thread(_sync_search, query, max_results)
        log.info("DuckDuckGo returned %d results for: %s", len(results), query[:60])
        return results

    except Exception as exc:
        log.warning("DuckDuckGo search failed: %s", exc)
        raise
