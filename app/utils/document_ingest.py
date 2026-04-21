"""Drive the document-ingestion agent that turns a file into graph nodes.

This is the workhorse behind the `doc_analyst` node. Given a file's
already-extracted text + chunks, we:

1. Load the current student schema so the agent reuses existing
   section/entity names instead of inventing duplicates.
2. Hand the agent a text LLM bound to the `document_ingestor` tool
   profile (graph writes + link tools, no web, no chunk deletion).
3. Run a capped tool-calling loop — up to `_INGESTION_ROUNDS` rounds,
   with each round executing at most `_INGESTION_TOOL_LIMIT` tool
   calls — until the model emits its final JSON report.
4. Summarize what it actually did via `build_graph_updates` so the
   replay + UI can show "saved N items" without walking the raw log.

The tool-calling loop is intentionally aggressive (100 rounds × 30
tools) because a long document can justify hundreds of writes. The
specialist runner's loop is much tighter — it's answering one
question, not learning a whole resume.
"""

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

log = logging.getLogger("pathfinder.utils.document_ingest")

# Tool profile decides which tools the LLM can see — `document_ingestor`
# hides read-only vector tools and the specialist's `respond` tool.
_AGENT_PROFILE = "document_ingestor"
# Truncation budgets for the ingestion prompt. The text/chunk limits are
# intentionally generous since ingestion prompts run at lower frequency
# than chat turns and benefit from seeing the whole document.
_QUERY_LIMIT = 400
_DOCUMENT_LIMIT = 24000
_CHUNK_PROMPT_LIMIT = 24000
# Ingestion loop caps — see the module docstring for rationale.
_INGESTION_TOOL_LIMIT = 30
_INGESTION_ROUNDS = 100


def _normalize_model_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Coerce the agent's final JSON into the fixed shape replays expect.

    The agent is *asked* to return `summary` + `key_takeaways` +
    `saved_items` + `stop_reason`, but it occasionally misses a field
    or returns the wrong type. This normalizer fills gaps with empty
    defaults, trims whitespace, and caps list lengths so one chatty
    model response can't blow out the replay UI.
    """
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
    step_progress: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Run the ingestion agent over one file, returning its tool log + summary.

    Called by `doc_analyst` for every uploaded file on a chat turn.
    The return dict carries everything the replay artifact needs:

    - `tool_call_log` — raw per-call records (input/output/status),
    - `model_summary` — the LLM's own natural-language recap,
    - `graph_updates` — `build_graph_updates` distillation,
    - `graph_schema_after` — schema manifest once writes settled, so
      later nodes can see the updated shape without another round trip.

    Progress messages are appended to `step_progress` (a mutable list
    owned by the caller) both for the replay artifact and for live
    SSE streaming via `app.utils.progress`.
    """
    progress_sink: list[dict[str, str]] = step_progress if step_progress is not None else []
    graph_db = GraphDB(await get_graph_driver())

    llm = get_text_llm().bind_tools(get_agent_tool_schemas(_AGENT_PROFILE))

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

    for round_idx in range(_INGESTION_ROUNDS):
        if round_idx == 0:
            add_progress(
                progress_sink,
                stage="Reading your uploaded files",
                message=f"Reading {filename}.",
            )
        else:
            add_progress(
                progress_sink,
                stage="Reading your uploaded files",
                message=f"Continuing extraction from {filename} (step {round_idx + 1}).",
            )
        ai_msg = await llm.ainvoke(messages)
        messages.append(ai_msg)
        if not isinstance(ai_msg, AIMessage):
            break
        if ai_msg.tool_calls:
            tool_count = min(len(ai_msg.tool_calls), _INGESTION_TOOL_LIMIT)
            add_progress(
                progress_sink,
                stage="Reading your uploaded files",
                message=(
                    f"Saving {tool_count} item"
                    f"{'s' if tool_count != 1 else ''} from {filename}."
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
                "key_takeaways": [],
                "saved_items": [],
                "stop_reason": "",
            }
        break

    model_summary = _normalize_model_summary(final_payload)
    graph_updates = build_graph_updates(tool_call_log)
    graph_schema_after = await graph_db.get_student_schema(student_id=student_id)

    saved_count = len(model_summary.get("saved_items") or [])
    if saved_count > 0:
        add_progress(
            progress_sink,
            stage="Reading your uploaded files",
            message=(
                f"Saved {saved_count} item"
                f"{'s' if saved_count != 1 else ''} from {filename}."
            ),
        )
    else:
        add_progress(
            progress_sink,
            stage="Reading your uploaded files",
            message=f"Finished reading {filename}.",
        )

    return {
        "tool_call_log": tool_call_log,
        "model_summary": model_summary,
        "graph_updates": graph_updates,
        "graph_schema_after": graph_schema_after,
    }
