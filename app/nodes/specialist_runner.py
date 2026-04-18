"""Single specialist runner for the simplified MCP-first flow."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.adapters.llm.lmstudio import get_text_llm
from app.adapters.neo4j.graphDB import GraphDB
from app.nodes.doc_analyst import doc_analyst
from app.core.prompts import (
    ACADEMIC_SPECIALIST_SYSTEM_PROMPT,
    CAREER_SPECIALIST_SYSTEM_PROMPT,
    GENERAL_SPECIALIST_SYSTEM_PROMPT,
)
from app.core.state import PathfinderState
from app.tools.graph_tools import get_driver as get_graph_driver
from app.tools.tools import ToolContext, build_tool_transcript_payload, execute_tool, get_tool_schemas
from app.utils.json_extract import parse_json_object
from app.utils.runtime_utils import build_recent_conversation_window

log = logging.getLogger("pathfinder.agents.specialist_runner")

_SPECIALIST_CONFIG = {
    "academic": {"title": "Academic Specialist", "prompt": ACADEMIC_SPECIALIST_SYSTEM_PROMPT},
    "career": {"title": "Career Specialist", "prompt": CAREER_SPECIALIST_SYSTEM_PROMPT},
    "general": {"title": "General Specialist", "prompt": GENERAL_SPECIALIST_SYSTEM_PROMPT},
}
_MESSAGE_FIELD_RE = re.compile(r'"message"\s*:\s*"((?:\\.|[^"])*)"', re.DOTALL)
_SPECIAL_TOKEN_RE = re.compile(r"<\|.*?\|>")


def _system_prompt(selected_specialist: str) -> str:
    specialist = _SPECIALIST_CONFIG.get(selected_specialist, _SPECIALIST_CONFIG["general"])
    return str(specialist["prompt"])


_NOT_FOUND_PHRASES = (
    "couldn't find",
    "could not find",
    "unable to find",
    "no specific",
    "i don't have",
    "not available",
    "i couldn't locate",
    "i was unable",
    "i could not locate",
    "did not find",
)


def _should_retry_web_search(payload: dict[str, Any], tool_log: list[dict[str, Any]]) -> bool:
    """Return True if the LLM gave up on a web-searchable question too early."""
    message = str(payload.get("message", "") or "").lower()
    if not any(phrase in message for phrase in _NOT_FOUND_PHRASES):
        return False
    search_count = sum(1 for t in tool_log if isinstance(t, dict) and t.get("tool") == "search_web")
    fetch_count = sum(1 for t in tool_log if isinstance(t, dict) and t.get("tool") == "fetch_url")
    return search_count < 2 or fetch_count < 2


def _extract_message_from_text(content: str) -> str:
    text = str(content or "").strip()
    parsed = parse_json_object(text)
    if isinstance(parsed, dict):
        message = str(parsed.get("message", "") or "").strip()
        if message:
            return _clean_message(message)

    match = _MESSAGE_FIELD_RE.search(text)
    if match:
        try:
            extracted = json.loads(f'"{match.group(1)}"')
        except Exception:
            extracted = match.group(1)
        extracted = str(extracted or "").strip()
        if extracted:
            return _clean_message(extracted)

    return _clean_message(text)


def _clean_message(content: str) -> str:
    text = str(content or "")
    text = _SPECIAL_TOKEN_RE.sub("", text)
    text = text.replace('\\"', '"').strip()
    if text.startswith("{") and '"message"' in text:
        maybe = _extract_message_from_text(text)
        if maybe and maybe != text:
            return maybe
    return text.strip().strip('"').strip()


async def _graph_db() -> GraphDB:
    return GraphDB(await get_graph_driver())


def _bounded_tool_value(value: Any, limit: int = 12000) -> Any:
    """Keep replay-facing tool payloads readable without dropping structure."""
    try:
        serialized = json.dumps(value, ensure_ascii=True, default=str)
    except Exception:
        return str(value)[:limit]
    if len(serialized) <= limit:
        return value
    return {
        "truncated": True,
        "preview": serialized[:limit],
        "original_size": len(serialized),
    }


def _normalize_specialist_payload(payload: dict[str, Any], session_context: str) -> dict[str, Any]:
    """Normalize the specialist final payload into the required runtime shape."""
    next_session_context = str(payload.get("next_session_context", "") or "").strip()
    if not next_session_context:
        next_session_context = session_context
    next_long_context = payload.get("next_long_context")
    if next_long_context in ("", [], {}):
        next_long_context = None
    return {
        "message": _clean_message(str(payload.get("message", "") or "")),
        "stop_reason": str(payload.get("stop_reason", "") or ""),
        "next_session_context": next_session_context,
        "next_long_context": next_long_context if next_long_context is None else str(next_long_context),
    }


async def specialist_runner(state: PathfinderState) -> PathfinderState:
    """Run the selected specialist with the canonical MCP-style tool surface."""
    selected_specialist = str(state.get("selected_specialist", "general") or "general")
    student_id = str(state.get("student_id", "") or "")
    session_id = str(state.get("session_id", "") or "")
    query = str(state.get("query", "") or "")

    step_progress = list(state.get("step_progress", []))
    step_progress.append(f"Running {selected_specialist.replace('_', ' ')} specialist...")

    working_state = dict(state)
    files = list(state.get("files", []))
    reasoning = str(state.get("reasoning", "medium") or "medium").strip().lower() or "medium"

    if files:
        step_progress.append("Pre-ingesting uploaded documents...")
        doc_state = await doc_analyst({**state, "step_progress": step_progress})
        working_state.update(doc_state)
        step_progress = list(doc_state.get("step_progress", step_progress))

    graph_db = await _graph_db()
    student = await graph_db.get_student(student_id=student_id) or {}
    student_schema = await graph_db.get_student_schema(student_id=student_id)
    raw_session_messages = working_state.get("messages", [])
    session_messages = list(raw_session_messages) if isinstance(raw_session_messages, list) else []
    session_context = str(working_state.get("session_context", "") or "").strip()
    long_context = str(student.get("long_context_summary", "") or "").strip()

    prompt_context = {
        "student_schema": student_schema,
        "recent_messages": build_recent_conversation_window(session_messages, limit=10),
        "session_context": session_context,
        "long_context": long_context,
    }

    llm = get_text_llm(reasoning).bind_tools(get_tool_schemas())
    tool_context = ToolContext(
        student_id=student_id,
        session_id=session_id,
        state={
            **working_state,
            "student_schema": student_schema,
            "session_context": session_context,
            "long_context": long_context,
        },
    )
    messages: list[Any] = [
        SystemMessage(content=_system_prompt(selected_specialist)),
        HumanMessage(
            content=(
                "User query:\n"
                f"{query}\n\n"
                "Specialist context:\n"
                f"{json.dumps(prompt_context, ensure_ascii=True)}\n\n"
                "Tool contract reminder:\n"
                "- Use MCP-style tools for graph, document, and web access.\n"
                "- Return final JSON only after you are done with tool use."
            )
        ),
    ]
    raw_tool_call_log = working_state.get("tool_call_log", [])
    tool_call_log = list(raw_tool_call_log) if isinstance(raw_tool_call_log, list) else []
    final_payload: dict[str, Any] = {}
    web_retry_used = False

    for _ in range(12):
        ai_msg = await llm.ainvoke(messages)
        messages.append(ai_msg)
        if not isinstance(ai_msg, AIMessage):
            break
        if ai_msg.tool_calls:
            responded = False
            for call in ai_msg.tool_calls[:6]:
                tool_name = str(call.get("name", "") or "")
                args = call.get("args", {}) if isinstance(call.get("args", {}), dict) else {}
                result = await execute_tool(tool_name, args, tool_context)
                compact = build_tool_transcript_payload(tool_name, args, result, tool_context)
                tool_call_log.append(
                    {
                        "call_id": str(call.get("id", "") or ""),
                        "tool": tool_name,
                        "input": args,
                        "args": args,
                        "status": str(compact.get("status") or ("error" if result.get("error") else "ok")),
                        "output": _bounded_tool_value(result),
                        "result_summary": compact,
                    }
                )
                messages.append(
                    ToolMessage(
                        content=json.dumps(compact, ensure_ascii=True, default=str),
                        tool_call_id=str(call.get("id", "") or ""),
                    )
                )
                if tool_name == "respond" and not result.get("error"):
                    final_payload = result
                    responded = True
            if responded:
                normalized = _normalize_specialist_payload(final_payload, session_context)
                if not web_retry_used and _should_retry_web_search(normalized, tool_call_log):
                    web_retry_used = True
                    nudge = (
                        "Your answer says you could not find the information, but "
                        "you have not exhausted web search options. Do NOT repeat "
                        "the same search. Change your strategy:\n"
                        "- Rephrase: broaden beyond specific names or codes — "
                        "search for the general process or policy instead.\n"
                        "- Pick a result whose title most closely matches what "
                        "the student is actually asking for.\n"
                        "- Fetch at least one URL you have not fetched yet.\n"
                        "Respond again with whatever you find — even partial "
                        "information is better than none. Include source URLs."
                    )
                    messages.append(HumanMessage(content=nudge))
                    final_payload = {}
                    log.info("Web-search retry nudge injected for student=%s", student_id)
                    continue
                final_payload = normalized
                break
            continue
        content = ai_msg.content if isinstance(ai_msg.content, str) else str(ai_msg.content)
        parsed = parse_json_object(content)
        if isinstance(parsed, dict):
            final_payload = _normalize_specialist_payload(parsed, session_context)
        else:
            final_payload = _normalize_specialist_payload(
                {
                    "message": _extract_message_from_text(content),
                    "stop_reason": "",
                    "next_session_context": session_context,
                    "next_long_context": None,
                },
                session_context,
            )
        break

    message = _clean_message(str(final_payload.get("message", "") or ""))
    if not message:
        message = "I could not generate a useful response for this request."
    step_progress.append(f"{selected_specialist.replace('_', ' ').title()} specialist completed")

    return {
        **working_state,
        "student_schema": student_schema,
        "session_context": session_context,
        "long_context": long_context,
        "selected_specialist": selected_specialist,
        "specialist_output": {
            "message": message,
            "stop_reason": final_payload.get("stop_reason", ""),
            "next_session_context": str(final_payload.get("next_session_context", "") or session_context),
            "next_long_context": final_payload.get("next_long_context"),
        },
        "tool_call_log": tool_call_log,
        "step_progress": step_progress,
    }
