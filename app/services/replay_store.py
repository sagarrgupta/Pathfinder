"""Replay artifact persistence for completed Pathfinder turns."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config.settings import settings
from app.utils.ids import generate_replay_id


def _artifact_dir() -> Path:
    path = Path(settings.REPLAY_ARTIFACT_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_replay_artifact(
    *,
    query: str,
    done_payload: dict[str, Any],
    final_state: dict[str, Any],
    student_id: str,
    session_id: str,
) -> dict[str, Any]:
    """Build a compact replay artifact from a completed chat turn."""
    evidence_pack = final_state.get("evidence_pack", {}) or {}
    raw_decision_payload = final_state.get("decision_payload", {}) or {}
    decision_payload = raw_decision_payload if isinstance(raw_decision_payload, dict) else {}
    artifact_id = generate_replay_id()
    return {
        "id": artifact_id,
        "created_at": _utc_now(),
        "student_id": student_id,
        "session_id": session_id,
        "query": query,
        "workflow": final_state.get("workflow", ""),
        "intent": final_state.get("intent", ""),
        "method": done_payload.get("method", ""),
        "quality_path": done_payload.get("quality_path", ""),
        "confidence": done_payload.get("confidence", 0.0),
        "stop_reason": done_payload.get("stop_reason", ""),
        "blocked_reasons": list(done_payload.get("blocked_reasons", [])),
        "recovery_events": list(done_payload.get("recovery_events", [])),
        "student_strategy": done_payload.get("student_strategy", {}),
        "student_operating_model": done_payload.get("student_operating_model", {}),
        "recommendation_outcome_profile": done_payload.get("recommendation_outcome_profile", {}),
        "decision_continuity": done_payload.get("decision_continuity", {}),
        "runtime_snapshot": done_payload.get("runtime_snapshot", {}),
        "dependency_status": done_payload.get("dependency_status", {}),
        "retrieval_summary": done_payload.get("retrieval_summary", {}),
        "retrieval_trace": done_payload.get("retrieval_trace", []),
        "retrieval_diagnostics": done_payload.get("retrieval_diagnostics", {}),
        "retrieval_recovery_events": done_payload.get("retrieval_recovery_events", []),
        "session_compaction": done_payload.get("session_compaction", {}),
        "session_memory": done_payload.get("session_memory", {}),
        "trace_summary": done_payload.get("trace_summary", {}),
        "citations": done_payload.get("citations", []),
        "answer": final_state.get("final_answer", ""),
        "decision_payload": decision_payload,
        "evidence_overview": {
            "document_count": len(evidence_pack.get("document_records", []) or []),
            "web_count": len(evidence_pack.get("web_records", []) or []),
            "evidence_record_count": len(evidence_pack.get("evidence_records", []) or []),
            "profile_fact_count": len(evidence_pack.get("profile_facts", []) or []),
        },
    }


def save_replay_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    """Persist a replay artifact to disk as JSON."""
    artifact_id = str(artifact.get("id") or generate_replay_id())
    path = _artifact_dir() / f"{artifact_id}.json"
    payload = {**artifact, "id": artifact_id}
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return payload


def list_replay_artifacts(limit: int = 50) -> list[dict[str, Any]]:
    """List replay artifacts in reverse chronological order."""
    artifacts: list[dict[str, Any]] = []
    for path in sorted(_artifact_dir().glob("replay_*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        artifacts.append(
            {
                "id": data.get("id", path.stem),
                "created_at": data.get("created_at", ""),
                "student_id": data.get("student_id", ""),
                "session_id": data.get("session_id", ""),
                "query": data.get("query", ""),
                "workflow": data.get("workflow", ""),
                "method": data.get("method", ""),
                "quality_path": data.get("quality_path", ""),
                "confidence": data.get("confidence", 0.0),
            }
        )
    return artifacts


def get_replay_artifact(replay_id: str) -> dict[str, Any] | None:
    """Load a single replay artifact by ID."""
    path = _artifact_dir() / f"{replay_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
