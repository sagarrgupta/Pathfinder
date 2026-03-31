from __future__ import annotations

import json
import sys
import types
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


def _install_test_stubs() -> None:
    if "neo4j" not in sys.modules:
        neo4j_module = types.ModuleType("neo4j")

        class AsyncDriver:  # pragma: no cover - import stub
            pass

        class _DummySession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def run(self, *_args, **_kwargs):
                return _DummyResult()

        class _DummyDriver:
            def session(self):
                return _DummySession()

            async def close(self):
                return None

        class AsyncGraphDatabase:  # pragma: no cover - import stub
            @staticmethod
            def driver(*_args, **_kwargs):
                return _DummyDriver()

        neo4j_module.AsyncDriver = AsyncDriver
        neo4j_module.AsyncGraphDatabase = AsyncGraphDatabase
        sys.modules["neo4j"] = neo4j_module

    if "neo4j.exceptions" not in sys.modules:
        exceptions_module = types.ModuleType("neo4j.exceptions")

        class Neo4jError(Exception):
            pass

        class ServiceUnavailable(Neo4jError):
            pass

        exceptions_module.Neo4jError = Neo4jError
        exceptions_module.ServiceUnavailable = ServiceUnavailable
        sys.modules["neo4j.exceptions"] = exceptions_module

    if "neo4j.time" not in sys.modules:
        time_module = types.ModuleType("neo4j.time")

        class _BaseTemporal:
            def to_native(self):
                return self

            def isoformat(self):
                return "1970-01-01T00:00:00"

            def __str__(self):
                return self.isoformat()

        class DateTime(_BaseTemporal):
            pass

        class Date(_BaseTemporal):
            pass

        class Time(_BaseTemporal):
            pass

        class Duration(_BaseTemporal):
            pass

        time_module.DateTime = DateTime
        time_module.Date = Date
        time_module.Time = Time
        time_module.Duration = Duration
        sys.modules["neo4j.time"] = time_module

    if "langchain_openai" not in sys.modules:
        langchain_openai_module = types.ModuleType("langchain_openai")

        class ChatOpenAI:  # pragma: no cover - import stub
            def __init__(self, *args, **kwargs):
                pass

            async def ainvoke(self, *_args, **_kwargs):
                return types.SimpleNamespace(content="")

        langchain_openai_module.ChatOpenAI = ChatOpenAI
        sys.modules["langchain_openai"] = langchain_openai_module

    if "langchain_ollama" not in sys.modules:
        langchain_ollama_module = types.ModuleType("langchain_ollama")

        class OllamaEmbeddings:  # pragma: no cover - import stub
            def __init__(self, *args, **kwargs):
                pass

            def embed_query(self, _text):
                return [0.0, 0.0, 0.0]

            def embed_documents(self, texts):
                return [[0.0, 0.0, 0.0] for _ in texts]

        langchain_ollama_module.OllamaEmbeddings = OllamaEmbeddings
        sys.modules["langchain_ollama"] = langchain_ollama_module

    if "bs4" not in sys.modules:
        bs4_module = types.ModuleType("bs4")

        class _StubNode:
            def get_text(self, separator=" ", strip=True):
                return ""

            def decompose(self):
                return None

            def find_all(self, *_args, **_kwargs):
                return []

        class BeautifulSoup:  # pragma: no cover - import stub
            def __init__(self, *_args, **_kwargs):
                self.body = _StubNode()

            def find(self, *_args, **_kwargs):
                return None

            def find_all(self, *_args, **_kwargs):
                return []

        bs4_module.BeautifulSoup = BeautifulSoup
        sys.modules["bs4"] = bs4_module

    if "aiosqlite" not in sys.modules:
        aiosqlite_module = types.ModuleType("aiosqlite")

        async def connect(*_args, **_kwargs):
            return object()

        aiosqlite_module.connect = connect
        sys.modules["aiosqlite"] = aiosqlite_module

    if "langgraph.checkpoint.sqlite.aio" not in sys.modules:
        langgraph_sqlite_module = types.ModuleType("langgraph.checkpoint.sqlite.aio")

        class AsyncSqliteSaver:  # pragma: no cover - import stub
            def __init__(self, _conn):
                pass

            async def setup(self):
                return None

        langgraph_sqlite_module.AsyncSqliteSaver = AsyncSqliteSaver
        sys.modules["langgraph.checkpoint.sqlite.aio"] = langgraph_sqlite_module


class _DummyResult:
    async def single(self):
        return None

    def __aiter__(self):
        async def _empty():
            if False:
                yield None

        return _empty()


_install_test_stubs()

from app.agents.input_guard import MAX_QUERY_LENGTH, input_guard
from app.agents.question_triage import question_triage
from app.agents.reasoning_planner import reasoning_planner
from app.main import app


@dataclass(frozen=True)
class UserFixture:
    student_id: str
    name: str
    university: str
    program: str
    gpa: str
    semester: str
    goal: str
    preference: str
    top_skill: str
    project_focus: str


@dataclass(frozen=True)
class ScenarioTemplate:
    slug: str
    query: str
    domain: str
    task_type: str
    depth: str
    needs_web: bool = False
    needs_documents: bool = False
    needs_profile: bool = True
    files: tuple[tuple[str, bytes, str], ...] = ()
    blocked: bool = False
    expect_personalization: bool = True
    expect_actions: bool = False
    expect_citations: bool = False
    expect_sources: tuple[str, ...] = ()
    missing_info: tuple[str, ...] = ()
    expected_reply_contains: tuple[str, ...] = ()


@dataclass(frozen=True)
class MessageScenario:
    user: UserFixture
    template: ScenarioTemplate

    @property
    def id(self) -> str:
        return f"{self.user.student_id}_{self.template.slug}"


USERS = [
    UserFixture("student-a", "Sagar", "California State University, Sacramento", "Computer Science", "3.65", "Spring 2026", "Backend internships", "remote-friendly roles", "Python", "backend APIs"),
    UserFixture("student-b", "Viv", "Sacramento State", "Pre-Computer Science", "3.20", "Fall 2026", "Transfer into CS", "structured plans", "Java", "course planning"),
    UserFixture("student-c", "Alicia", "UC Davis", "Data Science", "3.82", "Spring 2026", "ML engineer roles", "research-heavy roles", "SQL", "machine learning"),
    UserFixture("student-d", "Marcus", "San Jose State University", "Software Engineering", "3.41", "Fall 2025", "Full-stack internships", "startup environments", "TypeScript", "frontend systems"),
    UserFixture("student-e", "Nina", "University of the Pacific", "Business Analytics", "3.74", "Summer 2026", "Data analyst roles", "hybrid work", "Excel", "dashboards"),
]


TEMPLATES = [
    ScenarioTemplate("intro_short", "I am {name}", "profile", "update", "light", expected_reply_contains=("updated your profile",)),
    ScenarioTemplate("intro_full", "I am {name}, a {program} student at {university}", "profile", "update", "light", expected_reply_contains=("updated your profile",)),
    ScenarioTemplate("goal_update", "My goal is {goal}", "profile", "update", "light", expected_reply_contains=("updated your profile",)),
    ScenarioTemplate("pref_update", "I prefer {preference}", "profile", "update", "light", expected_reply_contains=("updated your profile",)),
    ScenarioTemplate("name_recall", "What is my name?", "profile", "summarize", "light", expected_reply_contains=("{name}",)),
    ScenarioTemplate("school_recall", "Which university do I study at?", "profile", "summarize", "light", expected_reply_contains=("{university}",)),
    ScenarioTemplate("gpa_recall", "What is my GPA?", "profile", "summarize", "light", expected_reply_contains=("{gpa}",)),
    ScenarioTemplate("profile_summary", "What do you know about me right now?", "profile", "summarize", "light", expected_reply_contains=("{name}", "{program}")),
    ScenarioTemplate("academic_plan", "What courses should I take next semester?", "academic", "plan", "standard", needs_web=True, expect_actions=True, expect_sources=("profile", "memory", "web")),
    ScenarioTemplate("career_roles", "What jobs can I get based on my profile?", "career", "recommend", "standard", expect_actions=True, expect_sources=("profile", "memory")),
    ScenarioTemplate("career_fit", "Based on my background, suggest two roles that fit me.", "career", "recommend", "light", expect_actions=True, expect_sources=("profile", "memory")),
    ScenarioTemplate("interview_prep", "Prepare me for an interview for {goal}.", "interview", "plan", "standard", expect_actions=True, expect_sources=("profile", "memory")),
    ScenarioTemplate("role_compare", "Compare two career directions for me: backend engineer vs data engineer.", "career", "compare", "deep", needs_web=True, expect_actions=True, expect_sources=("profile", "memory", "web")),
    ScenarioTemplate("resume_roles", "Based on my attached resume, which roles should I aim for?", "career", "analyze", "standard", needs_documents=True, files=(("resume.pdf", b"resume data", "application/pdf"),), expect_actions=True, expect_citations=True, expect_sources=("profile", "documents")),
    ScenarioTemplate("resume_review", "Review my attached resume and tell me what to improve.", "career", "analyze", "standard", needs_documents=True, files=(("resume.pdf", b"resume review", "application/pdf"),), expect_actions=True, expect_citations=True, expect_sources=("profile", "documents")),
    ScenarioTemplate("transcript_summary", "Summarize the attached transcript.", "document", "analyze", "standard", needs_documents=True, files=(("transcript.pdf", b"transcript data", "application/pdf"),), expect_citations=True, expect_sources=("profile", "documents")),
    ScenarioTemplate("doc_followup", "Use my attached document and tell me what stands out.", "document", "analyze", "standard", needs_documents=True, files=(("statement.pdf", b"statement data", "application/pdf"),), expect_citations=True, expect_sources=("profile", "documents")),
    ScenarioTemplate("follow_up", "What did you recommend last time?", "general", "clarify", "light", expected_reply_contains=("last time",)),
    ScenarioTemplate("missing_info", "Help me choose between grad school and industry.", "career", "compare", "deep", needs_web=True, expect_actions=True, missing_info=("preferred timeline",), expect_sources=("profile", "memory", "web")),
    ScenarioTemplate("offtopic_block", "What is the weather in Paris today?", "general", "general", "light", blocked=True, expect_personalization=False),
]


class _FakeResponse:
    def __init__(self, content: str):
        self.content = content


class _FakeLLM:
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload

    async def ainvoke(self, _messages):
        return _FakeResponse(json.dumps(self.payload))


def _triage_payload(template: ScenarioTemplate) -> dict[str, Any]:
    return {
        "domain": template.domain,
        "task_type": template.task_type,
        "reasoning_depth": template.depth,
        "needs_web": template.needs_web,
        "needs_documents": template.needs_documents,
        "needs_profile": template.needs_profile,
        "reasoning": f"{template.domain}::{template.task_type}",
    }


def _scenario_query(template: ScenarioTemplate, user: UserFixture) -> str:
    return template.query.format(
        name=user.name,
        university=user.university,
        program=user.program,
        gpa=user.gpa,
        goal=user.goal,
        preference=user.preference,
    )


def _profile_payload(user: UserFixture) -> dict[str, Any]:
    return {
        "personal": {
            "name": user.name,
            "university": user.university,
            "program": user.program,
            "gpa": user.gpa,
            "semester": user.semester,
        },
        "courses": [{"name": "Algorithms", "code": "CSC 130"}],
        "skills": [{"name": user.top_skill}],
        "goals": [{"name": user.goal}],
        "documents": [{"filename": f"{user.student_id}-resume.pdf"}],
        "interests": [{"name": user.project_focus}],
        "experience": [],
        "projects": [{"name": f"{user.project_focus.title()} Project"}],
        "constraints": [],
        "preferences": [{"name": user.preference}],
        "behavioral_patterns": [],
        "candidate_facts": [{"confidence": 0.85, "status": "resolved"}],
        "memory_items": [{"summary": f"Prefers {user.preference}"}],
        "evidence": [{"source_type": "chat"}],
        "all_entities": {},
    }


def _saved_recommendations(user: UserFixture) -> list[dict[str, Any]]:
    return [
        {
            "id": f"rec-{user.student_id}",
            "student_id": user.student_id,
            "summary": f"Prior plan for {user.goal}",
            "memory_type": "saved_plan",
            "created_at": None,
            "metadata": {
                "title": f"{user.goal} plan",
                "actions": [f"Strengthen {user.top_skill} portfolio"],
                "status": "active",
                "follow_up_prompt": "What progress did you make?",
                "next_review_at": "2026-04-15T00:00:00Z",
                "source_query": "What should I do next?",
            },
        }
    ]


class DeterministicGraph:
    def __init__(self, scenario_map: dict[tuple[str, str], MessageScenario]):
        self.scenario_map = scenario_map

    async def astream(self, initial_state, config=None):
        key = (initial_state["student_id"], initial_state["query"])
        scenario = self.scenario_map[key]
        user = scenario.user

        guarded = await input_guard(initial_state)
        yield {"guardrail_agent": {"step_progress": guarded.get("step_progress", []), "is_blocked": guarded.get("is_blocked", False)}}
        if guarded.get("is_blocked"):
          yield {
              "answer_composer_agent": {
                  "step_progress": guarded.get("step_progress", []) + ["Blocked by guardrail"],
                  "final_answer": guarded["block_reason"],
                  "confidence_score": 1.0,
                  "citations": [],
                  "retrieval_sources": [],
                  "planner_trace": [],
                  "recommended_actions": [],
                  "missing_info": [],
                  "conflicts": [],
                  "conflict_nudges": [],
                  "retrieval_summary": {},
                  "consolidation_summary": {},
                  "execution_trace": [],
                  "answer_rationale": ["Guardrail policy applied."],
              }
          }
          return

        payload = _triage_payload(scenario.template)
        with patch("app.agents.question_triage.get_text_llm", return_value=_FakeLLM(payload)):
            triaged = await question_triage(guarded)
        yield {
            "question_triage": {
                "step_progress": triaged.get("step_progress", []),
                "intent": triaged["intent"],
                "task_type": triaged["task_type"],
                "reasoning_depth": triaged["reasoning_depth"],
            }
        }
        planned = await reasoning_planner(triaged)
        yield {
            "reasoning_planner": {
                "step_progress": planned.get("step_progress", []),
                "planner_trace": planned.get("planner_trace", []),
                "active_capabilities": planned.get("active_capabilities", []),
            }
        }
        answer = _build_answer(scenario, planned)
        yield {
            "answer_composer_agent": {
                "step_progress": planned.get("step_progress", []) + ["Final answer ready"],
                **answer,
            }
        }


def _build_answer(scenario: MessageScenario, planned: dict[str, Any]) -> dict[str, Any]:
    user = scenario.user
    template = scenario.template
    capabilities = planned.get("active_capabilities", [])

    citations = []
    retrieval_sources = []
    retrieval_summary = {"memory_items": 0, "candidate_facts": 0, "documents": 0, "web_results": 0}
    recommended_actions: list[str] = []
    missing_info = list(template.missing_info)
    rationale = [f"Matched {template.domain} intent for {user.name}."]

    if template.needs_profile:
        retrieval_sources.extend(["profile", "memory"])
        retrieval_summary["memory_items"] = 2
        retrieval_summary["candidate_facts"] = 1
    if template.needs_documents or template.files:
        retrieval_sources.append("documents")
        retrieval_summary["documents"] = max(1, len(template.files))
        citations = [{"source": f[0], "metadata": {"title": f[0]}} for f in template.files]
    if template.needs_web:
        retrieval_sources.append("web")
        retrieval_summary["web_results"] = 2

    if template.expect_actions:
        recommended_actions = [
            f"Prioritize work aligned with {user.goal.lower()}",
            f"Showcase {user.top_skill} through a project focused on {user.project_focus}",
        ]

    if template.slug.startswith("intro") or template.slug in {"goal_update", "pref_update"}:
        final_answer = (
            f"I've updated your profile, {user.name}. "
            f"I'll use your {user.program} background at {user.university} in future guidance."
        )
    elif template.slug == "name_recall":
        final_answer = f"Your name is {user.name}."
    elif template.slug == "school_recall":
        final_answer = f"You study at {user.university}."
    elif template.slug == "gpa_recall":
        final_answer = f"Your GPA is {user.gpa}."
    elif template.slug == "profile_summary":
        final_answer = (
            f"I know that you are {user.name}, studying {user.program} at {user.university}, "
            f"with a GPA of {user.gpa}, and currently targeting {user.goal.lower()}."
        )
    elif template.slug == "academic_plan":
        final_answer = (
            f"For {user.name}, the next semester should prioritize courses that support {user.goal.lower()}. "
            f"Given your {user.program} background and semester {user.semester}, I would balance core progress with one portfolio-building elective."
        )
    elif template.slug in {"career_roles", "career_fit"}:
        final_answer = (
            f"Based on your {user.program} background, GPA {user.gpa}, and strength in {user.top_skill}, "
            f"the best fit roles for you are aligned with {user.goal.lower()} and adjacent applied engineering paths."
        )
    elif template.slug == "interview_prep":
        final_answer = (
            f"To prepare for {user.goal.lower()}, focus on explaining {user.project_focus}, "
            f"demonstrating {user.top_skill}, and practicing concise behavioral stories."
        )
    elif template.slug == "role_compare":
        final_answer = (
            f"For you, backend engineering is a stronger near-term match because it fits your {user.top_skill} foundation, "
            f"while data engineering becomes stronger if you want more pipeline and analytics-heavy work."
        )
    elif template.slug in {"resume_roles", "resume_review"}:
        final_answer = (
            f"Based on the attached resume and your {user.program} profile, "
            f"you should target roles connected to {user.goal.lower()} and strengthen how you present {user.top_skill} work."
        )
    elif template.slug in {"transcript_summary", "doc_followup"}:
        final_answer = (
            f"The attached document reinforces your current direction. "
            f"The most relevant signals for {user.name} are strong alignment with {user.goal.lower()} and evidence around {user.project_focus}."
        )
    elif template.slug == "follow_up":
        final_answer = (
            f"Last time I recommended a plan focused on {user.goal.lower()} and strengthening {user.top_skill}. "
            f"The next step is to review progress against that plan."
        )
    elif template.slug == "missing_info":
        final_answer = (
            f"Both grad school and industry could fit your {user.program} background. "
            f"Right now, industry looks slightly stronger, but I still need your preferred timeline to personalize the choice more confidently."
        )
    else:
        final_answer = f"I can help with that, {user.name}."

    return {
        "final_answer": final_answer,
        "confidence_score": 0.83 if not missing_info else 0.72,
        "citations": citations,
        "retrieval_sources": retrieval_sources,
        "planner_trace": planned.get("planner_trace", []),
        "recommended_actions": recommended_actions,
        "missing_info": missing_info,
        "conflicts": [],
        "conflict_nudges": [],
        "retrieval_summary": retrieval_summary,
        "consolidation_summary": {"triggered": bool(template.slug.startswith("intro") or template.slug in {"goal_update", "pref_update"})},
        "execution_trace": [{"agent": cap} for cap in capabilities],
        "answer_rationale": rationale,
    }


def _parse_sse(text: str) -> tuple[str, dict[str, Any]]:
    event_type = None
    tokens: list[str] = []
    done_payload: dict[str, Any] | None = None
    for raw_line in text.splitlines():
        if raw_line.startswith("event: "):
            event_type = raw_line[7:].strip()
        elif raw_line.startswith("data: "):
            payload = json.loads(raw_line[6:])
            if event_type == "token":
                tokens.append(payload.get("content", ""))
            elif event_type == "done":
                done_payload = payload
    return "".join(tokens).strip(), done_payload or {}


def _score_response(
    scenario: MessageScenario,
    answer_text: str,
    done_payload: dict[str, Any],
) -> dict[str, bool]:
    metadata = done_payload.get("metadata", {})
    user = scenario.user
    template = scenario.template
    lower_answer = answer_text.lower()
    forbidden_names = {other.name.lower() for other in USERS if other.student_id != user.student_id}

    expected_tokens = [
        token.format(
            name=user.name,
            university=user.university,
            program=user.program,
            gpa=user.gpa,
        ).lower()
        for token in template.expected_reply_contains
    ]
    has_personal_signal = any(
        signal.lower() in lower_answer
        for signal in [user.name, user.program, user.university, user.goal, user.top_skill, user.gpa]
    )

    scores = {
        "non_empty": bool(answer_text.strip()),
        "no_generic_failure": "couldn't generate" not in lower_answer and "error:" not in lower_answer,
        "personalized": (not template.expect_personalization) or has_personal_signal,
        "isolated": all(name not in lower_answer for name in forbidden_names),
        "expected_content": all(token in lower_answer for token in expected_tokens) if expected_tokens else True,
        "actionable": (not template.expect_actions) or len(metadata.get("recommended_actions", [])) >= 1,
        "grounded": (not template.expect_citations) or len(done_payload.get("citations", [])) >= 1,
        "sources_match": all(source in metadata.get("sources", []) for source in template.expect_sources),
        "missing_info_signaled": (not template.missing_info) or all(item in metadata.get("missing_info", []) for item in template.missing_info),
        "planner_trace_present": template.blocked or len(metadata.get("planner_trace", [])) >= 1,
    }
    return scores


def _patched_client(scenario_map, users):
    fake_profiles = [
        {
            "id": user.student_id,
            "name": user.name,
            "email": None,
            "university": user.university,
            "program": user.program,
            "created_at": None,
            "updated_at": None,
            "completeness": 0.5,
        }
        for user in users
    ]

    async def _ensure_student(student_id):
        for profile in fake_profiles:
            if profile["id"] == student_id:
                return profile
        return {"id": student_id, "name": "Student"}

    async def _get_student(student_id):
        for profile in fake_profiles:
            if profile["id"] == student_id:
                return profile
        return None

    async def _get_full_profile(student_id):
        user = next(user for user in users if user.student_id == student_id)
        return _profile_payload(user)

    async def _list_saved(student_id):
        user = next(user for user in users if user.student_id == student_id)
        return _saved_recommendations(user)

    return patch.multiple(
        "app.main",
        init_schema=AsyncMock(),
        ensure_vector_index=AsyncMock(),
        list_students=AsyncMock(return_value=fake_profiles),
        start_background_jobs=lambda: None,
        stop_background_jobs=AsyncMock(),
        close_driver=AsyncMock(),
    ), patch.multiple(
        "app.api.routes",
        list_students=AsyncMock(return_value=fake_profiles),
        create_student=AsyncMock(return_value=fake_profiles[0]),
        ensure_student=AsyncMock(side_effect=_ensure_student),
        get_student=AsyncMock(side_effect=_get_student),
        get_full_profile=AsyncMock(side_effect=_get_full_profile),
        list_saved_recommendations=AsyncMock(side_effect=_list_saved),
        find_document_by_filename=AsyncMock(return_value=None),
        delete_document_cascade=AsyncMock(return_value=True),
        get_compiled_graph=AsyncMock(return_value=DeterministicGraph(scenario_map)),
    )


ALL_SCENARIOS = [
    MessageScenario(user=user, template=template)
    for user in USERS
    for template in TEMPLATES
]

assert len(ALL_SCENARIOS) == 100


def test_generated_scenario_count_is_100():
    assert len(ALL_SCENARIOS) == 100


def test_multi_user_100_message_suite():
    scenario_map = {(scenario.user.student_id, _scenario_query(scenario.template, scenario.user)): scenario for scenario in ALL_SCENARIOS}
    main_patch, route_patch = _patched_client(scenario_map, USERS)

    with main_patch, route_patch, TestClient(app) as client:
        for scenario in ALL_SCENARIOS:
            query = _scenario_query(scenario.template, scenario.user)
            request_kwargs: dict[str, Any] = {
                "data": {"query": query, "student_id": scenario.user.student_id},
            }
            if scenario.template.files:
                request_kwargs["files"] = [
                    ("files", (filename, content, content_type))
                    for filename, content, content_type in scenario.template.files
                ]

            response = client.post("/api/v1/chat", **request_kwargs)
            assert response.status_code == 200, scenario.id
            answer_text, done_payload = _parse_sse(response.text)
            assert done_payload.get("student_id") == scenario.user.student_id, scenario.id

            metrics = _score_response(scenario, answer_text, done_payload)
            failed = [name for name, passed in metrics.items() if not passed]
            assert not failed, f"{scenario.id} failed metrics: {failed}\nanswer={answer_text}\nmetadata={done_payload.get('metadata')}"


def test_profile_reset_does_not_recreate_deleted_profile():
    fake_profiles = [
        {
            "id": "student-reset",
            "name": "Student",
            "email": None,
            "university": None,
            "program": None,
            "created_at": None,
            "updated_at": None,
            "completeness": 0.0,
        }
    ]

    with patch.multiple(
        "app.main",
        init_schema=AsyncMock(),
        ensure_vector_index=AsyncMock(),
        list_students=AsyncMock(return_value=fake_profiles),
        start_background_jobs=lambda: None,
        stop_background_jobs=AsyncMock(),
        close_driver=AsyncMock(),
    ), patch.multiple(
        "app.api.routes",
        list_students=AsyncMock(return_value=fake_profiles),
        ensure_student=AsyncMock(return_value=fake_profiles[0]),
        get_student=AsyncMock(return_value=None),
        reset_student_data=AsyncMock(return_value=True),
    ):
        with TestClient(app) as client:
            reset = client.delete("/api/v1/profile/reset", params={"student_id": "student-reset"})
            assert reset.status_code == 200

            profile = client.get("/api/v1/profile", params={"student_id": "student-reset"})
            assert profile.status_code == 200
            body = profile.json()
            assert body["personal"] == {}
            assert body["documents"] == []
            assert body["completeness"] == 0.0
