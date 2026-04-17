"""Web MCP tools."""

from __future__ import annotations

from app.adapters.web_search.fallback_chain import search as web_search
from app.adapters.web_search.url_fetcher import fetch_url_content
from app.tools.tools import ToolContext, ToolSpec
from app.utils import coerce_bounded_int


async def _search_web(arguments: dict[str, Any], _: ToolContext) -> dict[str, Any]:
    query = str(arguments.get("query", "") or "").strip()
    if not query:
        return {"error": "query is required"}
    max_results = coerce_bounded_int(arguments.get("max_results", 5), default=5, maximum=10)
    results = await web_search(query, max_results=max_results)
    return {"results": results[:max_results]}


async def _fetch_url(arguments: dict[str, Any], _: ToolContext) -> dict[str, Any]:
    url = str(arguments.get("url", "") or "").strip()
    if not url:
        return {"error": "url is required"}
    result = await fetch_url_content(url)
    return {"result": result or {}, "error": "" if result else "fetch failed"}


async def _find_official_sources(arguments: dict[str, Any], _: ToolContext) -> dict[str, Any]:
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


def get_web_tool_specs() -> list[ToolSpec]:
    """Return web-search tool definitions."""
    return [
        ToolSpec(
            name="search_web",
            description="Search the web for current or external information relevant to the user query. Use this when the answer depends on live sources, public webpages, policies, catalogs, deadlines, or other information not guaranteed to exist in the student graph.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query describing the information to look up on the web.",
                    },
                    "max_results": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "description": "Maximum number of search results to return.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=_search_web,
        ),
        ToolSpec(
            name="fetch_url",
            description="Fetch one specific webpage and return extracted readable content. Use this after finding a promising source and you need the actual page text rather than only search-result snippets.",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Absolute URL of the webpage to fetch and extract.",
                    }
                },
                "required": ["url"],
                "additionalProperties": False,
            },
            handler=_fetch_url,
        ),
        ToolSpec(
            name="find_official_sources",
            description="Search for likely official or authoritative sources related to the query, such as university, government, catalog, or institutional pages. Use this when source quality matters and the model should prefer official references first.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query for which authoritative or official sources should be identified.",
                    }
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=_find_official_sources,
        ),
    ]
