"""Exposes Pathfinder's tools over the Model Context Protocol (MCP).

MCP lets external clients (Claude Desktop, IDE agents, other LLM runners)
talk to the same tool surface the in-process workflow uses. This file
wraps the shared registry in an MCP stdio server: `list_tools` advertises
what's available, and `call_tool` dispatches one call.

No profile enforcement here — any caller connected over the MCP socket
sees the full tool surface. That's appropriate because MCP is for
trusted integrations; untrusted callers should use the HTTP API, which
runs the agent profiles via `execute_agent_tool`.
"""

from __future__ import annotations

import json
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent

from app.tools.tools import ToolContext, execute_tool, get_mcp_tools
from app.utils.ids import generate_student_id

log = logging.getLogger("pathfinder.mcp")

server = Server("pathfinder")


@server.list_tools()
async def list_tools():
    """Return the full set of MCP-shaped tool definitions."""
    return get_mcp_tools()


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, object]):
    """Execute one tool and return its JSON result as MCP TextContent.

    We pull `student_id` / `session_id` out of the arguments to build a
    `ToolContext` (same shape the workflow uses). If the client forgot to
    send a student id, we mint a fresh one so the call still succeeds
    against per-student data structures.
    """
    try:
        payload = dict(arguments or {})
        student_id = str(payload.get("student_id", "") or generate_student_id())
        session_id = str(payload.get("session_id", "") or "")
        result = await execute_tool(name, payload, ToolContext(student_id=student_id, session_id=session_id))
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=True, default=str))]
    except Exception as exc:
        # Errors are wrapped as plain text so the MCP client always gets a
        # reply and can surface the message to the user/agent.
        log.error("MCP tool error: %s", exc, exc_info=True)
        return [TextContent(type="text", text=f"Error: {exc}")]


async def run_mcp_server():
    """Start the MCP stdio server (blocks until the client disconnects)."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
