"""Shared LM Studio tool-calling loop for advisor agents."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.adapters.neo4j.graph_store import update_student
from app.adapters.web_search.url_fetcher import fetch_url_content
from app.config.settings import settings
from app.core.state import PathfinderState
from app.services.execution_registry import execute_web_search

log = logging.getLogger("pathfinder.agents.tool_calling")


def advisor_tool_schemas() -> list[dict[str, Any]]:
    """OpenAI-style tool schemas for advisor agents."""
    return [
        {
            "type": "function",
            "function": {
                "name": "get_student_profile",
                "description": "Load the student's current academic and career profile.",
                "strict": True,
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_web",
                "description": "Search the web for official pages, catalogs, requirements, or market data.",
                "strict": True,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_url",
                "description": "Fetch and read a specific webpage URL.",
                "strict": True,
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_student_documents",
                "description": "Search uploaded student documents for matching text snippets.",
                "strict": True,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 10},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "update_student_profile",
                "description": "Persist a small set of student profile fields when user shares new facts.",
                "strict": True,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "updates": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "gpa": {"type": "string"},
                                "university": {"type": "string"},
                                "program": {"type": "string"},
                                "semester": {"type": "string"},
                                "email": {"type": "string"},
                            },
                            "additionalProperties": False,
                        }
                    },
                    "required": ["updates"],
                    "additionalProperties": False,
                },
            },
        },
    ]


async def run_advisor_tool_loop(
    *,
    llm: Any,
    system_prompt: str,
    user_query: str,
    state: PathfinderState,
    max_rounds: int = 4,
) -> tuple[str, list[dict[str, Any]]]:
    """Run a bounded tool-calling loop and return final answer + provenance log."""
    tool_llm = llm.bind_tools(advisor_tool_schemas())
    tool_call_log = _trim_tool_log(list(state.get("tool_call_log", [])))
    messages: list[Any] = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_query),
    ]

    final_answer = ""
    for _ in range(max_rounds):
        ai_msg = await tool_llm.ainvoke(messages)
        messages.append(ai_msg)
        if not isinstance(ai_msg, AIMessage):
            final_answer = str(getattr(ai_msg, "content", "") or "")
            break

        if ai_msg.tool_calls:
            for call in ai_msg.tool_calls[:4]:
                call_id = str(call.get("id", ""))
                name = str(call.get("name", ""))
                args = call.get("args", {}) if isinstance(call.get("args", {}), dict) else {}
                result = await _execute_with_timeout(name=name, args=args, state=state)
                tool_call_log.append({
                    "tool": name,
                    "args": args,
                    "status": "ok" if not result.get("error") else "error",
                    "result_summary": _summarize_tool_result(result),
                })
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


async def _execute_with_timeout(*, name: str, args: dict[str, Any], state: PathfinderState) -> dict[str, Any]:
    """Execute a tool with timeout protection."""
    try:
        return await asyncio.wait_for(
            _execute_advisor_tool(name=name, args=args, state=state),
            timeout=max(1.0, float(settings.TOOL_CALL_TIMEOUT_SECONDS)),
        )
    except asyncio.TimeoutError:
        log.warning("Tool timed out: %s(%s)", name, args)
        return {"error": f"tool timeout after {settings.TOOL_CALL_TIMEOUT_SECONDS:.0f}s"}


async def _execute_advisor_tool(*, name: str, args: dict[str, Any], state: PathfinderState) -> dict[str, Any]:
    """Dispatch advisor tool call to Python implementation."""
    try:
        if name == "get_student_profile":
            return {"profile": state.get("profile_data", {})}

        if name == "search_web":
            query = str(args.get("query", "")).strip()
            max_results = int(args.get("max_results", 5) or 5)
            if not query:
                return {"error": "query is required"}
            results = await execute_web_search(query, max_results=max(1, min(max_results, 10)))
            return {"results": results[:10]}

        if name == "fetch_url":
            url = str(args.get("url", "")).strip()
            if not url:
                return {"error": "url is required"}
            result = await fetch_url_content(url)
            return {"result": result or {}, "error": "" if result else "fetch failed"}

        if name == "search_student_documents":
            query = str(args.get("query", "")).strip().lower()
            top_k = int(args.get("top_k", 5) or 5)
            if not query:
                return {"error": "query is required"}
            documents = list(state.get("retrieved_documents", []))
            hits = []
            for doc in documents:
                text = str(doc.get("text", ""))
                if query in text.lower():
                    hits.append({
                        "filename": doc.get("filename", ""),
                        "page_number": doc.get("page_number", ""),
                        "snippet": text[:400],
                    })
                if len(hits) >= max(1, min(top_k, 10)):
                    break
            return {"matches": hits}

        if name == "update_student_profile":
            student_id = str(state.get("student_id", "")).strip()
            updates = args.get("updates", {}) if isinstance(args.get("updates", {}), dict) else {}
            if not student_id:
                return {"error": "student_id missing"}
            clean = {k: str(v) for k, v in updates.items() if v not in (None, "")}
            if not clean:
                return {"error": "no valid updates provided"}
            updated = await update_student(student_id, **clean)
            return {"updated": updated}

        return {"error": f"unknown tool: {name}"}
    except Exception as exc:  # pragma: no cover - defensive in runtime loop
        log.warning("Tool execution failed: %s(%s) -> %s", name, args, exc)
        return {"error": str(exc)}


def _summarize_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return compact log-safe summary of tool output."""
    if result.get("error"):
        return {"error": str(result.get("error", ""))[:300]}
    if "results" in result and isinstance(result.get("results"), list):
        return {"results_count": len(result["results"])}
    if "matches" in result and isinstance(result.get("matches"), list):
        return {"matches_count": len(result["matches"])}
    if "result" in result and isinstance(result.get("result"), dict):
        payload = result["result"]
        return {
            "title": str(payload.get("title", ""))[:120],
            "url": str(payload.get("url", ""))[:200],
            "content_chars": len(str(payload.get("content", ""))),
        }
    if "updated" in result and isinstance(result.get("updated"), dict):
        return {"updated_fields": list(result["updated"].keys())[:8]}
    return {"ok": True}


def _trim_tool_log(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only recent tool log entries to avoid context bloat."""
    limit = max(10, int(settings.TOOL_CALL_LOG_MAX_ENTRIES))
    if len(entries) <= limit:
        return entries
    return entries[-limit:]
