# MCP: Exposing Your Tools (Advanced, Optional)

The **Model Context Protocol (MCP)** lets external AI clients (IDEs, chat apps) call your agent's tools. Your system becomes a capability provider in a larger ecosystem.

---

## 1. How to Install

### 1.1 Prerequisites

- Running backend (see `backend-service-and-agent-graph.md`)
- MCP-aware client (e.g. Cursor, Claude Desktop, or custom)

### 1.2 Install MCP

```bash
pip install mcp
```

### 1.3 MCP Server vs Client

| Role | Description |
|------|-------------|
| **MCP Server** | Your backend exposes tools; clients connect to it. |
| **MCP Client** | An IDE or app that discovers and calls your tools. |

This guide focuses on **exposing your backend as an MCP server**.

---

## 2. Why Expose Tools via MCP

| Benefit | Description |
|---------|-------------|
| **Reuse** | Other agents/IDEs call your graph search, doc search, etc. without reimplementing. |
| **Integration** | Cursor, Claude Desktop, and similar tools can use your agent's capabilities. |
| **Composability** | Your system becomes a building block in a multi-agent setup. |
| **Thesis demo** | Shows your agent as a tool provider in an agent ecosystem. |

---

## 3. How to Set Up and Use

### 3.1 Choose Tools to Expose

Good candidates:

| Tool | Purpose |
|------|---------|
| `search_knowledge_graph` | Query Neo4j with a natural-language or structured query |
| `search_documents` | Semantic search over chunks; return text + metadata |
| `search_web` | Web search (if you have it) |
| `get_user_profile` | Return structured profile data |

Each tool should:

- Take JSON-serializable arguments (e.g. `query: str`, `user_id: str`).
- Return JSON-serializable results (dicts, lists, strings, numbers).
- Be safe for external callers (no destructive operations by default).

### 3.2 Define Tool Functions

```python
async def search_knowledge_graph(query: str, user_id: str = "default") -> dict:
    """Query the user's knowledge graph. Returns matching entities and relationships."""
    # Your Neo4j + embedding logic here
    results = [...]  # list of dicts
    return {"results": results}  # Must be JSON-serializable
```

### 3.3 Register with MCP Server

```python
from mcp import Server
from mcp.types import Tool, TextContent

# Create server and register tools
# (Exact API depends on mcp package version; see mcp docs)
server = Server("my-agent")
server.add_tool(
    Tool(
        name="search_knowledge_graph",
        description="Search the user's knowledge graph",
        inputSchema={
            "type": "object",
            "properties": {"query": {"type": "string"}, "user_id": {"type": "string"}},
            "required": ["query"],
        },
    ),
    handler=search_knowledge_graph,
)
```

### 3.4 Run the MCP Server

- Start the server so it listens on a port or stdio.
- Configure your MCP client to connect to that endpoint.
- Verify the client can list and call your tools.

---

## 4. Common Pitfalls and Fixes

| Symptom | Cause | Fix |
|---------|-------|-----|
| Client can't find server | Wrong host/port or server not running | Check server logs; verify connection config |
| Serialization errors on call | Returning Neo4j objects, custom classes | Convert to `dict`, `list`, `str`, `int`, `float` before returning |
| Slow or blocked calls | Long-running operations | Keep tools fast; split into smaller steps if needed |
| Tool not discoverable | Incorrect registration | Ensure tool has `name`, `description`, `inputSchema` |

---

## 5. Official Documentation

- **MCP Specification:** https://modelcontextprotocol.io/
- **MCP Python:** https://github.com/modelcontextprotocol/python-sdk
- **Anthropic MCP:** https://docs.anthropic.com/en/docs/build-with-claude/mcp
