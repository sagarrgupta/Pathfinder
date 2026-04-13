"""Direct URL content fetcher.

When the user provides a specific URL, this module fetches the page
and extracts readable text content instead of relying on keyword search.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.adapters.web_search._common import build_search_result, normalize_url

log = logging.getLogger("pathfinder.search.url_fetcher")

# Regex to extract URLs from user text
_URL_PATTERN = re.compile(
    r"https?://[^\s<>\"'\]\)]+",
    re.IGNORECASE,
)

# Maximum content length to return (characters) — prevents huge pages
# from overwhelming the LLM context window
_MAX_CONTENT_LENGTH = 22_000

# Elements to remove before extracting text
_REMOVE_TAGS = {
    "script", "style", "nav", "footer", "header", "aside",
    "noscript", "svg", "form", "button", "iframe",
}

# Request headers to look like a normal browser
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def extract_urls(text: str) -> list[str]:
    """Extract all URLs from a text string."""
    urls = [normalize_url(url) for url in _URL_PATTERN.findall(text or "")]
    seen: set[str] = set()
    deduped: list[str] = []
    for url in urls:
        if url and url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


async def fetch_url_content(url: str, timeout: float = 15.0) -> dict[str, Any] | None:
    """Fetch a URL and extract its text content.

    Returns a dict with title, url, content, and source fields
    (same shape as web search results), or None on failure.
    """
    url = normalize_url(url)
    if not url:
        return None
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            headers=_HEADERS,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type and "application/xhtml" not in content_type:
            log.info("Skipping non-HTML content at %s (type: %s)", url, content_type)
            return None

        html = response.text
        soup = BeautifulSoup(html, "html.parser")

        # Extract page title
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else url

        # Remove unwanted elements
        for tag_name in _REMOVE_TAGS:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        # Try to find the main content area
        main_content = (
            soup.find("main")
            or soup.find("article")
            or soup.find("div", {"role": "main"})
            or soup.find("div", class_=re.compile(r"(content|review|main)", re.I))
            or soup.body
        )

        if not main_content:
            log.warning("No content found at %s", url)
            return None

        # Extract text, preserving some structure
        text = _extract_text(main_content)

        if len(text) < 50:
            log.warning("Very little text extracted from %s (%d chars)", url, len(text))
            return None

        # Truncate if too long
        if len(text) > _MAX_CONTENT_LENGTH:
            text = text[:_MAX_CONTENT_LENGTH] + "\n\n[Content truncated...]"

        log.info("Fetched %d chars from %s", len(text), url)

        return build_search_result(
            title=title,
            url=url,
            content=text,
            score=1.0,
            source="direct_url",
            extra={"fetched_via": "url_fetcher"},
        )

    except httpx.HTTPStatusError as exc:
        log.warning("HTTP error fetching %s: %s", url, exc.response.status_code)
        return None
    except httpx.TimeoutException:
        log.warning("Timeout fetching %s", url)
        return None
    except Exception as exc:
        log.warning("Failed to fetch %s: %s", url, exc)
        return None


def _extract_text(element) -> str:
    """Extract readable text from a BeautifulSoup element.

    Preserves paragraph structure with double newlines between blocks.
    """
    blocks: list[str] = []
    for child in element.find_all(
        ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "td", "th", "div", "span"],
        recursive=True,
    ):
        text = child.get_text(separator=" ", strip=True)
        if text and len(text) > 10:  # Skip very short fragments
            blocks.append(text)

    if not blocks:
        # Fallback: just get all text
        return element.get_text(separator="\n", strip=True)

    # Deduplicate consecutive blocks (nested elements can repeat)
    deduped: list[str] = []
    seen_casefold: set[str] = set()
    for block in blocks:
        key = block.casefold()
        if key in seen_casefold:
            continue
        if not deduped or block != deduped[-1]:
            deduped.append(block)
            seen_casefold.add(key)

    return "\n\n".join(deduped)
