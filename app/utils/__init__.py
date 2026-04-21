"""Cross-cutting helpers used by nodes, tools, and the API.

Unlike `app/adapters` (which wraps external services) or `app/tools`
(which exposes LLM-callable functions), this folder holds plain Python
helpers that multiple parts of the app happen to need:

- `ids.py`             : generators for stable, prefixed UUIDs (student,
                         session, document, chunk, field, replay).
- `json_extract.py`    : robust JSON parsing for model output (handles
                         code fences, trailing prose, stray braces).
- `progress.py`        : buffered + live "what is the agent doing right
                         now?" progress messages the SSE chat endpoint
                         streams to the browser.
- `runtime_utils.py`   : small helpers for shaping conversation history
                         and inferring the retrieval "method" of a turn.
- `ingest_common.py`   : shared summarizer both ingestion pipelines use
                         to turn their raw tool call logs into a tidy
                         `graph_updates` report.
- `document_ingest.py` : drives the document-ingestion agent — runs a
                         tool-calling loop that reads an uploaded file
                         and writes structured facts into the graph.
- `query_ingest.py`    : mirror of the above for chat messages —
                         harvests graph structure from what the user
                         just said, without touching chunks.

These modules never import from `app.nodes` or `app.api` — they sit
below those layers so anything can depend on them without cycles.
"""
