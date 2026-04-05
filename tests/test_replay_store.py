from __future__ import annotations

import json
from pathlib import Path

from app.services import replay_eval
from app.services import replay_store


def test_replay_artifact_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(replay_store.settings, "REPLAY_ARTIFACT_DIR", str(tmp_path))

    done_payload = {
        "method": "rag+graph+facts",
        "quality_path": "profile+documents+facts",
        "confidence": 0.82,
        "stop_reason": "",
        "blocked_reasons": [],
        "student_strategy": {"primary_priority": "internship_readiness"},
        "runtime_snapshot": {"selected_text_model": "qwen/qwen3-14b"},
        "dependency_status": {"neo4j": "connected", "llm": "connected"},
        "retrieval_summary": {"strategy": "memory_pack", "document_count": 3},
        "retrieval_trace": [{"source": "documents", "label": "resume.pdf"}],
        "trace_summary": {"steps": 6},
        "citations": [{"source": "https://example.edu"}],
    }
    final_state = {
        "final_answer": "Recommended next steps.",
        "workflow": "academic_planning",
        "intent": "academic",
        "decision_payload": {"decision_type": "course_planning"},
        "evidence_pack": {
            "document_records": [{"filename": "resume.pdf"}],
            "web_records": [],
            "evidence_records": [{"entity_type": "course"}],
            "profile_facts": [{"fact_type": "goal", "value": "backend internship"}],
        },
    }

    artifact = replay_store.build_replay_artifact(
        query="What courses should I take next semester?",
        done_payload=done_payload,
        final_state=final_state,
        student_id="student_test123",
        session_id="session_test123",
    )
    saved = replay_store.save_replay_artifact(artifact)

    assert saved["id"].startswith("replay_")
    assert saved["student_strategy"]["primary_priority"] == "internship_readiness"
    assert saved["retrieval_summary"]["strategy"] == "memory_pack"
    assert saved["evidence_overview"]["document_count"] == 1

    listed = replay_store.list_replay_artifacts(limit=10)
    assert listed
    assert listed[0]["id"] == saved["id"]

    loaded = replay_store.get_replay_artifact(saved["id"])
    assert loaded is not None
    assert loaded["answer"] == "Recommended next steps."
    assert loaded["decision_payload"]["decision_type"] == "course_planning"

    artifact_path = Path(tmp_path) / f"{saved['id']}.json"
    assert artifact_path.exists()
    parsed = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert parsed["query"] == "What courses should I take next semester?"


def test_replay_evaluation_scores_grounded_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(replay_store.settings, "REPLAY_ARTIFACT_DIR", str(tmp_path))

    artifact = replay_store.build_replay_artifact(
        query="Help me choose between two course plans.",
        done_payload={
            "method": "rag+graph+facts",
            "quality_path": "profile+documents+facts",
            "confidence": 0.77,
            "blocked_reasons": [],
            "student_strategy": {"primary_priority": "gpa_protection"},
            "runtime_snapshot": {"selected_text_model": "qwen/qwen3-14b"},
            "dependency_status": {"neo4j": "connected", "llm": "connected"},
            "retrieval_summary": {"strategy": "memory_pack", "document_count": 2},
            "retrieval_trace": [{"source": "documents", "label": "degree_plan.pdf"}],
            "citations": [{"source": "https://catalog.example.edu"}],
        },
        final_state={
            "final_answer": "Take the balanced option unless you need the lighter load.",
            "workflow": "academic_planning",
            "intent": "academic",
            "decision_payload": {
                "decision_type": "course_planning",
                "recommendation_paths": [{"label": "Balanced", "summary": "Best overall path"}],
            },
            "evidence_pack": {
                "document_records": [{"filename": "degree_plan.pdf"}],
                "web_records": [],
                "evidence_records": [{"entity_type": "course"}],
                "profile_facts": [{"fact_type": "goal", "value": "protect GPA"}],
            },
        },
        student_id="student_eval123",
        session_id="session_eval123",
    )
    saved = replay_store.save_replay_artifact(artifact)

    evaluation = replay_eval.evaluate_replay_by_id(saved["id"])
    assert evaluation is not None
    assert evaluation["status"] in {"pass", "warn"}
    assert evaluation["checks"]["answer_present"] is True
    assert evaluation["checks"]["has_grounding"] is True
    assert evaluation["metrics"]["citation_count"] == 1

    batch = replay_eval.evaluate_recent_replays(limit=10, student_id="student_eval123")
    assert batch["summary"]["total"] >= 1
    assert batch["evaluations"][0]["replay_id"] == saved["id"]
