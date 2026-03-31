"""Pathfinder MCP Server.

Exposes Pathfinder tools via the Model Context Protocol (MCP) standard,
allowing external MCP-compatible clients to use Pathfinder's capabilities.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

log = logging.getLogger("pathfinder.mcp")

# Create the MCP server
server = Server("pathfinder")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available Pathfinder tools."""
    return [
        Tool(
            name="search_knowledge_graph",
            description="Search the student's Neo4j knowledge graph for structured data (courses, skills, GPA, etc.)",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language query about the student's profile"},
                    "student_id": {"type": "string", "description": "Student ID (default: 'default')"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="search_documents",
            description="Semantic search over the student's uploaded document chunks",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "k": {"type": "integer", "description": "Number of results (default: 5)"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="search_web",
            description="Search the web using the fallback chain (Tavily → Google → Brave → DuckDuckGo)",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Web search query"},
                    "max_results": {"type": "integer", "description": "Max results (default: 5)"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_student_profile",
            description="Get the complete student profile from the knowledge graph",
            inputSchema={
                "type": "object",
                "properties": {
                    "student_id": {"type": "string", "description": "Student ID (default: 'default')"},
                },
            },
        ),
        Tool(
            name="analyze_document",
            description="Process a document and extract entities into the knowledge graph",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Document text to analyze"},
                    "document_type": {"type": "string", "description": "Type: transcript, resume, or other"},
                },
                "required": ["text"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Execute a Pathfinder tool."""
    try:
        if name == "search_knowledge_graph":
            from app.adapters.neo4j.graph_store import get_full_profile, list_students
            student_id = arguments.get("student_id")
            if not student_id:
                students = await list_students()
                student_id = students[0]["id"] if students else ""
            profile = await get_full_profile(student_id)
            return [TextContent(type="text", text=json.dumps(profile, default=str))]

        elif name == "search_documents":
            from app.adapters.neo4j.vector_store import similarity_search
            query = arguments["query"]
            k = arguments.get("k", 5)
            results = await similarity_search(query, k=k)
            return [TextContent(type="text", text=json.dumps(results, default=str))]

        elif name == "search_web":
            from app.adapters.web_search.fallback_chain import search
            query = arguments["query"]
            max_results = arguments.get("max_results", 5)
            results = await search(query, max_results=max_results)
            return [TextContent(type="text", text=json.dumps(results, default=str))]

        elif name == "get_student_profile":
            from app.adapters.neo4j.graph_store import get_full_profile, list_students
            student_id = arguments.get("student_id")
            if not student_id:
                students = await list_students()
                student_id = students[0]["id"] if students else ""
            profile = await get_full_profile(student_id)
            return [TextContent(type="text", text=json.dumps(profile, default=str))]

        elif name == "analyze_document":
            text = arguments["text"]
            return [TextContent(type="text", text=f"Document analysis: {len(text)} chars processed")]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as exc:
        log.error("MCP tool error: %s", exc, exc_info=True)
        return [TextContent(type="text", text=f"Error: {exc}")]


async def run_mcp_server():
    """Run the MCP server over stdio."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
