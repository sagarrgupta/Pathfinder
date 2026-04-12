"""Internal Pathfinder MCP client used by the in-app orchestration runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.mcp_tools import execute_pathfinder_tool, list_tool_descriptors, to_langchain_tool_schemas


@dataclass
class InternalMCPClient:
    """Lightweight adapter over the canonical Pathfinder MCP tool registry."""

    state: dict[str, Any]
    runtime_snapshot: dict[str, Any] | None = None

    def context(self) -> dict[str, Any]:
        """Build tool execution context."""
        return {
            "state": self.state,
            "runtime_snapshot": dict(self.runtime_snapshot or {}),
        }

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return all registered tool descriptors."""
        return list_tool_descriptors()

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute one tool and return the canonical envelope."""
        return await execute_pathfinder_tool(name, arguments or {}, context=self.context())

    def langchain_tool_schemas(self) -> list[dict[str, Any]]:
        """Return OpenAI-style schemas for tool calling."""
        return to_langchain_tool_schemas()
