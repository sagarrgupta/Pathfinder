from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable

from app.main import app


class FakeGraph:
    async def astream(self, initial_state, config=None):
        yield {"guardrail_agent": {"step_progress": ["Guard ok"]}}
        yield {
            "question_triage": {
                "step_progress": ["Guard ok", "Triage done"],
                "intent": "career",
                "task_type": "recommend",
                "reasoning_depth": "deep",
            }
        }
        yield {
            "answer_composer_agent": {
                "step_progress": ["Guard ok", "Triage done", "Final answer ready"],
                "final_answer": "Based on your profile, focus on backend roles first.",
                "confidence_score": 0.82,
                "citations": [{"source": "resume.pdf", "metadata": {"title": "Resume"}}],
                "retrieval_sources": ["profile", "memory", "documents"],
                "planner_trace": [
                    "triage:career:recommend:deep",
                    "planner:profile_memory_agent->semantic_memory_agent->career_strategy_agent->answer_composer_agent->memory_writer_agent",
                ],
                "recommended_actions": ["Polish your Python projects", "Apply to 5 backend internships"],
                "missing_info": ["Preferred location"],
                "conflicts": [{"id": "c1", "fact_type": "goal", "value": "ML engineer"}],
                "conflict_nudges": ["I have two possible goal signals for you."],
                "retrieval_summary": {"memory_items": 2, "candidate_facts": 1, "documents": 1},
                "consolidation_summary": {"triggered": True},
                "execution_trace": [{"agent": "career_strategy_agent"}],
                "answer_rationale": ["Matches current project background"],
            }
        }


FAKE_PROFILES = [
    {
        "id": "student-1",
        "name": "Alice",
        "email": None,
        "university": "Sac State",
        "program": "CS",
        "created_at": None,
        "updated_at": None,
        "completeness": 0.5,
    }
]

PROFILE_PAYLOAD = {
    "personal": {"name": "Alice", "program": "CS", "university": "Sac State"},
    "courses": [],
    "skills": [{"name": "Python"}],
    "goals": [{"name": "Backend engineer"}],
    "documents": [{"filename": "resume.pdf"}],
    "interests": [],
    "experience": [],
    "projects": [],
    "constraints": [],
    "preferences": [],
    "behavioral_patterns": [],
    "candidate_facts": [{"confidence": 0.8, "status": "resolved"}],
    "memory_items": [{"summary": "Prefers concise answers"}],
    "evidence": [{"source_type": "chat"}],
    "all_entities": {},
}

SAVED_RECS = [
    {
        "id": "memory-1",
        "student_id": "student-1",
        "summary": "Plan for internships",
        "memory_type": "saved_plan",
        "created_at": None,
        "metadata": {
            "title": "Internship push",
            "actions": ["Update resume"],
            "status": "active",
            "follow_up_prompt": "Did you apply?",
            "next_review_at": "2026-04-06T00:00:00Z",
        },
    }
]


def _patched_client():
    return patch.multiple(
        "app.main",
        init_schema=AsyncMock(),
        ensure_vector_index=AsyncMock(),
        list_students=AsyncMock(return_value=FAKE_PROFILES),
        start_background_jobs=lambda: None,
        stop_background_jobs=AsyncMock(),
        close_driver=AsyncMock(),
    )


def test_storage_failure_returns_503():
    with patch("app.api.routes.list_students", new=AsyncMock(side_effect=ServiceUnavailable("db down"))):
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/api/v1/profiles")
    assert response.status_code == 503
    assert "datastore" in response.json()["detail"].lower()


def test_profile_and_chat_flow_smoke():
    with _patched_client(), patch(
        "app.api.routes.list_students", new=AsyncMock(return_value=FAKE_PROFILES)
    ), patch("app.api.routes.create_student", new=AsyncMock(return_value=FAKE_PROFILES[0])), patch(
        "app.api.routes.ensure_student", new=AsyncMock(return_value=FAKE_PROFILES[0])
    ), patch(
        "app.api.routes.get_full_profile", new=AsyncMock(return_value=PROFILE_PAYLOAD)
    ), patch(
        "app.api.routes.list_saved_recommendations", new=AsyncMock(return_value=SAVED_RECS)
    ), patch(
        "app.api.routes.store_memory_item", new=AsyncMock(return_value=SAVED_RECS[0])
    ), patch(
        "app.api.routes.get_compiled_graph", new=AsyncMock(return_value=FakeGraph())
    ):
        with TestClient(app) as client:
            profiles = client.get("/api/v1/profiles")
            assert profiles.status_code == 200
            assert profiles.json()[0]["student_id"] == "student-1"

            profile = client.get("/api/v1/profile", params={"student_id": "student-1"})
            assert profile.status_code == 200
            assert profile.json()["memory_overview"]["candidate_facts"] == 1

            saved = client.get("/api/v1/recommendations", params={"student_id": "student-1"})
            assert saved.status_code == 200
            assert saved.json()[0]["title"] == "Internship push"

            chat = client.post(
                "/api/v1/chat",
                data={"query": "Help me plan my career", "student_id": "student-1"},
            )
            assert chat.status_code == 200
            assert "event: done" in chat.text
            assert "\"student_id\": \"student-1\"" in chat.text
            assert "Apply to 5 backend internships" in chat.text
