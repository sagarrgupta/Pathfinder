from app.adapters.llm.lmstudio import is_garbage_output
from app.core.quality import infer_quality_path
from app.agents.responder import _render_decision_payload


def test_short_correct_answer_is_not_treated_as_garbage():
    assert is_garbage_output("Yes, CSC 215 is a good catalog-based option.") is False


def test_quality_path_reflects_structured_pipeline():
    path = infer_quality_path({
        "profile_data": {"personal": {"name": "Sagar"}},
        "web_results": [{"url": "https://catalog.csus.edu"}],
        "evidence_records": [{"entity_type": "course"}],
        "decision_payload": {"decision_type": "course_planning"},
        "confidence_score": 0.8,
        "workflow": "academic_planning",
    })

    assert path == "profile+web+facts+planner+eval+academic_planning"


def test_rendered_payload_does_not_override_existing_safe_draft():
    draft = "I could not verify a 2-year semester-by-semester plan from the official sources yet."
    payload = {
        "answer_outline": ["Invented planner content"],
        "recommended_items": [{"label": "CS 601", "reason": "unsupported"}],
    }

    chosen = draft if draft else _render_decision_payload(payload, 0.4)
    assert chosen == draft
