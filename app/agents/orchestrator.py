"""MCP-first orchestration node for Pathfinder."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.adapters.llm.lmstudio import get_text_llm
from app.agents.tool_calling import run_advisor_tool_loop
from app.core.prompts import MCP_ORCHESTRATOR_SYSTEM_PROMPT
from app.core.state import PathfinderState
from app.services.mcp_client import InternalMCPClient

log = logging.getLogger("pathfinder.agents.orchestrator")


async def orchestrator(state: PathfinderState) -> PathfinderState:
    """Run the MCP-first orchestration loop and produce the draft answer."""
    query = str(state.get("query", "")).strip()
    step_progress = list(state.get("step_progress", []))
    step_progress.append("Preparing Pathfinder MCP tool environment...")

    client = InternalMCPClient(
        state=state,
        runtime_snapshot=(state.get("runtime_snapshot", {}) if isinstance(state.get("runtime_snapshot", {}), dict) else {}),
    )
    tool_descriptors = await client.list_tools()
    llm = get_text_llm()
    system_prompt = _build_mcp_system_prompt(tool_descriptors)
    preflight_tool_log: list[dict[str, Any]] = []

    step_progress.append("Running required web search...")
    forced_web_result = await client.call_tool("search_web", {"query": query, "max_results": 5})
    preflight_tool_log.append(
        {
            "tool": "search_web",
            "args": {"query": query, "max_results": 5},
            "status": "ok" if forced_web_result.get("ok") else "error",
            "errors": list(forced_web_result.get("errors", [])),
            "citations": list(forced_web_result.get("citations", [])),
            "meta": dict(forced_web_result.get("meta", {})),
            "result_summary": _tool_result_summary(forced_web_result),
        }
    )
    state["tool_call_log"] = list(preflight_tool_log)

    user_payload = _build_user_payload(state)

    step_progress.append("Running local MCP-first reasoning...")
    answer, tool_call_log = await run_advisor_tool_loop(
        llm=llm,
        system_prompt=system_prompt,
        user_query=user_payload,
        state=state,
        max_rounds=5,
    )
    tool_call_log = _merge_tool_logs(preflight_tool_log, tool_call_log)

    citations = _citations_from_tool_log(tool_call_log)
    state["tool_call_log"] = tool_call_log
    state["citations"] = citations
    state["plan"] = _unique_tool_names(tool_call_log)
    state["mcp_tool_calls"] = list(tool_call_log)
    step_progress.append(
        f"MCP orchestration complete: {len(tool_call_log)} tool call(s), {len(citations)} citation(s)"
    )

    return {
        **state,
        "intent": "mcp_orchestrated",
        "missing_info": [],
        "draft_answer": answer.strip(),
        "citations": citations,
        "tool_call_log": tool_call_log,
        "plan": _unique_tool_names(tool_call_log),
        "mcp_tool_calls": list(tool_call_log),
        "next_node": "evaluator",
        "step_progress": step_progress,
    }


def _build_mcp_system_prompt(tool_descriptors: list[dict[str, Any]]) -> str:
    lines = [MCP_ORCHESTRATOR_SYSTEM_PROMPT.strip(), "", "Available Pathfinder MCP tools:"]
    for item in tool_descriptors:
        lines.append(
            f"- {item.get('name', '')}: {item.get('description', '')} "
            f"When to use: {item.get('guidance', '')}"
        )
    return "\n".join(lines)


def _build_user_payload(state: PathfinderState) -> str:
    request_plan = state.get("request_plan", {}) if isinstance(state.get("request_plan", {}), dict) else {}
    recent_messages = _recent_messages_payload(state.get("messages", []))
    payload = {
        "user_query": state.get("query", ""),
        "session_id": state.get("session_id", ""),
        "student_id": state.get("student_id", ""),
        "advisor_mode": state.get("advisor_mode", ""),
        "uploaded_files": [item.get("filename", "") for item in list(state.get("files", []) or []) if isinstance(item, dict)],
        "request_plan": request_plan,
        "runtime_policy": state.get("runtime_policy", {}),
        "recent_messages": recent_messages,
        "session_summary": state.get("session_summary", {}),
        "session_memory": state.get("session_memory", {}),
        "compacted_session": state.get("compacted_session", {}),
        "working_memory": state.get("working_memory", {}),
        "preloaded_web_context": list(state.get("web_results", []))[:5],
        "instructions": [
            "Use recent_messages plus session_memory and compacted_session as conversation continuity context.",
            "A web search has already been run for this turn. Use that evidence first, and call fetch_url or more web tools if you need to deepen or verify it.",
            "Call tools when facts or evidence are needed.",
            "Do not invent current or official information.",
            "Return the final answer as plain text after tool use is complete.",
        ],
    }
    return json.dumps(payload, ensure_ascii=True)


def _citations_from_tool_log(tool_call_log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in tool_call_log:
        if not isinstance(item, dict):
            continue
        for citation in item.get("citations", []) or []:
            if not isinstance(citation, dict):
                continue
            key = (
                str(citation.get("title", "")),
                str(citation.get("url", "")),
                str(citation.get("snippet", ""))[:120],
            )
            if key in seen:
                continue
            seen.add(key)
            citations.append(citation)
    return citations[:12]


def _unique_tool_names(tool_call_log: list[dict[str, Any]]) -> list[str]:
    ordered: list[str] = []
    for item in tool_call_log:
        name = str(item.get("tool", "")).strip()
        if name and name not in ordered:
            ordered.append(name)
    return ordered


def _merge_tool_logs(
    preflight_tool_log: list[dict[str, Any]],
    runtime_tool_log: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged = list(preflight_tool_log)
    for item in runtime_tool_log:
        merged.append(item)
    return merged


def _tool_result_summary(result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("ok"):
        return {
            "errors": list(result.get("errors", []))[:3],
            "meta": dict(result.get("meta", {})),
        }
    data = result.get("data")
    if isinstance(data, dict):
        if "results" in data and isinstance(data.get("results"), list):
            return {"results_count": len(data["results"])}
        if "candidates" in data and isinstance(data.get("candidates"), list):
            return {"candidate_count": len(data["candidates"])}
        return {"keys": sorted(list(data.keys()))[:8]}
    return {"ok": True}


def _recent_messages_payload(messages: list[Any], max_messages: int = 8) -> list[dict[str, str]]:
    """Serialize a bounded recent transcript for the MCP orchestration model."""
    serialized: list[dict[str, str]] = []
    for raw in list(messages or []):
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
        normalized_role = "user" if role in {"human", "user"} else "assistant" if role in {"assistant", "ai"} else ""
        snippet = " ".join(content.split())
        if not normalized_role or not snippet:
            continue
        serialized.append(
            {
                "role": normalized_role,
                "content": snippet[:500] + ("..." if len(snippet) > 500 else ""),
            }
        )
    if max_messages > 0 and len(serialized) > max_messages:
        serialized = serialized[-max_messages:]
    return serialized
