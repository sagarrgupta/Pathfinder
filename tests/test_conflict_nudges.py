from app.agents.conflict_resolution_agent import _build_nudge, _needs_nudge, build_conflict_nudges
from app.services.retrieval import _collect_conflicts


def test_build_nudge_includes_dropdown_options():
    nudge = _build_nudge(
        {
            "id": "candidate_1",
            "fact_type": "goal",
            "value": "industry job",
            "alternatives": ["phd"],
        }
    )

    assert nudge["options"][0]["action"] == "choose_value"
    assert any(option["label"] == "Keep both for now" for option in nudge["options"])
    assert any(option["label"] == "Ask me later" for option in nudge["options"])


def test_needs_nudge_respects_snooze_state():
    conflict = {
        "confidence": 0.9,
        "conflict_kind": "explicit",
        "nudge_state": "snoozed",
        "nudge_until": "2999-01-01T00:00:00Z",
        "nudge_count": 3,
    }

    assert _needs_nudge(conflict) is False


def test_collect_conflicts_ignores_superseded_values():
    conflicts = _collect_conflicts(
        {"candidate_facts": []},
        {
            "candidate_facts": [
                {"id": "1", "fact_type": "goal", "value": "industry", "confidence": 0.9, "status": "resolved"},
                {"id": "2", "fact_type": "goal", "value": "phd", "confidence": 0.8, "status": "superseded"},
            ]
        },
    )

    assert conflicts == []


def test_collect_conflicts_allows_compatible_preferences_to_coexist():
    conflicts = _collect_conflicts(
        {"candidate_facts": []},
        {
            "candidate_facts": [
                {
                    "id": "1",
                    "fact_type": "preference",
                    "value": "remote backend roles",
                    "confidence": 0.9,
                    "status": "resolved",
                },
                {
                    "id": "2",
                    "fact_type": "preference",
                    "value": "consider moving closer to campus",
                    "confidence": 0.8,
                    "status": "resolved",
                },
            ]
        },
    )

    assert conflicts == []


def test_collect_conflicts_keeps_true_preference_contradictions():
    conflicts = _collect_conflicts(
        {"candidate_facts": []},
        {
            "candidate_facts": [
                {
                    "id": "1",
                    "fact_type": "preference",
                    "value": "remote backend roles",
                    "confidence": 0.9,
                    "status": "resolved",
                },
                {
                    "id": "2",
                    "fact_type": "preference",
                    "value": "onsite backend roles",
                    "confidence": 0.8,
                    "status": "resolved",
                },
            ]
        },
    )

    assert len(conflicts) == 1
    assert conflicts[0]["fact_type"] == "preference"
    assert "onsite backend roles" in conflicts[0]["alternatives"]


def test_build_conflict_nudges_does_not_merge_compatible_preferences():
    nudges = build_conflict_nudges(
        [
            {
                "id": "1",
                "fact_type": "preference",
                "value": "remote backend roles",
                "confidence": 0.9,
                "conflict_kind": "explicit",
            },
            {
                "id": "2",
                "fact_type": "preference",
                "value": "consider moving closer to campus",
                "confidence": 0.8,
                "conflict_kind": "explicit",
            },
        ],
        only_nudgeable=False,
    )

    assert nudges == []
