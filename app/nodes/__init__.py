"""LangGraph nodes — one file per step in a chat turn.

Every node is an `async def node(state)` function that returns an updated
state. The exact order they run in is defined in `app.core.workflow`:

    input_guard       -> block unsafe or empty queries up front
    orchestrator      -> pick the best specialist for the question
    query_ingestor    -> opportunistically harvest facts from the user's message
    specialist_runner -> run the selected specialist's tool-calling loop
    response_validator-> tidy the output and attach citations
    context_persister -> save rolling session/long-term context to Neo4j
    responder         -> hand the final answer back to the API layer
    doc_analyst       -> (sub-step) extract + ingest any uploaded files

Nothing here depends on FastAPI or the MCP server; these are pure
functions over `PathfinderState` so they're easy to test in isolation.
"""
