from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage

from app.agents.orchestrator import orchestrator
from app.agents.tool_calling import run_advisor_tool_loop
from app.mcp_server import call_tool as server_call_tool, list_tools as server_list_tools
from app.services.mcp_tools import execute_pathfinder_tool, list_tool_descriptors


@pytest.mark.asyncio
async def test_tool_descriptors_and_server_listing_are_aligned():
    descriptors = list_tool_descriptors()
    tools = await server_list_tools()

    assert descriptors
    assert len(descriptors) == len(tools)
    assert {item["name"] for item in descriptors} == {tool.name for tool in tools}
    assert all({"name", "description", "inputSchema", "guidance"} <= set(item.keys()) for item in descriptors)


@pytest.mark.asyncio
async def test_unknown_tool_returns_canonical_error_envelope():
    result = await execute_pathfinder_tool("missing_tool", {}, context={"state": {}})

    assert result["ok"] is False
    assert result["data"] == {}
    assert result["citations"] == []
    assert result["meta"]["tool"] == "missing_tool"
    assert result["errors"]


@pytest.mark.asyncio
async def test_get_session_context_returns_state_snapshot():
    state = {
        "query": "help me plan next semester",
        "session_id": "sess-1",
        "student_id": "stu-1",
        "advisor_mode": "semester_planning",
        "files": [{"filename": "transcript.pdf"}],
        "request_plan": {"workflow_hint": "academic_planning"},
        "runtime_policy": {"decisions": []},
        "messages": [("human", "I want backend roles"), ("ai", "Let's focus on backend internships.")],
        "session_memory": {"carry_forward_context": {"goals": ["backend internship"]}},
        "compacted_session": {"conversation_digest": {"recent_turns": [{"role": "user", "content": "I want backend roles"}]}},
    }

    result = await execute_pathfinder_tool(
        "get_session_context",
        {},
        context={"state": state, "runtime_snapshot": {"selected_text_model": "local-model"}},
    )

    assert result["ok"] is True
    assert result["errors"] == []
    assert result["data"]["uploaded_file_count"] == 1
    assert result["data"]["runtime_snapshot"]["selected_text_model"] == "local-model"
    assert result["data"]["recent_messages"][0]["role"] == "user"
    assert result["data"]["session_memory"]["carry_forward_context"]["goals"] == ["backend internship"]


@pytest.mark.asyncio
async def test_server_call_tool_returns_json_text_for_unknown_tool():
    payload = await server_call_tool("not_real", {})
    text = payload[0].text
    parsed = json.loads(text)

    assert parsed["ok"] is False
    assert parsed["meta"]["tool"] == "not_real"


@pytest.mark.asyncio
async def test_orchestrator_runs_mcp_flow_and_routes_to_evaluator(monkeypatch):
    captured_user_query = {}
    forced_calls = []

    async def fake_list_tools(self):
        return [{"name": "get_session_context", "description": "desc", "guidance": "guide", "inputSchema": {}}]

    async def fake_call_tool(self, name, arguments=None):
        forced_calls.append((name, arguments or {}))
        if name == "search_web":
            return {
                "ok": True,
                "data": {"query": arguments["query"], "results": [{"title": "Result", "url": "https://example.com"}]},
                "errors": [],
                "citations": [{"title": "Result", "url": "https://example.com", "snippet": "snapshot"}],
                "meta": {"query": arguments["query"], "result_count": 1},
            }
        return {"ok": True, "data": {}, "errors": [], "citations": [], "meta": {}}

    async def fake_run_loop(**kwargs):
        captured_user_query["payload"] = kwargs["user_query"]
        return (
            "Final answer from MCP runtime",
            [
                {
                    "tool": "get_session_context",
                    "status": "ok",
                    "citations": [{"title": "Runtime", "url": "", "snippet": "snapshot"}],
                }
            ],
        )

    monkeypatch.setattr("app.agents.orchestrator.get_text_llm", lambda: object())
    monkeypatch.setattr("app.agents.orchestrator.run_advisor_tool_loop", fake_run_loop)
    monkeypatch.setattr("app.agents.orchestrator.InternalMCPClient.list_tools", fake_list_tools)
    monkeypatch.setattr("app.agents.orchestrator.InternalMCPClient.call_tool", fake_call_tool)

    state = {
        "query": "what can you help me with?",
        "session_id": "sess-1",
        "student_id": "stu-1",
        "advisor_mode": "adaptive",
        "files": [],
        "request_plan": {},
        "runtime_policy": {},
        "messages": [("human", "I am targeting ML internships"), ("ai", "We can use that as context.")],
        "session_memory": {"carry_forward_context": {"goals": ["ML internship"]}},
        "compacted_session": {"conversation_digest": {"recent_turns": [{"role": "user", "content": "I am targeting ML internships"}]}},
        "step_progress": [],
        "tool_call_log": [],
        "citations": [],
    }

    result = await orchestrator(state)

    assert result["next_node"] == "evaluator"
    assert result["draft_answer"] == "Final answer from MCP runtime"
    assert result["plan"] == ["search_web", "get_session_context"]
    assert result["mcp_tool_calls"][0]["tool"] == "search_web"
    assert result["mcp_tool_calls"][1]["tool"] == "get_session_context"
    assert result["citations"][0]["title"] == "Result"
    assert "ML internship" in captured_user_query["payload"]
    assert "preloaded_web_context" in captured_user_query["payload"]
    assert forced_calls[0][0] == "search_web"


@pytest.mark.asyncio
async def test_tool_loop_includes_recent_conversation_context():
    captured_messages = []

    class FakeBoundLLM:
        async def ainvoke(self, messages):
            captured_messages.extend(messages)
            return AIMessage(content="Final answer with context", tool_calls=[])

    class FakeLLM:
        def bind_tools(self, schemas):
            return FakeBoundLLM()

    state = {
        "messages": [
            ("human", "I want backend internships."),
            ("ai", "Backend internships sound like a good focus."),
        ],
        "tool_call_log": [],
    }

    answer, tool_log = await run_advisor_tool_loop(
        llm=FakeLLM(),
        system_prompt="System prompt",
        user_query='{"user_query":"What should I do next?"}',
        state=state,
        max_rounds=1,
    )

    rendered = [getattr(msg, "content", "") for msg in captured_messages]
    assert any("I want backend internships." in str(item) for item in rendered)
    assert any("Backend internships sound like a good focus." in str(item) for item in rendered)
    assert answer == "Final answer with context"
    assert tool_log == []
