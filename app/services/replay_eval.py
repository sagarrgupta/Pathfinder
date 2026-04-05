"""Lightweight replay artifact evaluation for regression checks."""

from __future__ import annotations

from typing import Any

from app.services.replay_store import get_replay_artifact, list_replay_artifacts


def evaluate_replay_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    """Score a replay artifact using lightweight completeness and grounding heuristics."""
    answer = str(artifact.get("answer", "") or "").strip()
    citations = list(artifact.get("citations", []) or [])
    retrieval_trace = list(artifact.get("retrieval_trace", []) or [])
    retrieval_diagnostics = dict(artifact.get("retrieval_diagnostics", {}) or {})
    blocked_reasons = list(artifact.get("blocked_reasons", []) or [])
    evidence_overview = dict(artifact.get("evidence_overview", {}) or {})
    decision_payload = dict(artifact.get("decision_payload", {}) or {})
    dependency_status = dict(artifact.get("dependency_status", {}) or {})

    issues: list[str] = []
    checks: dict[str, bool] = {}

    answer_present = bool(answer)
    checks["answer_present"] = answer_present
    if not answer_present:
        issues.append("Missing final answer.")

    has_grounding = bool(citations) or bool(retrieval_trace) or sum(
        int(evidence_overview.get(key, 0) or 0)
        for key in ("document_count", "web_count", "evidence_record_count", "profile_fact_count")
    ) > 0
    checks["has_grounding"] = has_grounding
    if not has_grounding:
        issues.append("No citations, retrieval trace, or evidence counts were saved.")

    dependencies_ready = all(status == "connected" for status in dependency_status.values()) if dependency_status else True
    checks["dependencies_ready"] = dependencies_ready
    if dependency_status and not dependencies_ready:
        issues.append("One or more runtime dependencies were unavailable during the turn.")

    has_recommendation_shape = bool(decision_payload.get("decision_type")) or bool(
        decision_payload.get("recommendation_paths")
    )
    checks["has_recommendation_shape"] = has_recommendation_shape
    if not has_recommendation_shape:
        issues.append("Decision payload is missing recommendation structure.")

    no_blockers = not blocked_reasons
    checks["no_blockers"] = no_blockers
    if blocked_reasons:
        issues.append("Turn completed with explicit blockers.")

    confidence = float(artifact.get("confidence", 0.0) or 0.0)
    confidence_aligned = not answer_present or confidence > 0.0
    checks["confidence_aligned"] = confidence_aligned
    if answer_present and confidence <= 0.0:
        issues.append("Answer exists but confidence is missing or zero.")

    evidence_quality = dict(retrieval_diagnostics.get("evidence_quality", {}) or {})
    quality_score_value = float(evidence_quality.get("overall_quality", 0.0) or 0.0)
    strong_evidence_quality = quality_score_value >= 0.42 if evidence_quality else True
    checks["strong_evidence_quality"] = strong_evidence_quality
    if evidence_quality and not strong_evidence_quality:
        issues.append("Retrieved evidence quality was weak for this turn.")

    score_components = {
        "answer": 0.25 if answer_present else 0.0,
        "grounding": 0.25 if has_grounding else 0.0,
        "dependencies": 0.15 if dependencies_ready else 0.0,
        "decision_shape": 0.2 if has_recommendation_shape else 0.0,
        "no_blockers": 0.1 if no_blockers else 0.0,
        "confidence": 0.03 if confidence_aligned else 0.0,
        "evidence_quality": 0.02 if strong_evidence_quality else 0.0,
    }
    score = round(sum(score_components.values()), 4)

    status = "pass"
    if score < 0.55:
        status = "fail"
    elif score < 0.8:
        status = "warn"

    return {
        "replay_id": artifact.get("id", ""),
        "query": artifact.get("query", ""),
        "workflow": artifact.get("workflow", ""),
        "method": artifact.get("method", ""),
        "score": score,
        "status": status,
        "checks": checks,
        "issues": issues,
        "metrics": {
            "citation_count": len(citations),
            "retrieval_trace_count": len(retrieval_trace),
            "blocked_reason_count": len(blocked_reasons),
            "document_count": int(evidence_overview.get("document_count", 0) or 0),
            "web_count": int(evidence_overview.get("web_count", 0) or 0),
            "evidence_record_count": int(evidence_overview.get("evidence_record_count", 0) or 0),
            "profile_fact_count": int(evidence_overview.get("profile_fact_count", 0) or 0),
            "evidence_quality_percent": int(round(quality_score_value * 100)),
        },
        "score_components": score_components,
    }


def evaluate_replay_by_id(replay_id: str) -> dict[str, Any] | None:
    """Load and evaluate one replay artifact."""
    artifact = get_replay_artifact(replay_id)
    if artifact is None:
        return None
    return evaluate_replay_artifact(artifact)


def evaluate_recent_replays(limit: int = 25, student_id: str | None = None) -> dict[str, Any]:
    """Evaluate a batch of recent replay artifacts."""
    artifacts = list_replay_artifacts(limit=limit)
    if student_id:
        artifacts = [artifact for artifact in artifacts if artifact.get("student_id") == student_id]

    evaluations: list[dict[str, Any]] = []
    for item in artifacts:
        replay_id = str(item.get("id", "") or "")
        if not replay_id:
            continue
        evaluation = evaluate_replay_by_id(replay_id)
        if evaluation:
            evaluations.append(evaluation)

    total = len(evaluations)
    passed = sum(1 for item in evaluations if item.get("status") == "pass")
    warned = sum(1 for item in evaluations if item.get("status") == "warn")
    failed = sum(1 for item in evaluations if item.get("status") == "fail")
    average_score = round(sum(float(item.get("score", 0.0) or 0.0) for item in evaluations) / max(total, 1), 4)

    return {
        "summary": {
            "total": total,
            "passed": passed,
            "warned": warned,
            "failed": failed,
            "average_score": average_score,
            "student_id": student_id or "",
        },
        "evaluations": evaluations,
    }
