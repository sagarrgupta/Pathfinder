"""Shared plumbing for every web-search provider.

All providers (Tavily, Google CSE, Brave, DuckDuckGo) return different
raw payloads. Each provider-specific file normalizes its response using
the helpers here so `fallback_chain.search` can treat every result the
same way and the LLM tools get a single, stable shape back.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

# Hard ceiling on how many results any single provider can return. Keeps
# tool responses small enough to fit comfortably in the LLM transcript.
_MAX_RESULTS_LIMIT = 10


def normalize_query(query: str) -> str:
    """Collapse whitespace so different tabs/newlines don't look like new queries."""
    return " ".join(str(query or "").split()).strip()


def clamp_max_results(max_results: int) -> int:
    """Keep caller-specified `max_results` within [1, 10] no matter what."""
    return max(1, min(int(max_results), _MAX_RESULTS_LIMIT))


def normalize_url(url: str) -> str:
    """Normalize a URL so dedup works across providers.

    Lowercases scheme + host, drops fragments, strips trailing slashes —
    the exact same page returned by two providers should hash to one
    URL after this.
    """
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        cleaned = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))
        return cleaned.rstrip("/")
    except Exception:
        return raw.rstrip("/")


def build_search_result(
    *,
    title: str,
    url: str,
    content: str,
    source: str,
    score: float = 0.0,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Standard result dict every provider emits.

    Returns `None` when the hit is unusable (no URL, no title and no
    content) so the caller can drop it without extra validation.
    `source` records which provider produced the hit so the frontend
    can badge citations.
    """
    normalized_url = normalize_url(url)
    normalized_title = " ".join(str(title or "").split()).strip()
    normalized_content = " ".join(str(content or "").split()).strip()
    if not normalized_url or not (normalized_title or normalized_content):
        return None
    payload = {
        "title": normalized_title or normalized_url,
        "url": normalized_url,
        "content": normalized_content,
        "score": float(score or 0.0),
        "source": source,
    }
    if extra:
        payload.update(extra)
    return payload


def dedupe_results(results: list[dict[str, Any]], max_results: int) -> list[dict[str, Any]]:
    """Drop duplicate URLs (post-normalization) and cap to `max_results`."""
    deduped: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for item in results:
        url = normalize_url(str(item.get("url") or ""))
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        candidate = dict(item)
        candidate["url"] = url
        deduped.append(candidate)
        if len(deduped) >= clamp_max_results(max_results):
            break
    return deduped
