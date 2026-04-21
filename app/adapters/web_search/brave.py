"""Brave Search provider.

Requires `BRAVE_API_KEY`. We only read from the `web.results` section
of the response — Brave also returns news/images/videos that we don't
use for answering questions.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.adapters.web_search._common import build_search_result, clamp_max_results, dedupe_results, normalize_query
from app.config.settings import settings

log = logging.getLogger("pathfinder.search.brave")

_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


async def search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Call Brave's HTTP API and normalize the `web.results` section."""
    query = normalize_query(query)
    max_results = clamp_max_results(max_results)
    if not query:
        return []
    if not settings.BRAVE_API_KEY:
        raise RuntimeError("BRAVE_API_KEY not configured")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                _BRAVE_URL,
                headers={"X-Subscription-Token": settings.BRAVE_API_KEY},
                params={"q": query, "count": max_results},
            )
            resp.raise_for_status()
            data = resp.json()

        results: list[dict[str, Any]] = []
        for item in data.get("web", {}).get("results", []):
            normalized = build_search_result(
                title=item.get("title", ""),
                url=item.get("url", ""),
                content=item.get("description", ""),
                score=0.0,
                source="brave",
            )
            if normalized:
                results.append(normalized)
        results = dedupe_results(results, max_results)
        log.info("Brave returned %d results for: %s", len(results), query[:60])
        return results

    except Exception as exc:
        log.warning("Brave search failed: %s", exc)
        raise
