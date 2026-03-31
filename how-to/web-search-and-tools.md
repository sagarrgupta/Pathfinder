# Web Search and External Tools (Optional)

Web search and other external tools let your agent use up-to-date or external data when local knowledge is insufficient. This guide covers adding such tools to your agent.

---

## 1. How to Install

### 1.1 Prerequisites

- Backend service running (see `backend-service-and-agent-graph.md`)
- (Optional) API keys for Tavily, Brave, or Google CSE

### 1.2 Install Packages

```bash
pip install tavily-python ddgs
# Optional:
# pip install google-api-python-client  # for Google CSE
```

### 1.3 Get API Keys (Optional)

| Provider | Sign Up | Free Tier | Notes |
|----------|---------|-----------|-------|
| **Tavily** | https://tavily.com | 1000 searches/month | AI-optimized, recommended |
| **Brave Search** | https://brave.com/search/api/ | 2000 queries/month | Good quality |
| **DuckDuckGo (ddgs)** | None | Unlimited | No key; use as fallback |
| **Google CSE** | https://programmablesearchengine.google.com | 100/day (free) | Requires CSE ID + API key |

Add keys to `.env`:

```env
TAVILY_API_KEY=tvly-xxxx
BRAVE_API_KEY=BSAxxxx
GOOGLE_CSE_API_KEY=xxxx
GOOGLE_CSE_ID=xxxx
```

---

## 2. Why Add Web Search or Tools

| Benefit | Description |
|---------|-------------|
| **Fresh data** | Access info not in your local graph or documents |
| **Grounded answers** | Cite real web sources instead of hallucinating |
| **Extensibility** | Same pattern for calendars, CRMs, code search, etc. |
| **Tool-using agent** | LLM decides when to call tools based on the task |

---

## 3. How to Set Up and Use

### 3.1 Implement a Search Function

```python
import os
from typing import Optional

def search_web(query: str, max_results: int = 5) -> list[dict]:
    """Search the web; fallback chain: Tavily -> DuckDuckGo."""
    # Try Tavily first if key is set
    tavily_key = os.environ.get("TAVILY_API_KEY")
    if tavily_key:
        try:
            from tavily import TavilyClient
            client = TavilyClient(api_key=tavily_key)
            resp = client.search(query, max_results=max_results)
            return [
                {"title": r["title"], "url": r["url"], "snippet": r.get("content", "")}
                for r in resp.get("results", [])
            ]
        except Exception:
            pass

    # Fallback to DuckDuckGo (no key needed)
    from ddgs import DDGS
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=max_results))
    return [
        {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
        for r in results
    ]
```

### 3.2 Expose as a LangChain Tool

```python
from langchain_core.tools import tool

@tool
def search_web_tool(query: str) -> str:
    """Search the web for current information. Use when local knowledge is insufficient."""
    results = search_web(query, max_results=5)
    return "\n\n".join([
        f"[{r['title']}]({r['url']})\n{r['snippet']}"
        for r in results
    ])
```

### 3.3 Use in Your Agent

- Add `search_web_tool` to the tools list for your planner or web-research node.
- The LLM will call it when it decides external search is needed.
- Pass the tool output as context into the next LLM call for answer generation.

### 3.4 Fallback Chain Pattern

Use a priority order: Tavily (best) → Brave → Google CSE → DuckDuckGo (unlimited). If one fails or hits rate limits, try the next.

---

## 4. Common Pitfalls and Fixes

| Symptom | Cause | Fix |
|---------|-------|-----|
| HTTP 401/403 | Missing or invalid API key | Check `.env`; verify key format |
| Rate limit exceeded | Too many requests | Cache queries; use DuckDuckGo fallback |
| Agent ignores results | Weak prompt | Add: "Use the provided search results as your primary source." |
| Backend crashes on tool call | No error handling | Wrap in try/except; return `{"error": "..."}` on failure |
| Timeout | Slow provider | Add timeout; fall back to next provider |

---

## 5. Generic HTTP Tool Pattern

For any external API (weather, CRM, code search):

1. **API function**: Handle auth, URL, parsing; return structured data (dicts/lists).
2. **LangChain tool**: Wrap with `@tool` and a clear description.
3. **Agent node**: Include tool in the node's tool list; LLM decides when to call it.
4. **Error handling**: On failure, return a safe result (e.g. "Tool unavailable") so the graph can continue.

---

## 6. Official Documentation

- **Tavily:** https://docs.tavily.com/
- **DuckDuckGo Search (ddgs):** https://pypi.org/project/duckduckgo-search/
- **LangChain Tools:** https://python.langchain.com/docs/modules/agents/tools/
