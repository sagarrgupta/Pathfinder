from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import pytest

from app.agents.input_guard import MAX_QUERY_LENGTH, input_guard
from app.agents.answer_composer_agent import answer_composer_agent
from app.agents.query_interpreter_agent import query_interpreter_agent
from app.agents.question_triage import question_triage
from app.agents.reasoning_planner import reasoning_planner
from app.agents.missing_info_agent import missing_info_agent


@dataclass
class Scenario:
    name: str
    query: str
    files: bool = False
    expected_blocked: bool = False
    expected_domain: str | None = None
    expected_task_type: str | None = None
    expected_depth: str | None = None
    expected_caps: list[str] = field(default_factory=list)
    forbidden_caps: list[str] = field(default_factory=list)
    llm_triage: dict[str, Any] | None = None
    notes: str = ""


class _FakeResponse:
    def __init__(self, content: str):
        self.content = content


class _FakeLLM:
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload

    async def ainvoke(self, _messages):
        return _FakeResponse(json.dumps(self.payload))


class _FakePlannerLLM:
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload

    async def ainvoke(self, _messages):
        return _FakeResponse(json.dumps(self.payload))


def _base_state(scenario: Scenario) -> dict[str, Any]:
    return {
        "query": scenario.query,
        "files": [{"filename": "resume.pdf", "content": b"resume", "size": 6, "content_type": "application/pdf"}]
        if scenario.files
        else [],
        "student_id": "student-test",
        "session_id": "session-test",
        "topic_guard_enabled": True,
        "interpreted_query": "",
        "interpreted_goal": "",
        "interpreted_constraints": [],
        "interpreted_search_brief": "",
        "interpretation_notes": "",
        "step_progress": [],
        "planner_trace": [],
        "active_capabilities": [],
        "retrieval_sources": [],
        "missing_info": [],
        "conflicts": [],
    }


SCENARIOS = [
    Scenario(
        name="short_profile_intro",
        query="I am sagar",
        expected_domain="profile",
        expected_task_type="update",
        expected_depth="light",
        expected_caps=["profile_memory_agent", "answer_composer_agent", "memory_writer_agent"],
        notes="Very short self-identification should become profile-building context.",
    ),
    Scenario(
        name="detailed_profile_intro",
        query="I am Sagar, a Computer Science student at California State University - Sacramento",
        expected_domain="profile",
        expected_task_type="update",
        expected_depth="light",
        expected_caps=["profile_memory_agent", "answer_composer_agent", "memory_writer_agent"],
    ),
    Scenario(
        name="name_statement",
        query="My name is Sagar Gupta",
        expected_domain="profile",
        expected_task_type="update",
        expected_depth="light",
        expected_caps=["profile_memory_agent", "answer_composer_agent", "memory_writer_agent"],
    ),
    Scenario(
        name="memory_recall_name",
        query="What's my name?",
        expected_domain="profile",
        expected_task_type="clarify",
        expected_depth="light",
        expected_caps=["profile_memory_agent", "semantic_memory_agent"],
        llm_triage={
            "domain": "profile",
            "task_type": "clarify",
            "reasoning_depth": "light",
            "needs_web": False,
            "needs_documents": False,
            "needs_profile": True,
            "reasoning": "Profile recall question",
        },
    ),
    Scenario(
        name="memory_recall_university",
        query="Which university do I study at?",
        expected_domain="profile",
        expected_task_type="clarify",
        expected_depth="light",
        expected_caps=["profile_memory_agent", "semantic_memory_agent"],
        llm_triage={
            "domain": "profile",
            "task_type": "clarify",
            "reasoning_depth": "light",
            "needs_web": False,
            "needs_documents": False,
            "needs_profile": True,
            "reasoning": "Profile recall question",
        },
    ),
    Scenario(
        name="career_generic",
        query="what jobs can i get",
        expected_domain="career",
        expected_task_type="recommend",
        expected_depth="light",
        expected_caps=["profile_memory_agent", "semantic_memory_agent", "web_researcher", "career_strategy_agent"],
        llm_triage={
            "domain": "career",
            "task_type": "recommend",
            "reasoning_depth": "light",
            "needs_web": True,
            "needs_documents": False,
            "needs_profile": True,
            "reasoning": "Career guidance request",
        },
    ),
    Scenario(
        name="career_based_on_profile",
        query="Based on my profile, suggest two career directions for me in short.",
        expected_domain="career",
        expected_task_type="recommend",
        expected_depth="light",
        expected_caps=["profile_memory_agent", "semantic_memory_agent", "career_strategy_agent"],
        llm_triage={
            "domain": "career",
            "task_type": "recommend",
            "reasoning_depth": "light",
            "needs_web": False,
            "needs_documents": False,
            "needs_profile": True,
            "reasoning": "Profile-grounded career guidance",
        },
    ),
    Scenario(
        name="interview_prep",
        query="Prepare me for a backend interview",
        expected_domain="interview",
        expected_task_type="plan",
        expected_depth="standard",
        expected_caps=["profile_memory_agent", "semantic_memory_agent", "interview_coach_agent", "answer_composer_agent"],
        llm_triage={
            "domain": "interview",
            "task_type": "plan",
            "reasoning_depth": "standard",
            "needs_web": False,
            "needs_documents": False,
            "needs_profile": True,
            "reasoning": "Interview preparation request",
        },
    ),
    Scenario(
        name="academic_planning",
        query="What courses should I take next semester?",
        expected_domain="academic",
        expected_task_type="plan",
        expected_depth="standard",
        expected_caps=["profile_memory_agent", "semantic_memory_agent", "web_researcher", "academic_strategy_agent"],
        llm_triage={
            "domain": "academic",
            "task_type": "plan",
            "reasoning_depth": "standard",
            "needs_web": True,
            "needs_documents": False,
            "needs_profile": True,
            "reasoning": "Academic planning question",
        },
    ),
    Scenario(
        name="role_comparison",
        query="Compare data engineer vs ML engineer for me",
        expected_domain="career",
        expected_task_type="compare",
        expected_depth="deep",
        expected_caps=["decision_comparison_agent", "plan_action_agent", "answer_composer_agent"],
        llm_triage={
            "domain": "career",
            "task_type": "compare",
            "reasoning_depth": "deep",
            "needs_web": True,
            "needs_documents": False,
            "needs_profile": True,
            "reasoning": "Comparison question",
        },
    ),
    Scenario(
        name="resume_jobs_current_turn",
        query="Based on my resume, which jobs should I aim for?",
        files=True,
        expected_domain="career",
        expected_task_type="analyze",
        expected_depth="standard",
        expected_caps=["document_evidence_agent", "profile_memory_agent", "career_strategy_agent"],
        llm_triage={
            "domain": "career",
            "task_type": "analyze",
            "reasoning_depth": "standard",
            "needs_web": False,
            "needs_documents": True,
            "needs_profile": True,
            "reasoning": "Use attached resume first",
        },
    ),
    Scenario(
        name="resume_improvement_current_turn",
        query="Review my attached resume and tell me what to improve",
        files=True,
        expected_domain="career",
        expected_task_type="analyze",
        expected_depth="standard",
        expected_caps=["document_evidence_agent", "profile_memory_agent", "career_strategy_agent"],
        llm_triage={
            "domain": "career",
            "task_type": "analyze",
            "reasoning_depth": "standard",
            "needs_web": False,
            "needs_documents": True,
            "needs_profile": True,
            "reasoning": "Resume review",
        },
    ),
    Scenario(
        name="transcript_summary_current_turn",
        query="Summarize the attached transcript",
        files=True,
        expected_domain="document",
        expected_task_type="analyze",
        expected_depth="standard",
        expected_caps=["document_evidence_agent", "profile_memory_agent", "document_understanding_agent"],
        llm_triage={
            "domain": "document",
            "task_type": "analyze",
            "reasoning_depth": "standard",
            "needs_web": False,
            "needs_documents": True,
            "needs_profile": True,
            "reasoning": "Document understanding request",
        },
    ),
    Scenario(
        name="web_page_review",
        query="Review this university page https://example.edu/program and summarize the important points",
        expected_domain="research",
        expected_task_type="summarize",
        expected_depth="standard",
        expected_caps=["web_researcher", "decision_comparison_agent", "answer_composer_agent"],
        llm_triage={
            "domain": "research",
            "task_type": "summarize",
            "reasoning_depth": "standard",
            "needs_web": True,
            "needs_documents": False,
            "needs_profile": True,
            "reasoning": "Web review request",
        },
    ),
    Scenario(
        name="simple_greeting",
        query="hello",
        expected_domain="greeting",
        expected_task_type="general",
        expected_depth="light",
        expected_caps=[],
        llm_triage={
            "domain": "greeting",
            "task_type": "general",
            "reasoning_depth": "light",
            "needs_web": False,
            "needs_documents": False,
            "needs_profile": False,
            "reasoning": "Greeting",
        },
    ),
    Scenario(
        name="capability_overview",
        query="what can you do",
        expected_domain="general",
        expected_task_type="clarify",
        expected_depth="light",
        expected_caps=["answer_composer_agent"],
        llm_triage={
            "domain": "general",
            "task_type": "clarify",
            "reasoning_depth": "light",
            "needs_web": False,
            "needs_documents": False,
            "needs_profile": False,
            "reasoning": "Meta question about Pathfinder capabilities",
        },
    ),
    Scenario(
        name="new_chat_from_scratch",
        query="Help me plan my semester from scratch",
        expected_domain="academic",
        expected_task_type="plan",
        expected_depth="deep",
        expected_caps=["academic_strategy_agent", "plan_action_agent", "answer_composer_agent"],
        llm_triage={
            "domain": "academic",
            "task_type": "plan",
            "reasoning_depth": "deep",
            "needs_web": True,
            "needs_documents": False,
            "needs_profile": True,
            "reasoning": "Deep academic planning",
        },
    ),
    Scenario(
        name="follow_up_memory_recall",
        query="What did you recommend last time?",
        expected_domain="general",
        expected_task_type="clarify",
        expected_depth="light",
        expected_caps=["profile_memory_agent", "semantic_memory_agent"],
        llm_triage={
            "domain": "general",
            "task_type": "clarify",
            "reasoning_depth": "light",
            "needs_web": False,
            "needs_documents": False,
            "needs_profile": True,
            "reasoning": "Cross-session memory recall",
        },
    ),
    Scenario(
        name="preference_update",
        query="I prefer remote roles and data-focused work",
        expected_domain="profile",
        expected_task_type="update",
        expected_depth="light",
        expected_caps=["profile_memory_agent", "answer_composer_agent", "memory_writer_agent"],
        llm_triage={
            "domain": "profile",
            "task_type": "update",
            "reasoning_depth": "light",
            "needs_web": False,
            "needs_documents": False,
            "needs_profile": True,
            "reasoning": "Preference update",
        },
    ),
    Scenario(
        name="resume_with_current_turn_question",
        query="Using the attached resume, tell me which roles best match my experience",
        files=True,
        expected_domain="career",
        expected_task_type="analyze",
        expected_depth="standard",
        expected_caps=["document_evidence_agent", "profile_memory_agent", "career_strategy_agent"],
        llm_triage={
            "domain": "career",
            "task_type": "analyze",
            "reasoning_depth": "standard",
            "needs_web": False,
            "needs_documents": True,
            "needs_profile": True,
            "reasoning": "Current-turn resume grounding",
        },
    ),
    Scenario(
        name="too_long_message_blocked",
        query="a" * (MAX_QUERY_LENGTH + 50),
        expected_blocked=True,
        notes="Length guard should block overly long messages.",
    ),
    Scenario(
        name="offtopic_weather_blocked",
        query="What is the weather today in Paris?",
        expected_blocked=True,
        notes="Off-topic queries should still be blocked when topic guard is enabled.",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", SCENARIOS, ids=[scenario.name for scenario in SCENARIOS])
async def test_message_behavior_suite(scenario: Scenario):
    state = _base_state(scenario)
    guarded = await input_guard(state)
    assert guarded.get("is_blocked", False) is scenario.expected_blocked, scenario.notes

    if scenario.expected_blocked:
        assert guarded.get("block_reason")
        return

    if scenario.llm_triage is None:
        triaged = await question_triage(guarded)
    else:
        with patch("app.agents.question_triage.get_text_llm", return_value=_FakeLLM(scenario.llm_triage)):
            triaged = await question_triage(guarded)

    assert triaged["intent"] == scenario.expected_domain
    assert triaged["task_type"] == scenario.expected_task_type
    assert triaged["reasoning_depth"] == scenario.expected_depth

    if scenario.expected_domain == "greeting":
        return

    planned = await reasoning_planner(triaged)
    capabilities = planned.get("active_capabilities", [])

    for capability in scenario.expected_caps:
        assert capability in capabilities, f"{scenario.name}: missing {capability} in {capabilities}"

    for capability in scenario.forbidden_caps:
        assert capability not in capabilities, f"{scenario.name}: unexpected {capability} in {capabilities}"

    if scenario.files and "document_evidence_agent" in capabilities and "profile_memory_agent" in capabilities:
        assert capabilities.index("document_evidence_agent") < capabilities.index("profile_memory_agent")


@pytest.mark.asyncio
async def test_answer_composer_handles_capability_question_without_greeting_fallback():
    state = _base_state(next(s for s in SCENARIOS if s.name == "capability_overview"))
    state.update(
        {
            "intent": "general",
            "task_type": "clarify",
            "reasoning_depth": "light",
            "draft_answer": "",
            "needs_profile": False,
            "needs_documents": False,
            "needs_web": False,
            "profile_data": {"personal": {"name": "Sagar"}},
        }
    )

    final_state = await answer_composer_agent(state)

    assert "academic planning" in final_state["final_answer"].lower()
    assert "what would you like help with next" not in final_state["final_answer"].lower()


@pytest.mark.asyncio
async def test_query_interpreter_agent_populates_helper_fields():
    state = _base_state(next(s for s in SCENARIOS if s.name == "capability_overview"))

    with patch(
        "app.agents.query_interpreter_agent.get_text_llm",
        return_value=_FakePlannerLLM(
            {
                "expanded_query": "The user wants a concise overview of Pathfinder's capabilities and how it can help.",
                "goal": "Understand Pathfinder capabilities",
                "constraints": ["keep it concise"],
                "search_brief": "",
                "notes": "Meta/help request about the system.",
            }
        ),
    ):
        updated = await query_interpreter_agent(state)

    assert updated["query"] == "what can you do"
    assert "overview of Pathfinder's capabilities" in updated["interpreted_query"]
    assert updated["interpreted_goal"] == "Understand Pathfinder capabilities"
    assert updated["interpreted_constraints"] == ["keep it concise"]


@pytest.mark.asyncio
async def test_question_triage_can_use_interpreted_query_as_helper_context():
    state = _base_state(next(s for s in SCENARIOS if s.name == "capability_overview"))
    state.update(
        {
            "query": "help",
            "interpreted_query": "The user is asking what Pathfinder can do and how it can help them.",
            "interpreted_goal": "Understand Pathfinder capabilities",
        }
    )

    with patch(
        "app.agents.question_triage.get_text_llm",
        return_value=_FakeLLM(
            {
                "domain": "general",
                "task_type": "clarify",
                "reasoning_depth": "light",
                "needs_web": False,
                "needs_documents": False,
                "needs_profile": False,
                "reasoning": "Meta/help request",
            }
        ),
    ):
        triaged = await question_triage(state)

    assert triaged["intent"] == "general"
    assert triaged["task_type"] == "clarify"


@pytest.mark.asyncio
async def test_reasoning_planner_can_use_dynamic_direct_recipe_for_meta_question():
    state = {
        "query": "Explain how Pathfinder can help me.",
        "intent": "general",
        "task_type": "clarify",
        "reasoning_depth": "light",
        "needs_web": False,
        "needs_documents": False,
        "needs_profile": False,
        "files": [],
        "planner_trace": [],
        "step_progress": [],
        "active_capabilities": [],
        "web_search_hint": "",
        "answer_rationale": [],
    }

    with patch(
        "app.agents.reasoning_planner.get_text_llm",
        return_value=_FakePlannerLLM(
            {
                "needs_web": False,
                "needs_profile": False,
                "needs_documents": False,
                "reasoning_depth": "light",
                "primary_agent": "none",
                "response_mode": "direct",
                "needs_evidence_judge": False,
                "needs_conflict_check": False,
                "needs_missing_info": False,
                "write_memory": False,
                "must_include": [],
                "web_search_hint": "",
                "reasoning": "This is a lightweight meta question and should be answered directly.",
            }
        ),
    ):
        planned = await reasoning_planner(state)

    assert planned["active_capabilities"] == ["answer_composer_agent"]
    assert planned["answer_style"] == "direct_specialist"


@pytest.mark.asyncio
async def test_missing_info_agent_prefers_dynamic_missing_items():
    state = {
        "query": "Help me choose between grad school and industry.",
        "intent": "career",
        "task_type": "compare",
        "reasoning_depth": "deep",
        "profile_data": {"goals": [], "skills": [], "experience": [], "projects": []},
        "files": [],
        "retrieval_sources": [],
        "retrieval_summary": {},
        "step_progress": [],
        "answer_rationale": [],
        "execution_trace": [],
    }

    with patch(
        "app.agents.missing_info_agent.get_text_llm",
        return_value=_FakePlannerLLM(
            {
                "missing_items": ["preferred timeline", "financial constraints"],
                "reason": "These would meaningfully improve the comparison.",
            }
        ),
    ):
        updated = await missing_info_agent(state)

    assert updated["missing_info"] == ["preferred timeline", "financial constraints"]


@pytest.mark.asyncio
async def test_reasoning_planner_refines_web_and_depth_for_semester_planning():
    state = {
        "query": "Help me plan my semester from scratch",
        "intent": "academic",
        "task_type": "plan",
        "reasoning_depth": "standard",
        "needs_web": False,
        "needs_documents": False,
        "needs_profile": True,
        "files": [],
        "planner_trace": [],
        "step_progress": [],
        "active_capabilities": [],
        "web_search_hint": "",
        "answer_rationale": [],
    }

    with patch(
        "app.agents.reasoning_planner.get_text_llm",
        return_value=_FakePlannerLLM(
            {
                "needs_web": True,
                "needs_profile": True,
                "needs_documents": False,
                "reasoning_depth": "deep",
                "must_include": ["web_researcher", "plan_action_agent"],
                "web_search_hint": "Look for the current course catalog, class schedule, and advising resources for semester planning.",
                "reasoning": "A from-scratch semester plan depends on current institutional information.",
            }
        ),
    ):
        planned = await reasoning_planner(state)

    assert planned["needs_web"] is True
    assert planned["reasoning_depth"] == "deep"
    assert "web_researcher" in planned["active_capabilities"]
    assert "academic_strategy_agent" in planned["active_capabilities"]
    assert "plan_action_agent" in planned["active_capabilities"]
    assert "course catalog" in planned["web_search_hint"].lower()
    assert any("Planner rationale:" in item for item in planned["answer_rationale"])


@pytest.mark.asyncio
async def test_reasoning_planner_can_dynamically_insert_web_researcher_without_keyword_rule():
    state = {
        "query": "I want help choosing classes that fit my path for next term.",
        "intent": "academic",
        "task_type": "plan",
        "reasoning_depth": "standard",
        "needs_web": False,
        "needs_documents": False,
        "needs_profile": True,
        "files": [],
        "planner_trace": [],
        "step_progress": [],
        "active_capabilities": [],
        "web_search_hint": "",
        "answer_rationale": [],
    }

    with patch(
        "app.agents.reasoning_planner.get_text_llm",
        return_value=_FakePlannerLLM(
            {
                "needs_web": True,
                "needs_profile": True,
                "needs_documents": False,
                "reasoning_depth": "deep",
                "must_include": ["web_researcher", "academic_strategy_agent", "plan_action_agent"],
                "web_search_hint": "Check the school's current catalog, course schedule, and prerequisite flow for next term.",
                "reasoning": "This needs external academic information even though the user did not explicitly ask for web search.",
            }
        ),
    ):
        planned = await reasoning_planner(state)

    assert "web_researcher" in planned["active_capabilities"]
    assert planned["active_capabilities"].index("web_researcher") < planned["active_capabilities"].index("academic_strategy_agent")
    assert planned["reasoning_depth"] == "deep"
    assert planned["web_search_hint"].startswith("Check the school's current catalog")


@pytest.mark.asyncio
async def test_reasoning_planner_suppresses_web_for_profile_grounded_career_guidance():
    state = {
        "query": "Based on my profile, suggest two career directions for me in short.",
        "intent": "career",
        "task_type": "recommend",
        "reasoning_depth": "light",
        "needs_web": False,
        "needs_documents": False,
        "needs_profile": True,
        "files": [],
        "planner_trace": [],
        "step_progress": [],
        "active_capabilities": [],
        "web_search_hint": "",
        "answer_rationale": [],
    }

    with patch(
        "app.agents.reasoning_planner.get_text_llm",
        return_value=_FakePlannerLLM(
            {
                "needs_web": True,
                "needs_profile": True,
                "needs_documents": False,
                "reasoning_depth": "light",
                "must_include": ["web_researcher", "career_strategy_agent"],
                "web_search_hint": "Look for current job market evidence.",
                "reasoning": "Career recommendations often benefit from web context.",
            }
        ),
    ):
        planned = await reasoning_planner(state)

    assert "web_researcher" not in planned["active_capabilities"]
    assert "career_strategy_agent" in planned["active_capabilities"]


@pytest.mark.asyncio
async def test_reasoning_planner_suppresses_web_for_local_academic_advice():
    state = {
        "query": "Can you help me think through whether moving closer to campus would improve my semester routine?",
        "intent": "academic",
        "task_type": "recommend",
        "reasoning_depth": "standard",
        "needs_web": False,
        "needs_documents": False,
        "needs_profile": True,
        "files": [],
        "planner_trace": [],
        "step_progress": [],
        "active_capabilities": [],
        "web_search_hint": "",
        "answer_rationale": [],
    }

    with patch(
        "app.agents.reasoning_planner.get_text_llm",
        return_value=_FakePlannerLLM(
            {
                "needs_web": True,
                "needs_profile": True,
                "needs_documents": False,
                "reasoning_depth": "standard",
                "must_include": ["web_researcher", "academic_strategy_agent"],
                "web_search_hint": "Look for commuting and student-life information.",
                "reasoning": "Web could add environmental context.",
            }
        ),
    ):
        planned = await reasoning_planner(state)

    assert "web_researcher" not in planned["active_capabilities"]
    assert "academic_strategy_agent" in planned["active_capabilities"]


@pytest.mark.asyncio
async def test_input_guard_uses_llm_for_borderline_allowed_queries():
    state = {
        "query": "Can you help me think through whether moving closer to campus would improve my semester routine?",
        "topic_guard_enabled": True,
        "step_progress": [],
        "files": [],
    }

    with patch(
        "app.agents.input_guard.get_text_llm",
        return_value=_FakePlannerLLM({"allow": True, "reason": "This is a student-planning question tied to academic success."}),
    ):
        guarded = await input_guard(state)

    assert guarded["is_blocked"] is False


@pytest.mark.asyncio
async def test_input_guard_still_blocks_clear_offtopic_queries_when_llm_rejects():
    state = {
        "query": "Write me a recipe for pancakes with blueberries.",
        "topic_guard_enabled": True,
        "step_progress": [],
        "files": [],
    }

    with patch(
        "app.agents.input_guard.get_text_llm",
        return_value=_FakePlannerLLM({"allow": False, "reason": "Cooking advice is outside Pathfinder's scope."}),
    ):
        guarded = await input_guard(state)

    assert guarded["is_blocked"] is True
