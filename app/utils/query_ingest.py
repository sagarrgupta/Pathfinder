"""Ingest facts the user casually drops into a chat message.

Complements `app.utils.document_ingest`: whenever the user says
something like "btw I got promoted to senior engineer last month",
we want that on the profile even though no document was uploaded.

This module runs in parallel with the specialist on every chat turn
(from the `query_ingestor` node, before the specialist runs) and
writes whatever new structured facts it can extract.

Key differences from document ingestion:
- The agent sees the `query_ingestor` tool profile — graph writes
  only, no chunk/document grounding edges (there's no doc to link to)
  and no vector/embedding tools.
- The prompt is the chat message itself, not extracted file text.
- There is no per-chunk iteration — a single user turn is small.

Loop budget mirrors `document_ingest` for consistency, but in practice
most messages finish in one or two rounds.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.adapters.llm.lmstudio import get_text_llm
from app.adapters.neo4j.graphDB import GraphDB
from app.core.prompts import (
    QUERY_INGESTION_AGENT_SYSTEM_PROMPT,
    QUERY_INGESTION_AGENT_USER_PROMPT,
)
from app.tools.graph_tools import get_driver as get_graph_driver
from app.tools.tools import (
    ToolContext,
    build_tool_transcript_payload,
    execute_agent_tool,
    get_agent_tool_schemas,
)
from app.utils.ingest_common import build_graph_updates
from app.utils.json_extract import parse_json_object
from app.utils.progress import add_progress

log = logging.getLogger("pathfinder.utils.query_ingest")

# Tool profile — hides writes to chunks / documents the query ingester
# has no business touching on a chat-only turn.
_AGENT_PROFILE = "query_ingestor"
# Cap on chat message size we feed the agent. Generous — a normal
# message is well under this; the limit is just a safety belt.
_QUERY_PROMPT_LIMIT = 8000
# Loop caps mirror `document_ingest` so both pipelines feel the same.
_INGESTION_TOOL_LIMIT = 30
_INGESTION_ROUNDS = 100


def _normalize_query_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Tidy the agent's final JSON into the minimal `{summary, saved_items, stop_reason}` shape.

    Chat ingestion doesn't produce `key_takeaways` (there isn't a
    document to summarize) so the shape is smaller than
    `document_ingest._normalize_model_summary`.
    """
    saved_items = payload.get("saved_items") if isinstance(payload, dict) else []
    return {
        "summary": str(payload.get("summary", "") or "") if isinstance(payload, dict) else "",
        "saved_items": [
            str(item).strip()
            for item in (saved_items if isinstance(saved_items, list) else [])
            if str(item).strip()
        ][:20],
        "stop_reason": str(payload.get("stop_reason", "") or "") if isinstance(payload, dict) else "",
    }


async def ingest_query(
    *,
    student_id: str,
    session_id: str | None,
    query: str,
    step_progress: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Run the chat-ingestion agent over one user message.

    The `query_ingestor` node calls this on every turn (before the
    specialist). Returns the same shape as `ingest_document` so both
    pipelines share the `build_graph_updates` summary in the replay
    artifact. Any exception here is caught by the caller so a bad
    ingestion never prevents the user's question from being answered.
    """
    progress_sink: list[dict[str, str]] = step_progress if step_progress is not None else []
    graph_db = GraphDB(await get_graph_driver())
    llm = get_text_llm().bind_tools(get_agent_tool_schemas(_AGENT_PROFILE))
    tool_context = ToolContext(
        student_id=student_id,
        session_id=session_id or "",
        state={},
    )
    current_schema = await graph_db.get_student_schema(student_id=student_id)
    schema_text = json.dumps(current_schema, indent=2, ensure_ascii=True, default=str)
    prompt = QUERY_INGESTION_AGENT_USER_PROMPT.format(
        current_schema=schema_text,
        query=str(query or "").strip()[:_QUERY_PROMPT_LIMIT],
    )
    messages: list[Any] = [
        SystemMessage(content=QUERY_INGESTION_AGENT_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]
    tool_call_log: list[dict[str, Any]] = []
    final_payload: dict[str, Any] = {}

    for round_idx in range(_INGESTION_ROUNDS):
        if round_idx == 0:
            add_progress(
                progress_sink,
                stage="Reading your message",
                message="Thinking through what you said.",
            )
        else:
            add_progress(
                progress_sink,
                stage="Reading your message",
                message=f"Continuing review (step {round_idx + 1}).",
            )
        ai_msg = await llm.ainvoke(messages)
        messages.append(ai_msg)
        if not isinstance(ai_msg, AIMessage):
            break
        if ai_msg.tool_calls:
            tool_count = min(len(ai_msg.tool_calls), _INGESTION_TOOL_LIMIT)
            add_progress(
                progress_sink,
                stage="Reading your message",
                message=(
                    f"Checking the graph for {tool_count} detail"
                    f"{'s' if tool_count != 1 else ''}."
                ),
            )
            for call in ai_msg.tool_calls[:_INGESTION_TOOL_LIMIT]:
                tool_name = str(call.get("name", "") or "")
                args = call.get("args", {}) if isinstance(call.get("args", {}), dict) else {}
                try:
                    result = await execute_agent_tool(_AGENT_PROFILE, tool_name, args, tool_context)
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
                "saved_items": [],
                "stop_reason": "",
            }
        break

    saved_count = (
        len(final_payload.get("saved_items") or [])
        if isinstance(final_payload, dict)
        else 0
    )
    if saved_count > 0:
        add_progress(
            progress_sink,
            stage="Reading your message",
            message=(
                f"Saved {saved_count} new detail"
                f"{'s' if saved_count != 1 else ''} to your profile."
            ),
        )
    else:
        add_progress(
            progress_sink,
            stage="Reading your message",
            message="No new details to remember from this message.",
        )

    model_summary = _normalize_query_summary(final_payload)
    graph_updates = build_graph_updates(tool_call_log)
    graph_schema_after = await graph_db.get_student_schema(student_id=student_id)
    return {
        "tool_call_log": tool_call_log,
        "model_summary": model_summary,
        "graph_updates": graph_updates,
        "graph_schema_after": graph_schema_after,
    }
