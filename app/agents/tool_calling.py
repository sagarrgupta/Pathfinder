"""Shared MCP-backed tool-calling loop for Pathfinder agents."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.config.settings import settings
from app.core.state import PathfinderState
from app.services.mcp_client import InternalMCPClient

log = logging.getLogger("pathfinder.agents.tool_calling")


def advisor_tool_schemas(state: PathfinderState) -> list[dict[str, Any]]:
    """Return the canonical MCP-backed tool schemas."""
    return InternalMCPClient(state=dict(state)).langchain_tool_schemas()


async def run_advisor_tool_loop(
    *,
    llm: Any,
    system_prompt: str,
    user_query: str,
    state: PathfinderState,
    max_rounds: int = 4,
) -> tuple[str, list[dict[str, Any]]]:
    """Run a bounded MCP-backed tool-calling loop and return answer + provenance."""
    client = InternalMCPClient(state=state)
    tool_llm = llm.bind_tools(client.langchain_tool_schemas())
    tool_call_log = _trim_tool_log(list(state.get("tool_call_log", [])))
    history_messages = _conversation_history_messages(state, current_user_query=user_query)
    messages: list[Any] = [SystemMessage(content=system_prompt), *history_messages, HumanMessage(content=user_query)]

    final_answer = ""
    for _ in range(max_rounds):
        ai_msg = await tool_llm.ainvoke(messages)
        messages.append(ai_msg)
        if not isinstance(ai_msg, AIMessage):
            final_answer = str(getattr(ai_msg, "content", "") or "")
            break

        if ai_msg.tool_calls:
            for call in ai_msg.tool_calls[:6]:
                call_id = str(call.get("id", ""))
                name = str(call.get("name", ""))
                args = call.get("args", {}) if isinstance(call.get("args", {}), dict) else {}
                result = await _execute_with_timeout(name=name, args=args, client=client)
                tool_call_log.append(
                    {
                        "tool": name,
                        "args": args,
                        "status": "ok" if result.get("ok") else "error",
                        "errors": list(result.get("errors", [])),
                        "citations": list(result.get("citations", [])),
                        "meta": dict(result.get("meta", {})),
                        "result_summary": _summarize_tool_result(result),
                    }
                )
                tool_call_log = _trim_tool_log(tool_call_log)
                messages.append(ToolMessage(content=json.dumps(result, ensure_ascii=True), tool_call_id=call_id))
            continue

        content = ai_msg.content if isinstance(ai_msg.content, str) else str(ai_msg.content)
        final_answer = content.strip()
        if final_answer:
            break

    if not final_answer:
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                if content.strip():
                    final_answer = content.strip()
                    break

    return final_answer, tool_call_log


async def _execute_with_timeout(
    *,
    name: str,
    args: dict[str, Any],
    client: InternalMCPClient,
) -> dict[str, Any]:
    """Execute one MCP tool with timeout protection."""
    try:
        return await asyncio.wait_for(
            client.call_tool(name, args),
            timeout=max(1.0, float(settings.TOOL_CALL_TIMEOUT_SECONDS)),
        )
    except asyncio.TimeoutError:
        log.warning("Tool timed out: %s(%s)", name, args)
        return {
            "ok": False,
            "data": {},
            "errors": [f"tool timeout after {settings.TOOL_CALL_TIMEOUT_SECONDS:.0f}s"],
            "citations": [],
            "meta": {"tool": name},
        }


def _summarize_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return a compact log-safe summary of tool output."""
    if not result.get("ok"):
        return {
            "errors": list(result.get("errors", []))[:3],
            "meta": dict(result.get("meta", {})),
        }
    data = result.get("data")
    if isinstance(data, dict):
        summary: dict[str, Any] = {}
        for key in ("query", "result_count", "candidate_count", "match_count", "completed_count", "planned_count"):
            if key in data:
                summary[key] = data[key]
        if "results" in data and isinstance(data.get("results"), list):
            summary["results_count"] = len(data["results"])
        if "matches" in data and isinstance(data.get("matches"), list):
            summary["matches_count"] = len(data["matches"])
        if "processed_files" in data and isinstance(data.get("processed_files"), list):
            summary["processed_files"] = data["processed_files"][:5]
        if "title" in data:
            summary["title"] = str(data.get("title", ""))[:120]
        if not summary:
            summary["keys"] = sorted(list(data.keys()))[:8]
        return summary
    if isinstance(data, list):
        return {"items": len(data)}
    return {"ok": True}


def _trim_tool_log(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only recent tool log entries to avoid context bloat."""
    limit = max(10, int(settings.TOOL_CALL_LOG_MAX_ENTRIES))
    if len(entries) <= limit:
        return entries
    return entries[-limit:]


def _conversation_history_messages(
    state: PathfinderState,
    *,
    current_user_query: str,
    max_messages: int = 8,
) -> list[Any]:
    """Convert recent persisted conversation turns into bounded model context."""
    raw_messages = list(state.get("messages", []) or [])
    history: list[Any] = []
    current_trimmed = " ".join(str(current_user_query or "").split())

    for raw in raw_messages:
        role = ""
        content = ""
        if isinstance(raw, tuple) and len(raw) == 2:
            role = str(raw[0] or "")
            content = str(raw[1] or "")
        elif hasattr(raw, "content"):
            role = str(getattr(raw, "type", "") or getattr(raw, "role", ""))
            content = str(getattr(raw, "content", "") or "")
        else:
            continue

        normalized = " ".join(content.split())
        if not normalized:
            continue
        if role in {"human", "user"}:
            if current_trimmed and normalized == current_trimmed:
                continue
            history.append(HumanMessage(content=content))
        elif role in {"assistant", "ai"}:
            history.append(AIMessage(content=content))

    if max_messages > 0 and len(history) > max_messages:
        history = history[-max_messages:]
    return history
