"""Google Custom Search Engine adapter."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.adapters.web_search._common import build_search_result, clamp_max_results, dedupe_results, normalize_query
from app.config.settings import settings

log = logging.getLogger("pathfinder.search.google")

_GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"


async def search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Search using Google Custom Search Engine API."""
    query = normalize_query(query)
    max_results = clamp_max_results(max_results)
    if not query:
        return []
    if not settings.GOOGLE_CSE_API_KEY or not settings.GOOGLE_CSE_ID:
        raise RuntimeError("Google CSE keys not configured")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                _GOOGLE_CSE_URL,
                params={
                    "key": settings.GOOGLE_CSE_API_KEY,
                    "cx": settings.GOOGLE_CSE_ID,
                    "q": query,
                    "num": max_results,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results: list[dict[str, Any]] = []
        for item in data.get("items", []):
            normalized = build_search_result(
                title=item.get("title", ""),
                url=item.get("link", ""),
                content=item.get("snippet", ""),
                score=0.0,
                source="google_cse",
            )
            if normalized:
                results.append(normalized)
        results = dedupe_results(results, max_results)
        log.info("Google CSE returned %d results for: %s", len(results), query[:60])
        return results

    except Exception as exc:
        log.warning("Google CSE search failed: %s", exc)
        raise
