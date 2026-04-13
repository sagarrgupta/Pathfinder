"""Lightweight replay artifact evaluation for regression checks."""

from __future__ import annotations

from typing import Any

from app.services.replay_store import get_replay_artifact, list_replay_artifacts


def evaluate_replay_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    """Score a replay artifact using lightweight specialist-turn heuristics."""
    answer = str(artifact.get("answer", "") or "").strip()
    citations = list(artifact.get("citations", []) or [])
    tool_call_log = list(artifact.get("tool_call_log", []) or [])
    specialist_output = artifact.get("specialist_output", {}) or {}
    context_overview = artifact.get("context_overview", {}) or {}
    raw_dependency_status = artifact.get("dependency_status", {}) or {}
    dependency_status = dict(raw_dependency_status) if isinstance(raw_dependency_status, dict) else {}
    selected_specialist = str(artifact.get("selected_specialist", "") or "")

    issues: list[str] = []
    checks: dict[str, bool] = {}

    answer_present = bool(answer)
    checks["answer_present"] = answer_present
    if not answer_present:
        issues.append("Missing final answer.")

    has_grounding = bool(citations) or any(
        isinstance(item, dict) and item.get("status") == "ok"
        for item in tool_call_log
    )
    checks["has_grounding"] = has_grounding
    if not has_grounding:
        issues.append("No citations or successful tool calls were saved.")

    dependencies_ready = all(status == "connected" for status in dependency_status.values()) if dependency_status else True
    checks["dependencies_ready"] = dependencies_ready
    if dependency_status and not dependencies_ready:
        issues.append("One or more runtime dependencies were unavailable during the turn.")

    specialist_selected = bool(selected_specialist)
    checks["specialist_selected"] = specialist_selected
    if not specialist_selected:
        issues.append("Replay artifact is missing the selected specialist.")

    output_shaped = isinstance(specialist_output, dict) and bool(str(specialist_output.get("message", "") or "").strip())
    checks["output_shaped"] = output_shaped
    if not output_shaped:
        issues.append("Structured specialist output is missing the final message.")

    confidence = float(artifact.get("confidence", 0.0) or 0.0)
    confidence_aligned = not answer_present or confidence > 0.0
    checks["confidence_aligned"] = confidence_aligned
    if answer_present and confidence <= 0.0:
        issues.append("Answer exists but confidence is missing or zero.")

    context_present = sum(int(context_overview.get(key, 0) or 0) for key in (
        "document_result_count",
        "web_result_count",
        "memory_bucket_count",
    )) > 0 or bool(tool_call_log)
    checks["context_present"] = context_present
    if not context_present:
        issues.append("Replay artifact is missing retrieved context and tool activity.")

    score_components = {
        "answer": 0.25 if answer_present else 0.0,
        "grounding": 0.25 if has_grounding else 0.0,
        "dependencies": 0.15 if dependencies_ready else 0.0,
        "specialist": 0.15 if specialist_selected else 0.0,
        "output_shape": 0.1 if output_shaped else 0.0,
        "context": 0.07 if context_present else 0.0,
        "confidence": 0.03 if confidence_aligned else 0.0,
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
        "selected_specialist": selected_specialist,
        "method": artifact.get("method", ""),
        "score": score,
        "status": status,
        "checks": checks,
        "issues": issues,
        "metrics": {
            "citation_count": len(citations),
            "tool_call_count": len(tool_call_log),
            "document_result_count": int(context_overview.get("document_result_count", 0) or 0),
            "web_result_count": int(context_overview.get("web_result_count", 0) or 0),
            "memory_bucket_count": int(context_overview.get("memory_bucket_count", 0) or 0),
            "document_role_count": int(context_overview.get("document_role_count", 0) or 0),
            "transcript_state_count": int(context_overview.get("transcript_state_count", 0) or 0),
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
