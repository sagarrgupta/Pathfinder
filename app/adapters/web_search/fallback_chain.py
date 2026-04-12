"""Web search fallback chain.

Tries search providers in order: Tavily -> Google CSE -> Brave -> DuckDuckGo.
Aggregates unique results across providers, stopping once enough
results are collected.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine

from app.adapters.web_search import tavily, google_cse, brave, duckduckgo
from app.adapters.web_search._common import clamp_max_results, dedupe_results, normalize_query

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

    Tries each provider in order and aggregates unique results until
    ``max_results`` have been collected. If all providers fail or
    return nothing, returns an empty list.
    """
    query = normalize_query(query)
    max_results = clamp_max_results(max_results)
    if not query:
        return []
    errors: list[str] = []
    aggregated: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for name, provider in _PROVIDERS:
        try:
            results = await provider(query, max_results=max_results)
            if results:
                added = 0
                for result in results:
                    url = result.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        aggregated.append(result)
                        added += 1
                    if len(aggregated) >= max_results:
                        break
                log.info(
                    "Web search via %s added %d unique result(s), %d total",
                    name, added, len(aggregated)
                )
                if len(aggregated) >= max_results:
                    break
            else:
                log.info("Web search via %s returned no results, trying next", name)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            log.info("Web search via %s failed: %s — trying next provider", name, exc)

    if aggregated:
        return dedupe_results(aggregated, max_results)

    log.warning("All web search providers failed: %s", errors)
    return []
