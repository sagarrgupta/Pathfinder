"""Single specialist runner for the simplified MCP-first flow."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.adapters.neo4j.graph_store import get_full_profile, get_relevant_memories
from app.adapters.neo4j.vector_store import hybrid_search
from app.adapters.llm.lmstudio import get_text_llm
from app.agents.doc_analyst import doc_analyst
from app.core.prompts import (
    ACADEMIC_SPECIALIST_SYSTEM_PROMPT,
    CAREER_SPECIALIST_SYSTEM_PROMPT,
    GENERAL_SPECIALIST_SYSTEM_PROMPT,
)
from app.core.quality import build_session_summary
from app.core.state import PathfinderState
from app.services.long_context import build_long_context_payload
from app.tools.registry import ToolContext, compact_result, execute_tool, get_tool_schemas
from app.utils.json_extract import parse_json_object

log = logging.getLogger("pathfinder.agents.specialist_runner")

_SPECIALIST_CONFIG = {
    "academic": {"title": "Academic Specialist", "prompt": ACADEMIC_SPECIALIST_SYSTEM_PROMPT},
    "career": {"title": "Career Specialist", "prompt": CAREER_SPECIALIST_SYSTEM_PROMPT},
    "general": {"title": "General Specialist", "prompt": GENERAL_SPECIALIST_SYSTEM_PROMPT},
}
_MESSAGE_FIELD_RE = re.compile(r'"message"\s*:\s*"((?:\\.|[^"])*)"', re.DOTALL)
_SPECIAL_TOKEN_RE = re.compile(r"<\|.*?\|>")


def _recent_messages(messages: list[Any], limit: int = 8) -> list[dict[str, str]]:
    recent = []
    for msg in messages[-limit:]:
        if isinstance(msg, tuple) and len(msg) == 2:
            role = "user" if str(msg[0]) in {"human", "user"} else "assistant"
            recent.append({"role": role, "content": str(msg[1])})
        elif hasattr(msg, "content"):
            role_name = str(getattr(msg, "type", "") or getattr(msg, "role", ""))
            role = "user" if role_name in {"human", "user"} else "assistant"
            recent.append({"role": role, "content": str(getattr(msg, "content", "") or "")})
    return recent


def _manifest(profile: dict[str, Any], memories: dict[str, Any]) -> dict[str, Any]:
    all_entities = profile.get("all_entities", {}) if isinstance(profile.get("all_entities", {}), dict) else {}
    documents = all_entities.get("Document", []) if isinstance(all_entities.get("Document", []), list) else []
    document_groups: dict[str, int] = {}
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        group = str(doc.get("document_role") or doc.get("doc_type") or "unknown")
        document_groups[group] = document_groups.get(group, 0) + 1
    return {
        "graph_entity_types": {
            label: len(items)
            for label, items in all_entities.items()
            if isinstance(items, list) and items
        },
        "documents": {
            "count": len(documents),
            "groups": document_groups,
        },
        "memory_buckets": {
            key: len(value)
            for key, value in memories.items()
            if isinstance(value, list)
        },
    }


def _small_facts(profile: dict[str, Any], session_summary: dict[str, Any]) -> dict[str, Any]:
    from app.services.long_context import _small_facts as _shared_small_facts
    return _shared_small_facts(profile, session_summary)


def _system_prompt(selected_specialist: str) -> str:
    specialist = _SPECIALIST_CONFIG.get(selected_specialist, _SPECIALIST_CONFIG["general"])
    return str(specialist["prompt"])


_NOT_FOUND_PHRASES = (
    "couldn't find", "could not find", "unable to find", "no specific",
    "i don't have", "not available", "i couldn't locate",
    "i was unable", "i could not locate", "did not find",
)


def _should_retry_web_search(
    payload: dict[str, Any],
    tool_log: list[dict[str, Any]],
) -> bool:
    """Return True if the LLM gave up on a web-searchable question too early.

    Criteria: the answer contains a "not found" phrase AND the LLM used
    fewer than 2 distinct search_web calls or fewer than 2 fetch_url calls.
    """
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
    profile = working_state.get("profile_data", {}) if isinstance(working_state.get("profile_data", {}), dict) else {}
    reasoning = str(state.get("reasoning", "medium") or "medium").strip().lower() or "medium"

    if files:
        step_progress.append("Pre-ingesting uploaded documents...")
        doc_state = await doc_analyst({**state, "step_progress": step_progress})
        working_state.update(doc_state)
        step_progress = list(doc_state.get("step_progress", step_progress))

    profile = await get_full_profile(student_id)
    session_messages = list(working_state.get("messages", []))
    session_summary = build_session_summary(profile, session_messages, query)
    memories = await get_relevant_memories(student_id, query, limit=6)
    retrieved_documents = await hybrid_search(
        query=query,
        k=5,
        student_id=student_id,
        session_id=session_id or None,
    )

    short_context = {
        "recent_messages": _recent_messages(session_messages),
        "session_summary": session_summary,
        "profile_schema": profile.get("profile_schema", {}),
    }
    latest_ingestion = working_state.get("latest_ingestion_result", {}) if isinstance(working_state.get("latest_ingestion_result", {}), dict) else {}
    patch_summaries = list(latest_ingestion.get("patch_summaries", []) or [])
    if patch_summaries:
        short_context["document_ingestion"] = [
            {
                "filename": item.get("filename", ""),
                "student_updates": item.get("student_updates", {}),
                "context_updates": item.get("context_updates", {}),
                "entity_count": item.get("entity_count", 0),
                "relationship_count": item.get("relationship_count", 0),
            }
            for item in patch_summaries[:4]
            if isinstance(item, dict)
        ]
    long_context = {
        **build_long_context_payload(profile, session_summary),
        "memory_buckets": {
            key: len(value)
            for key, value in memories.items()
            if isinstance(value, list)
        },
        "manifest": _manifest(profile, memories),
        "small_facts": _small_facts(profile, session_summary),
    }
    long_term_points: list[str] = []
    for item in patch_summaries[:4]:
        if not isinstance(item, dict):
            continue
        context_updates = item.get("context_updates", {}) if isinstance(item.get("context_updates", {}), dict) else {}
        for point in list(context_updates.get("long_term_summary_points", []) or []):
            text = str(point or "").strip()
            if text and text not in long_term_points:
                long_term_points.append(text)
    if long_term_points:
        long_context["recent_document_highlights"] = long_term_points[:12]

    llm = get_text_llm(reasoning).bind_tools(get_tool_schemas())
    tool_context = ToolContext(
        student_id=student_id,
        session_id=session_id,
        state={
            **working_state,
            "profile_data": profile,
            "session_summary": session_summary,
            "semantic_memory": memories,
            "retrieved_documents": retrieved_documents,
        },
    )
    messages: list[Any] = [
        SystemMessage(content=_system_prompt(selected_specialist)),
        HumanMessage(
            content=(
                "User query:\n"
                f"{query}\n\n"
                "Short-term context:\n"
                f"{json.dumps(short_context, ensure_ascii=True)}\n\n"
                "Long-term context:\n"
                f"{json.dumps(long_context, ensure_ascii=True)}\n\n"
                "Tool contract reminder:\n"
                "- Use MCP-style tools for graph, document, memory, and web access.\n"
                "- Return final JSON only after you are done with tool use."
            )
        ),
    ]
    tool_call_log = list(working_state.get("tool_call_log", []))
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
                compact = compact_result(result)
                tool_call_log.append(
                    {
                        "call_id": str(call.get("id", "") or ""),
                        "tool": tool_name,
                        "input": args,
                        "args": args,
                        "status": "ok" if not result.get("error") else "error",
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
                if not web_retry_used and _should_retry_web_search(final_payload, tool_call_log):
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
                break
            continue
        content = ai_msg.content if isinstance(ai_msg.content, str) else str(ai_msg.content)
        parsed = parse_json_object(content)
        if isinstance(parsed, dict):
            final_payload = parsed
        else:
            final_payload = {
                "message": _extract_message_from_text(content),
                "memory_patch": None,
                "provenance": [],
                "stop_reason": "",
            }
        break

    message = _clean_message(str(final_payload.get("message", "") or ""))
    if not message:
        message = "I could not generate a useful response for this request."
    step_progress.append(f"{selected_specialist.replace('_', ' ').title()} specialist completed")

    return {
        **working_state,
        "profile_data": profile,
        "session_summary": session_summary,
        "semantic_memory": memories,
        "retrieved_documents": retrieved_documents,
        "selected_specialist": selected_specialist,
        "draft_answer": message,
        "long_context_payload": long_context,
        "specialist_output": {
            "message": message,
            "memory_patch": final_payload.get("memory_patch"),
            "provenance": final_payload.get("provenance", []),
            "stop_reason": final_payload.get("stop_reason", ""),
        },
        "tool_call_log": tool_call_log,
        "step_progress": step_progress,
        "next_node": "light_validator",
    }
