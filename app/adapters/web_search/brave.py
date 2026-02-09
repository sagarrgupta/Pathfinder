"""Brave Search adapter."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config.settings import settings

log = logging.getLogger("pathfinder.search.brave")

_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


async def search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Search using Brave Search API."""
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

        results = []
        for item in data.get("web", {}).get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("description", ""),
                "score": 0.0,
                "source": "brave",
            })
        log.info("Brave returned %d results for: %s", len(results), query[:60])
        return results

    except Exception as exc:
        log.warning("Brave search failed: %s", exc)
        raise
