"""Helpers for ingesting one document into the student graph."""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.adapters.llm.lmstudio import get_text_llm
from app.adapters.neo4j.graphDB import GraphDB
from app.core.prompts import (
    DOCUMENT_INGESTION_AGENT_SYSTEM_PROMPT,
    DOCUMENT_INGESTION_AGENT_USER_PROMPT,
)
from app.tools.graph_tools import get_driver as get_graph_driver, get_graph_tool_specs
from app.tools.tools import ToolContext, ToolSpec, build_tool_transcript_payload
from app.tools.vector_tools import get_vector_tool_specs
from app.utils.json_extract import parse_json_object

log = logging.getLogger("pathfinder.utils.document_ingest")

_QUERY_LIMIT = 400
_DOCUMENT_LIMIT = 24000
_CHUNK_PROMPT_LIMIT = 24000
_INGESTION_TOOL_LIMIT = 30
_INGESTION_ROUNDS = 100

# Tools that the ingestion agent should NOT see —
# web search, conversation utilities, cleanup, index creation, respond,
# chunk write tools (chunks are already stored before ingestion), and
# visualization-only helpers.
_INGESTION_EXCLUDED_TOOLS: set[str] = {
    # Web — not relevant during document ingestion
    "search_web",
    "fetch_url",
    "find_official_sources",
    "respond",
    # Destructive / admin tools the ingestion agent should never call
    "delete_document_chunks",
    "delete_chunk",
    "create_vector_index",
    "vector_health_check",
    # Chunk write tools — chunks are pre-stored before ingestion runs
    "upsert_chunk",
    "upsert_chunk_metadata",
    "batch_upsert_chunks",
    # Broad retrieval the ingestion agent doesn't need
    "get_chunks_for_student",
}


def _get_ingestion_tool_specs() -> list[ToolSpec]:
    """Return only the tools relevant for document ingestion."""
    return [
        spec
        for spec in (
            *get_graph_tool_specs(),
            *get_vector_tool_specs(),
        )
        if spec.name not in _INGESTION_EXCLUDED_TOOLS
    ]


def _get_ingestion_tool_schemas() -> list[dict[str, Any]]:
    """Return OpenAI-compatible schemas for the ingestion tool subset."""
    return [spec.as_openai_schema() for spec in _get_ingestion_tool_specs()]


async def _ingestion_execute_tool(
    name: str, arguments: dict[str, Any], context: ToolContext
) -> dict[str, Any]:
    """Execute one tool from the ingestion subset."""
    for spec in _get_ingestion_tool_specs():
        if spec.name == name:
            return await spec.handler(arguments, context)
    return {"error": f"unknown tool: {name}"}


def _normalize_model_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize the model's final JSON report into a fixed shape."""
    key_takeaways = payload.get("key_takeaways") if isinstance(payload, dict) else []
    saved_items = payload.get("saved_items") if isinstance(payload, dict) else []
    return {
        "summary": str(payload.get("summary", "") or "") if isinstance(payload, dict) else "",
        "key_takeaways": [
            str(item).strip()
            for item in (key_takeaways if isinstance(key_takeaways, list) else [])
            if str(item).strip()
        ][:12],
        "saved_items": [
            str(item).strip()
            for item in (saved_items if isinstance(saved_items, list) else [])
            if str(item).strip()
        ][:20],
        "stop_reason": str(payload.get("stop_reason", "") or "") if isinstance(payload, dict) else "",
    }


def _build_graph_updates(tool_call_log: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize what this ingestion run changed from successful tool writes."""
    sections_touched: list[str] = []
    entity_types_touched: list[str] = []
    relationship_types_touched: list[str] = []
    sample_entities_written: list[dict[str, Any]] = []
    seen_sections: set[str] = set()
    seen_entity_types: set[str] = set()
    seen_relationship_types: set[str] = set()
    seen_entity_samples: set[str] = set()
    counts = {
        "sections_upserted": 0,
        "entities_written": 0,
        "relationships_written": 0,
        "chunk_links_written": 0,
        "document_links_written": 0,
        "field_writes": 0,
    }

    for item in tool_call_log:
        if not isinstance(item, dict) or item.get("status") != "ok":
            continue
        tool_name = str(item.get("tool", "") or "")
        args = dict(item.get("input") or {})

        if tool_name == "upsert_section":
            counts["sections_upserted"] += 1
            key = str(args.get("key", "") or "").strip()
            if key and key not in seen_sections:
                seen_sections.add(key)
                sections_touched.append(key)
            continue

        if tool_name == "upsert_graph_node":
            counts["entities_written"] += 1
            entity_type = str(args.get("entity_type", "") or "").strip()
            if entity_type and entity_type not in seen_entity_types:
                seen_entity_types.add(entity_type)
                entity_types_touched.append(entity_type)
            identity = dict(args.get("identity") or {})
            if entity_type and identity:
                identity_signature = json.dumps(
                    {"entity_type": entity_type, "identity": identity},
                    sort_keys=True,
                    ensure_ascii=True,
                    default=str,
                )
                if identity_signature not in seen_entity_samples and len(sample_entities_written) < 5:
                    seen_entity_samples.add(identity_signature)
                    sample_entities_written.append(
                        {"entity_type": entity_type, "identity": identity}
                    )
            continue

        if tool_name == "upsert_graph_relation":
            counts["relationships_written"] += 1
            relationship_type = str(args.get("relationship_type", "") or "").strip()
            if relationship_type and relationship_type not in seen_relationship_types:
                seen_relationship_types.add(relationship_type)
                relationship_types_touched.append(relationship_type)
            continue

        if tool_name == "link_entity_to_chunk":
            counts["chunk_links_written"] += 1
            continue

        if tool_name == "link_entity_to_document":
            counts["document_links_written"] += 1
            continue

        if tool_name in {"upsert_entity_field", "upsert_nested_field"}:
            counts["field_writes"] += 1

    return {
        "sections_touched": sections_touched,
        "entity_types_touched": entity_types_touched,
        "relationship_types_touched": relationship_types_touched,
        "counts": counts,
        "sample_entities_written": sample_entities_written,
    }


async def ingest_document(
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
    """Use the tool registry to ingest one document into the student graph."""
    graph_db = GraphDB(await get_graph_driver())
    llm = get_text_llm().bind_tools(_get_ingestion_tool_schemas())
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
    current_schema = await graph_db.get_student_schema(student_id=student_id)
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
                try:
                    result = await _ingestion_execute_tool(tool_name, args, tool_context)
                except Exception as e:
                    result = {"error": str(e)}
                compact = build_tool_transcript_payload(tool_name, args, result, tool_context)
                tool_call_log.append(
                    {
                        "call_id": str(call.get("id", "") or ""),
                        "tool": tool_name,
                        "input": args,
                        "status": str(compact.get("status") or ("error" if result.get("error") else "ok")),
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
                "key_takeaways": [],
                "saved_items": [],
                "stop_reason": "",
            }
        break

    model_summary = _normalize_model_summary(final_payload)
    graph_updates = _build_graph_updates(tool_call_log)
    graph_schema_after = await graph_db.get_student_schema(student_id=student_id)
    return {
        "tool_call_log": tool_call_log,
        "model_summary": model_summary,
        "graph_updates": graph_updates,
        "graph_schema_after": graph_schema_after,
    }
