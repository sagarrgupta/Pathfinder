"""Shared tool registry package for Pathfinder.

The `tools` folder is the "hands" of every agent. Each file here
registers a set of `ToolSpec`s — self-describing functions the LLM can
call via MCP / OpenAI tool-calling:

- `tools.py`        : the registry itself (specs, profiles, execution wrappers).
- `graph_tools.py`  : read/write the student knowledge graph in Neo4j.
- `vector_tools.py` : manage chunk embeddings and similarity search.
- `web_tools.py`    : live web search and URL fetch (optional providers).
- `utility_tools.py`: the terminal `respond` tool used to finish a turn.
- `mcp_server.py`   : exposes the same tool surface over an MCP stdio server.

Agents (document ingester, query ingester, specialist) each see only a
subset of these tools — enforced by `_AGENT_TOOL_EXCLUSIONS` in `tools.py`
so the model physically cannot call something outside its role.
"""
