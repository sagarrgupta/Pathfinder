"""Pathfinder MCP server    """

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
    """Expose the shared tool surface as MCP tools."""
    return get_mcp_tools()


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, object]):
    """Dispatch one tool through the shared tool surface."""
    try:
        payload = dict(arguments or {})
        student_id = str(payload.get("student_id", "") or generate_student_id())
        session_id = str(payload.get("session_id", "") or "")
        result = await execute_tool(name, payload, ToolContext(student_id=student_id, session_id=session_id))
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=True, default=str))]
    except Exception as exc:
        log.error("MCP tool error: %s", exc, exc_info=True)
        return [TextContent(type="text", text=f"Error: {exc}")]


async def run_mcp_server():
    """Run the MCP server over stdio."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
