"""Tools for reaching outside the consumer graph — live web search + URL fetch.

Three tools are registered here:
- `search_web`            : generic results across the fallback provider chain.
- `fetch_url`             : pull readable content from one specific page.
- `find_official_sources` : search for brand/retailer product and size-guide sources.

Only the specialist profile sees these. Ingestion agents stay offline so
that the graph only reflects the consumer's own documents and statements,
not whatever the web happens to say at ingestion time.

The actual HTTP work is delegated to `app.adapters.web_search` so the
fallback order (Tavily -> Google CSE -> Brave, etc.) is tunable in one
place based on which API keys are configured.
"""

from __future__ import annotations

from typing import Any

from app.adapters.web_search.fallback_chain import search as web_search
from app.adapters.web_search.url_fetcher import fetch_url_content
from app.tools.tools import ToolContext, ToolSpec, bounded_text


def _compact_web_results(results: list[dict], limit: int = 5) -> list[dict]:
    """Trim a list of search results to title/url/snippet, bounded per field."""
    compacted: list[dict] = []
    for item in results[:limit]:
        if not isinstance(item, dict):
            continue
        compacted.append(
            {
                "title": bounded_text(item.get("title"), limit=160),
                "url": str(item.get("url", "") or ""),
                "snippet": bounded_text(item.get("snippet") or item.get("content"), limit=220),
            }
        )
    return compacted

async def _search_web(arguments: dict[str, Any], _: ToolContext) -> dict[str, Any]:
    """Run a web search through the adapter's provider fallback chain."""
    query = str(arguments.get("query", "") or "").strip()
    if not query:
        return {"error": "query is required"}
    # Clamp user-supplied result count to a safe range. The LLM occasionally
    # asks for 100 results, which wastes tokens and provider quota.
    try:
        max_results = int(arguments.get("max_results", 5))
    except Exception:
        max_results = 5
    max_results = max(1, min(max_results, 10))
    results = await web_search(query, max_results=max_results)
    return {"results": results[:max_results]}


def _compact_search_web(arguments: dict[str, Any], result: dict[str, Any], _: ToolContext) -> dict[str, Any]:
    results = list(result.get("results", []) or [])
    return {
        "query": str(arguments.get("query", "") or "").strip(),
        "count": len(results),
        "results": _compact_web_results(results, limit=8),
    }


async def _fetch_url(arguments: dict[str, Any], _: ToolContext) -> dict[str, Any]:
    """Download and extract readable content from one URL."""
    url = str(arguments.get("url", "") or "").strip()
    if not url:
        return {"error": "url is required"}
    result = await fetch_url_content(url)
    return {"result": result or {}, "error": "" if result else "fetch failed"}


def _compact_fetch_url(arguments: dict[str, Any], result: dict[str, Any], _: ToolContext) -> dict[str, Any]:
    payload = dict(result.get("result") or {})
    content = str(payload.get("content") or payload.get("text") or "")
    return {
        "url": str(arguments.get("url", "") or ""),
        "title": bounded_text(payload.get("title"), limit=160),
        # The model needs actual product details and size tables, not just a snippet.
        "content_preview": bounded_text(content, limit=22000),
        "content_truncated": len(content) > 22000 or "[Content truncated...]" in content,
    }


async def _find_official_sources(arguments: dict[str, Any], _: ToolContext) -> dict[str, Any]:
    """Find candidate brand/retailer sources; the agent verifies their provenance."""
    query = str(arguments.get("query", "") or "").strip()
    if not query:
        return {"error": "query is required"}
    results = await web_search(f"{query} official brand retailer size guide", max_results=8)
    # A search hit alone cannot establish authority. Do not discard real brands
    # because their URLs lack the old academic-domain substrings.
    return {"results": results[:5]}


def _compact_find_official(arguments: dict[str, Any], result: dict[str, Any], _: ToolContext) -> dict[str, Any]:
    results = list(result.get("results", []) or [])
    return {
        "query": str(arguments.get("query", "") or "").strip(),
        "count": len(results),
        "results": _compact_web_results(results, limit=5),
    }


def get_web_tool_specs() -> list[ToolSpec]:
    """Register search / fetch / official-source tools with the registry."""
    return [
        ToolSpec(
            name="search_web",
            description="Search the web for products, clothing, accessories, retailer pages, and product-specific size guides for any requested category. Use saved consumer preferences to target the search. Results are candidates: fetch pages to verify product details, fit evidence, prices, and availability.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query describing the information to look up on the web."},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 10, "description": "Maximum number of search results to return."},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=_search_web,
            compact_handler=_compact_search_web,
        ),
        ToolSpec(
            name="fetch_url",
            description="Fetch a specific product page or size guide and return readable page content, including available size-table text. Use this to verify search results and compare the consumer's measurements with the applicable chart. Content may be truncated or unavailable; do not invent missing details.",
            input_schema={
                "type": "object",
                "properties": {"url": {"type": "string", "description": "Absolute URL of the webpage to fetch and extract."}},
                "required": ["url"],
                "additionalProperties": False,
            },
            handler=_fetch_url,
            compact_handler=_compact_fetch_url,
        ),
        ToolSpec(
            name="find_official_sources",
            description="Search for candidate official brand or retailer product pages and size guides. Include the relevant brand or product in the query when known. Search results are not automatically authoritative: fetch the page and verify the source and chart applicability before relying on it.",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search query for which authoritative or official sources should be identified."}},
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=_find_official_sources,
            compact_handler=_compact_find_official,
        ),
    ]
