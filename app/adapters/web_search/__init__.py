"""Web search + URL fetch backends.

`fallback_chain.py` is the public entry point: it tries each configured
provider in turn (Tavily → Google CSE → Brave → DuckDuckGo) and returns
the first set of results. `url_fetcher.py` downloads and cleans up page
HTML for the `fetch_url` tool. `_common.py` holds shared dataclasses so
every provider returns the same result shape.

Which providers are active is controlled by API keys in `settings`; if
nothing is configured, DuckDuckGo (no-key) still works as a last resort.
"""
