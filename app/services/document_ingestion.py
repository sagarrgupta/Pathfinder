"""Structured document-ingestion patch extraction and application."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.adapters.embeddings.ollama import aembed_query
from app.adapters.llm.lmstudio import get_text_llm
from app.adapters.neo4j.graph_store import (
    get_profile_schema,
    store_evidence,
)
from app.core.prompts import (
    DOCUMENT_INGESTION_AGENT_SYSTEM_PROMPT,
    DOCUMENT_INGESTION_AGENT_USER_PROMPT,
)
from app.tools.registry import ToolContext, compact_result, execute_tool, get_tool_schemas
from app.utils.json_extract import parse_json_object

log = logging.getLogger("pathfinder.services.document_ingestion")

_QUERY_LIMIT = 400
_DOCUMENT_LIMIT = 12000
_CHUNK_PROMPT_LIMIT = 24000
_SCALAR_TYPES = (str, int, float, bool)
_INGESTION_TOOL_LIMIT = 30
_INGESTION_ROUNDS = 20


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _scalar_or_string(value: Any) -> Any:
    if value is None or isinstance(value, _SCALAR_TYPES):
        return value
    if isinstance(value, list):
        if all(item is None or isinstance(item, _SCALAR_TYPES) for item in value):
            return value
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=True)
    return str(value)


def _normalize_context_updates(value: Any) -> dict[str, list[str]]:
    source = value if isinstance(value, dict) else {}
    long_term = [
        str(item).strip()
        for item in list(source.get("long_term_summary_points", []) or [])
        if str(item).strip()
    ]
    session_notes = [
        str(item).strip()
        for item in list(source.get("session_notes", []) or [])
        if str(item).strip()
    ]
    return {
        "long_term_summary_points": long_term[:12],
        "session_notes": session_notes[:12],
    }
async def execute_document_ingestion_agent(
    *,
    student_id: str,
    session_id: str | None,
    document_id: str,
    query: str,
    filename: str,
    file_type: str,
    full_text: str,
    chunks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Use the MCP-style tool registry to ingest one document into profile state."""
    evidence = await store_evidence(
        student_id=student_id,
        source_type="document_ingestion",
        content=full_text[:_DOCUMENT_LIMIT],
        session_id=session_id,
        metadata={
            "document_id": document_id,
            "filename": filename,
            "patch_kind": "document_ingestion",
        },
        embedding=await aembed_query(full_text[:4000]),
    )
    llm = get_text_llm().bind_tools(get_tool_schemas())
    tool_context = ToolContext(
        student_id=student_id,
        session_id=session_id or "",
        state={
            "document_ingestion_context": {
                "document_id": document_id,
                "filename": filename,
            }
        },
    )
    current_schema = await get_profile_schema(student_id)
    schema_text = json.dumps(current_schema, indent=2, ensure_ascii=True, default=str)
    chunk_text = json.dumps(chunks or [], ensure_ascii=True, default=str)[:_CHUNK_PROMPT_LIMIT]
    prompt = DOCUMENT_INGESTION_AGENT_USER_PROMPT.format(
        current_schema=schema_text,
        query=(query or "").strip()[:_QUERY_LIMIT],
        document_id=document_id,
        filename=filename,
        file_type=file_type,
        document_chunks=chunk_text,
        document_text=full_text[:_DOCUMENT_LIMIT],
    )
    messages: list[Any] = [
        SystemMessage(content=DOCUMENT_INGESTION_AGENT_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]
    tool_call_log: list[dict[str, Any]] = []
    final_payload: dict[str, Any] = {}

    for _ in range(_INGESTION_ROUNDS):
        ai_msg = await llm.ainvoke(messages)
        messages.append(ai_msg)
        if not isinstance(ai_msg, AIMessage):
            break
        if ai_msg.tool_calls:
            for call in ai_msg.tool_calls[:_INGESTION_TOOL_LIMIT]:
                tool_name = str(call.get("name", "") or "")
                args = call.get("args", {}) if isinstance(call.get("args", {}), dict) else {}
                result = await execute_tool(tool_name, args, tool_context)
                compact = compact_result(result)
                tool_call_log.append(
                    {
                        "call_id": str(call.get("id", "") or ""),
                        "tool": tool_name,
                        "input": args,
                        "status": "ok" if not result.get("error") else "error",
                        "output": result,
                        "result_summary": compact,
                    }
                )
                messages.append(
                    ToolMessage(
                        content=json.dumps(compact, ensure_ascii=True, default=str),
                        tool_call_id=str(call.get("id", "") or ""),
                    )
                )
            continue
        content = ai_msg.content if isinstance(ai_msg.content, str) else str(ai_msg.content)
        parsed = parse_json_object(content)
        if isinstance(parsed, dict):
            final_payload = parsed
        else:
            final_payload = {
                "summary": "",
                "context_updates": {"long_term_summary_points": [], "session_notes": []},
                "saved_items": [],
                "stop_reason": "",
            }
        break

    profile = await execute_tool("get_profile_summary", {}, tool_context)
    entity_types = await execute_tool("list_entity_types", {}, tool_context)
    return {
        "evidence": evidence,
        "tool_call_log": tool_call_log,
        "final_payload": final_payload,
        "context_updates": _normalize_context_updates(final_payload.get("context_updates")),
        "saved_items": list(final_payload.get("saved_items", []) or []) if isinstance(final_payload, dict) else [],
        "summary": str(final_payload.get("summary", "") or ""),
        "stop_reason": str(final_payload.get("stop_reason", "") or ""),
        "profile_summary": profile,
        "entity_types": entity_types,
    }
