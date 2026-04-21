"""Adapters for external services Pathfinder talks to.

Every subpackage here wraps one external dependency so the rest of the
app can stay ignorant of vendor-specific APIs:

- `neo4j/`       : async driver + `GraphDB` / `VectorDB` helpers that
                   speak Cypher on our behalf.
- `embeddings/`  : Ollama embeddings client (used by the vector store
                   and the hybrid retriever).
- `llm/`         : LM Studio chat + tool-calling client (used by every
                   LangGraph node that invokes the LLM).
- `pdf/`         : PDF / docx / image text extraction for file uploads.
- `web_search/`  : pluggable web search providers (Tavily, Google CSE,
                   Brave, DuckDuckGo) behind a single fallback chain.

If Pathfinder ever swaps a backend (e.g. a different vector DB), only
its adapter needs to change — nothing in `nodes/` or `tools/` reaches
past this layer.
"""
