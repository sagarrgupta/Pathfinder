"""Pathfinder MCP server backed by the canonical internal tool registry."""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from app.services.mcp_tools import execute_pathfinder_tool, list_tool_descriptors

log = logging.getLogger("pathfinder.mcp")

server = Server("pathfinder")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available Pathfinder tools."""
    return [
        Tool(
            name=item["name"],
            description=item["description"],
            inputSchema=item["inputSchema"],
        )
        for item in list_tool_descriptors()
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Execute a Pathfinder tool and return the canonical JSON envelope."""
    result = await execute_pathfinder_tool(name, arguments or {}, context={"state": {}})
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=True, default=str))]


async def run_mcp_server() -> None:
    """Run the MCP server over stdio."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
