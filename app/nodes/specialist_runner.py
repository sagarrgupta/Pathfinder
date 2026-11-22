"""Runs the chosen specialist until it produces a final answer.

This is where the actual "answering" happens. The orchestrator has already
picked which persona to use (`academic`, `career`, or `general`); this
node loads that persona's system prompt, wires up the tool surface it is
allowed to see, and runs a tool-calling loop until the LLM emits a final
`respond` payload (or we hit the safety caps).

Key ideas:
- The LLM can see graph read tools, vector retrieval tools, and web
  tools — but NOT graph write tools, because ingestion has already run.
- Uploaded files are processed via `doc_analyst` at the top of this node,
  so their content is already in Neo4j by the time the LLM starts calling
  tools.
- If the model prematurely says "I could not find it" before exhausting
  web search options, we inject one retry nudge to push it harder. Only
  one retry per turn to avoid loops.
- Every tool call is recorded in `tool_call_log` so the response validator
  can build citations and replays can reconstruct exactly what happened.
"""

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
from app.tools.tools import (
    ToolContext,
    build_tool_transcript_payload,
    execute_agent_tool,
    get_agent_tool_schemas,
)
from app.utils.json_extract import parse_json_object
from app.utils.progress import add_progress
from app.utils.runtime_utils import build_recent_conversation_window

log = logging.getLogger("pathfinder.agents.specialist_runner")

# Tool-visibility profile — see `app.tools.tools._SPECIALIST_EXCLUDED_TOOLS`.
# The specialist is read-only against the graph; ingestion already ran.
_AGENT_PROFILE = "specialist"

# System prompt for each persona. Chosen at runtime based on what the
# orchestrator set as `selected_specialist`.
_SPECIALIST_CONFIG = {
    "academic": ACADEMIC_SPECIALIST_SYSTEM_PROMPT,
    "career": CAREER_SPECIALIST_SYSTEM_PROMPT,
    "general": GENERAL_SPECIALIST_SYSTEM_PROMPT,
}

# When the model returns free-form text instead of a proper `respond` tool
# call, we try to salvage a `message` field from any JSON it printed.
_MESSAGE_FIELD_RE = re.compile(r'"message"\s*:\s*"((?:\\.|[^"])*)"', re.DOTALL)
# Strip chat-template control tokens (e.g., `<|im_end|>`) that some local
# models emit into their plain-text output.
_SPECIAL_TOKEN_RE = re.compile(r"<\|.*?\|>")
_CONTEXT_FIELD_RE = re.compile(
    r'[ \t]*[`"*]*(next_session_context|next_long_context)[`"*]*[ \t]*:[ \t]*'
)


# Phrases that signal the model is giving up. If we see one of these in the
# final answer AND the model has not yet tried enough web searches/fetches,
# we nudge it to try again (once).
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

# Safety caps mirroring the document-ingestion style: bounded rounds and a
# bounded number of tool calls per round. No global tool-count cap — we
# trust per-round limits plus the round cap to bound work.
_LLM_ROUNDS = 30
_MAX_TOOL_CALLS_PER_ROUND = 20
_MAX_WEB_SEARCH_RETRIES = 3
_MAX_WEB_SEARCH_FETCHES = 20


def _should_retry_web_search(payload: dict[str, Any], tool_log: list[dict[str, Any]]) -> bool:
    """Did the model bail on a web-searchable question before trying hard enough?

    Returns True only if (a) the answer sounds like a giving-up phrase and
    (b) the model has not yet used its full web-search/fetch budget. That
    combination is the signal we want to push back on; anything else is
    treated as a legitimate "I really can't find this" response.
    """
    message = str(payload.get("message", "") or "").lower()
    if not any(phrase in message for phrase in _NOT_FOUND_PHRASES):
        return False
    search_count = sum(1 for t in tool_log if isinstance(t, dict) and t.get("tool") == "search_web")
    fetch_count = sum(1 for t in tool_log if isinstance(t, dict) and t.get("tool") == "fetch_url")
    return search_count < _MAX_WEB_SEARCH_RETRIES or fetch_count < _MAX_WEB_SEARCH_FETCHES


def _split_trailing_context(content: str) -> tuple[str, dict[str, Any]]:
    """Recover a complete memory-field suffix appended to an ordinary answer.

    Only consume a suffix containing both fields with valid string/null
    values, so mentions of these names in normal prose remain untouched.
    """
    start = re.search(r'\n(?=[ \t]*[`"*]*next_(?:session|long)_context[`"*]*[ \t]*:)', content)
    if start is None:
        return content, {}
    remaining = content[start.end():].strip()
    fields: dict[str, Any] = {}
    decoder = json.JSONDecoder(strict=False)
    while remaining:
        match = _CONTEXT_FIELD_RE.match(remaining)
        if match is None or match.group(1) in fields:
            return content, {}
        key = match.group(1)
        try:
            value, end = decoder.raw_decode(remaining[match.end():])
        except ValueError:
            return content, {}
        if not isinstance(value, str) and not (key == "next_long_context" and value is None):
            return content, {}
        fields[key] = value
        remaining = remaining[match.end() + end:].strip()
        if remaining.startswith(","):
            remaining = remaining[1:].lstrip()
    if set(fields) != {"next_session_context", "next_long_context"}:
        return content, {}
    return content[:start.start()].rstrip(), fields


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
    """Strip chat-template artifacts and unwrap JSON-wrapped text."""
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

def _normalize_specialist_payload(payload: dict[str, Any], session_context: str) -> dict[str, Any]:
    """Coerce whatever the model returned into the 4-field runtime contract.

    Downstream nodes (`response_validator`, `context_persister`, `responder`)
    assume `message`, `stop_reason`, `next_session_context`, and
    `next_long_context` exist. If the model forgot `next_session_context`,
    we carry the previous turn's value forward rather than wiping memory.
    """
    next_session_context = str(payload.get("next_session_context", "") or "").strip()
    if not next_session_context:
        log.warning(
            "LLM omitted next_session_context — carrying forward previous session context unchanged. "
            "Check that the respond tool / JSON output includes this required field."
        )
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
    """Drive the specialist LLM until it produces a final `respond` payload.

    Flow:
      1. If files are attached, run document ingestion first so the LLM can
         actually see them via graph/vector tools.
      2. Load the student's profile, schema, and carried-over context into
         the system/human prompt so the model starts oriented.
      3. Loop: ask the LLM -> execute any tool calls -> feed results back
         -> repeat until `respond` is called or caps are hit.
      4. If the final answer looks like a premature "I can't find it",
         push back once with a retry nudge.
    """
    selected_specialist = str(state.get("selected_specialist", "general") or "general")
    student_id = str(state.get("student_id", "") or "")
    session_id = str(state.get("session_id", "") or "")
    query = str(state.get("query", "") or "")

    step_progress = list(state.get("step_progress", []))
    add_progress(
        step_progress,
        stage="Working on your answer",
        message="Reviewing your profile and gathering the right context.",
    )
    working_state = dict(state)
    files = list(state.get("files", []))
    # User-selected reasoning effort passes through to the LLM adapter.
    reasoning = str(state.get("reasoning", "medium") or "medium").strip().lower() or "medium"

    # If the user attached files, ingest them first so their content is
    # queryable via graph/vector tools during this same turn.
    if files:
        add_progress(
            step_progress,
            stage="Reading your uploaded files",
            message="Pulling useful details from the files you attached.",
        )
        doc_state = await doc_analyst({**state, "step_progress": step_progress})
        working_state.update(doc_state)
        step_progress = list(doc_state.get("step_progress", step_progress))

    # Collect everything the specialist needs to be "aware" of the student.
    graph_db = GraphDB(await get_graph_driver())
    student = await graph_db.get_student(student_id=student_id) or {}
    student_schema = await graph_db.get_student_schema(student_id=student_id)
    raw_session_messages = working_state.get("messages", [])
    session_messages = list(raw_session_messages) if isinstance(raw_session_messages, list) else []
    session_context = str(working_state.get("session_context", "") or "").strip()
    long_context = str(student.get("long_context", "") or "").strip()

    # Compact JSON-friendly bundle embedded into the first HumanMessage so
    # the model has the full picture without needing a dozen read calls.
    prompt_context = {
        "student_schema": student_schema,
        "recent_messages": build_recent_conversation_window(session_messages, limit=10),
        "session_context": session_context,
        "long_context": long_context,
    }
    # Bind the tool schemas the specialist profile is allowed to use.
    llm = get_text_llm(reasoning).bind_tools(get_agent_tool_schemas(_AGENT_PROFILE))
    # Shared context passed into every tool handler (identifies who we are
    # acting on behalf of, and gives handlers access to the current state).
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
    # Initial conversation: persona prompt + user's query + the pre-loaded
    # context + a short reminder of the tool contract.
    messages: list[Any] = [
        SystemMessage(content=str(_SPECIALIST_CONFIG.get(selected_specialist, _SPECIALIST_CONFIG["general"]))),
        HumanMessage(
            content=(
                f"User query:\n{query}\n\n"
                f"Specialist context:\n{json.dumps(prompt_context, ensure_ascii=True)}\n\n"
                "Reminder: use tools for graph/document/web access; return final JSON only after tool use is done."
            )
        ),
    ]
    # Running transcript of every tool call we made this turn, used for
    # citations and replay artifacts.
    raw_tool_call_log = working_state.get("tool_call_log", [])
    tool_call_log = list(raw_tool_call_log) if isinstance(raw_tool_call_log, list) else []
    final_payload: dict[str, Any] = {}
    # One retry is allowed per turn — flag flips after we use it.
    web_retry_used = False

    # Bounded tool-calling loop. Each iteration is one LLM turn.
    for _ in range(_LLM_ROUNDS):
        ai_msg = await llm.ainvoke(messages)
        messages.append(ai_msg)
        if not isinstance(ai_msg, AIMessage):
            break
        if ai_msg.tool_calls:
            # The model wants tools — execute them and feed results back.
            responded = False
            # Cap calls per round to keep one turn from monopolizing work.
            for call in ai_msg.tool_calls[:_MAX_TOOL_CALLS_PER_ROUND]:
                tool_name = str(call.get("name", "") or "")
                args = call.get("args", {}) if isinstance(call.get("args", {}), dict) else {}
                # execute_agent_tool enforces the read-only specialist profile.
                result = await execute_agent_tool(_AGENT_PROFILE, tool_name, args, tool_context)
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
                # Feed the compact summary back as a ToolMessage so the
                # model can reason over the results without flooding context.
                messages.append(
                    ToolMessage(
                        content=json.dumps(compact, ensure_ascii=True, default=str),
                        tool_call_id=str(call.get("id", "") or ""),
                    )
                )
                # `respond` is the terminal tool — capture its payload and
                # exit the round once it's used successfully.
                if tool_name == "respond" and not result.get("error"):
                    final_payload = result
                    responded = True
            if responded:
                normalized = _normalize_specialist_payload(final_payload, session_context)
                # Gate: if the answer sounds like giving up but the model
                # hasn't exhausted web tools, force one more round with a
                # different strategy.
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
            answer_text, recovered_context = _split_trailing_context(content)
            final_payload = _normalize_specialist_payload(
                {
                    "message": _extract_message_from_text(answer_text),
                    "stop_reason": "",
                    "next_session_context": session_context,
                    "next_long_context": None,
                    **recovered_context,
                },
                session_context,
            )
        break

    message = _clean_message(str(final_payload.get("message", "") or ""))
    if not message:
        message = "I could not generate a useful response for this request."
    return {
        **working_state,
        "student_schema": student_schema,
        "input_session_context": session_context,
        "input_long_context": long_context,
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
