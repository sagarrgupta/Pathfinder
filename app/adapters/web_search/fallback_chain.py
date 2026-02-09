"""Web search fallback chain.

Tries search providers in order: Tavily -> Google CSE -> Brave -> DuckDuckGo.
Returns results from the first successful provider.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine

from app.adapters.web_search import tavily, google_cse, brave, duckduckgo

log = logging.getLogger("pathfinder.search.fallback")

# Ordered list of search providers
_PROVIDERS: list[tuple[str, Callable[..., Coroutine]]] = [
    ("Tavily", tavily.search),
    ("Google CSE", google_cse.search),
    ("Brave", brave.search),
    ("DuckDuckGo", duckduckgo.search),
]


async def search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Search the web using the fallback chain.

    Tries each provider in order. Returns results from the first
    successful one. If all fail, returns an empty list.
    """
    errors: list[str] = []

    for name, provider in _PROVIDERS:
        try:
            results = await provider(query, max_results=max_results)
            if results:
                log.info("Web search successful via %s", name)
                return results
            log.info("Web search via %s returned no results, trying next", name)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            log.info("Web search via %s failed: %s — trying next provider", name, exc)

    log.warning("All web search providers failed: %s", errors)
    return []
