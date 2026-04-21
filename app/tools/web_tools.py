"""Tools for reaching outside the student graph — live web search + URL fetch.

Three tools are registered here:
- `search_web`            : generic results across the fallback provider chain.
- `fetch_url`             : pull readable content from one specific page.
- `find_official_sources` : same as search_web but filters for `.edu`/`.gov`.

Only the specialist profile sees these. Ingestion agents stay offline so
that the graph only reflects the student's own documents and statements,
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
    return {
        "url": str(arguments.get("url", "") or ""),
        "title": bounded_text(payload.get("title"), limit=160),
        "content_preview": bounded_text(payload.get("content") or payload.get("text"), limit=320),
    }


async def _find_official_sources(arguments: dict[str, Any], _: ToolContext) -> dict[str, Any]:
    """Run a normal search and keep only results from authoritative domains.

    This is a heuristic — a page hosting `.edu` in the URL is more likely
    to be a real university source than a random blog. Good enough to
    steer the specialist towards trustworthy references first.
    """
    query = str(arguments.get("query", "") or "").strip()
    if not query:
        return {"error": "query is required"}
    results = await web_search(query, max_results=8)
    official = []
    for item in results:
        url = str(item.get("url", "") or "")
        if any(domain in url for domain in (".edu", ".gov", ".ac.", "official", "catalog")):
            official.append(item)
    return {"results": official[:5]}


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
            description="Search the web for current or external information relevant to the user query. Use this when the answer depends on live sources, public webpages, policies, catalogs, deadlines, or other information not guaranteed to exist in the student graph.",
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
            description="Fetch one specific webpage and return extracted readable content. Use this after finding a promising source and you need the actual page text rather than only search-result snippets.",
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
            description="Search for likely official or authoritative sources related to the query, such as university, government, catalog, or institutional pages. Use this when source quality matters and the model should prefer official references first.",
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
