"""Top-level search entry point that stitches providers together.

We try each provider in turn, aggregate unique URLs, and stop as soon
as we have `max_results` good hits. Provider order roughly tracks
quality vs cost: Tavily first (best for research Qs), then Google CSE,
then Brave, then DuckDuckGo as the no-API-key safety net.

If an earlier provider returns *some* results but not enough, later
providers fill in — that's why this is an aggregator, not a pure
fallback. `web_tools.search_web` calls this; no one else should.
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
    """Run the query across providers until we have enough unique hits.

    Logs which provider contributed how many results — useful when
    diagnosing why a specialist's web answer is thin (usually: all
    providers failed or hit rate limits).
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
