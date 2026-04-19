"""Replay artifact persistence for completed Pathfinder turns."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config.settings import settings
from app.utils.ids import generate_replay_id

_REPLAY_ID_RE = re.compile(r"^replay_[a-f0-9]{12}$")


def _artifact_dir() -> Path:
    path = Path(settings.REPLAY_ARTIFACT_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_replay_artifact(
    *,
    query: str,
    done_payload: dict[str, Any],
    final_state: dict[str, Any],
    student_id: str,
    session_id: str,
) -> dict[str, Any]:
    """Build a compact replay artifact from a completed specialist turn."""
    artifact_id = generate_replay_id()
    tool_call_log = list(final_state.get("tool_call_log", []) or [])
    specialist_output = final_state.get("specialist_output", {}) or {}
    latest_ingestion_result = dict(final_state.get("latest_ingestion_result", {}) or {})
    latest_query_ingestion_result = dict(final_state.get("latest_query_ingestion_result", {}) or {})
    documents = list(latest_ingestion_result.get("documents", []) or [])
    latest_schema = dict(final_state.get("student_schema") or {})
    query_schema_after = dict(latest_query_ingestion_result.get("graph_schema_after") or {})
    if query_schema_after:
        latest_schema = query_schema_after
    for item in reversed(documents):
        if not isinstance(item, dict):
            continue
        candidate = dict((item.get("ingestion_result") or {}).get("graph_schema_after") or {})
        if candidate:
            latest_schema = candidate
            break
    return {
        "id": artifact_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "student_id": student_id,
        "session_id": session_id,
        "query": query,
        "selected_specialist": final_state.get("selected_specialist", ""),
        "method": done_payload.get("method", ""),
        "stop_reason": done_payload.get("stop_reason", ""),
        "processing_issues": list(done_payload.get("processing_issues", [])),
        "runtime_snapshot": done_payload.get("runtime_snapshot", {}),
        "dependency_status": done_payload.get("dependency_status", {}),
        "routing_scores": done_payload.get("routing_scores", {}),
        "routing_reason": done_payload.get("routing_reason", ""),
        "citations": done_payload.get("citations", []),
        "answer": final_state.get("final_answer", ""),
        "specialist_output": specialist_output,
        "tool_call_log": tool_call_log,
        "input_session_context": str(final_state.get("input_session_context", "") or ""),
        "input_long_context": str(final_state.get("input_long_context", "") or ""),
        "session_context": str(final_state.get("session_context", "") or ""),
        "long_context": str(final_state.get("long_context", "") or ""),
        "student_schema": latest_schema,
        "document_ingestion": latest_ingestion_result,
        "query_ingestion": latest_query_ingestion_result,
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
                "selected_specialist": data.get("selected_specialist", ""),
                "method": data.get("method", ""),
            }
        )
    return artifacts


def get_replay_artifact(replay_id: str) -> dict[str, Any] | None:
    """Load a single replay artifact by ID."""
    if not _REPLAY_ID_RE.match(replay_id):
        return None
    path = _artifact_dir() / f"{replay_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def delete_replay_artifacts_for_student(student_id: str) -> int:
    """Delete every replay artifact associated with one student profile."""
    deleted = 0
    for path in _artifact_dir().glob("replay_*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(data.get("student_id", "") or "") != str(student_id or ""):
            continue
        try:
            path.unlink()
            deleted += 1
        except Exception:
            continue
    return deleted


def delete_all_replay_artifacts() -> int:
    """Delete every persisted replay artifact."""
    deleted = 0
    for path in _artifact_dir().glob("replay_*.json"):
        try:
            path.unlink()
            deleted += 1
        except Exception:
            continue
    return deleted
