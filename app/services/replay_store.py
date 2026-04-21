"""Writes a JSON "replay" to disk for every completed turn.

A replay captures everything that happened during one chat turn: the
query, routing decision, every tool call with its input and output, the
final answer, citations, processing issues, and snapshots of session /
long context. The API layer creates one at the end of each turn; the
`/replays` endpoints read them back for debugging and audits.

Files live under `settings.REPLAY_ARTIFACT_DIR` and are named
`replay_<hex-id>.json`. They are append-only in practice: we never rewrite
an existing file, only add new ones or delete on explicit cleanup.

The only "business logic" here is picking the best graph schema snapshot
to attach — preferring the most recent document ingestion's
post-ingestion schema, then the chat-message ingestion's, then whatever
was on the state at the end of the turn.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config.settings import settings
from app.utils.ids import generate_replay_id

# Replay ids are 12-hex-char-suffixed to keep filenames short and to make
# validation from URLs trivial.
_REPLAY_ID_RE = re.compile(r"^replay_[a-f0-9]{12}$")


def _artifact_dir() -> Path:
    """Return the on-disk replay folder, creating it if missing."""
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
    """Fold final state + SSE `done` payload into one replay-ready dict.

    `done_payload` is the JSON the API streams to the client at turn end
    (method, stop_reason, routing, citations, etc.); `final_state` is the
    full LangGraph state after every node ran. We merge them so a single
    saved file has both the user-visible summary and the raw evidence.
    """
    artifact_id = generate_replay_id()
    tool_call_log = list(final_state.get("tool_call_log", []) or [])
    specialist_output = final_state.get("specialist_output", {}) or {}
    latest_ingestion_result = dict(final_state.get("latest_ingestion_result", {}) or {})
    latest_query_ingestion_result = dict(final_state.get("latest_query_ingestion_result", {}) or {})
    documents = list(latest_ingestion_result.get("documents", []) or [])

    # Pick the freshest schema snapshot we have access to. Priority:
    #   1. The schema after document ingestion (most recent, richest).
    #   2. The schema after chat-message ingestion.
    #   3. Whatever was on the state when the turn ended.
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
    """Write one artifact to `<artifact_id>.json`, returning the payload.

    We always re-stamp the id so callers can hand in a partial artifact
    (without an id) and still get a valid on-disk record.
    """
    artifact_id = str(artifact.get("id") or generate_replay_id())
    path = _artifact_dir() / f"{artifact_id}.json"
    payload = {**artifact, "id": artifact_id}
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return payload


def list_replay_artifacts(limit: int = 50) -> list[dict[str, Any]]:
    """Return a lightweight index of recent replays for the UI list view.

    Only enough fields to render a row — full payloads are loaded on
    demand via `get_replay_artifact`. Sorted by file mtime so the most
    recent turn appears first.
    """
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
    """Load one replay by id. Returns None for unknown / malformed ids.

    The id regex check is important: the id comes from URL path params, so
    this stops directory-traversal attempts like `../../etc/passwd`.
    """
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
    """Purge every replay file that belongs to one student.

    Called when an admin deletes a student profile — we don't want stale
    replays lingering on disk referencing a student that no longer exists.
    """
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
    """Nuke the entire replay folder contents (admin reset path)."""
    deleted = 0
    for path in _artifact_dir().glob("replay_*.json"):
        try:
            path.unlink()
            deleted += 1
        except Exception:
            continue
    return deleted
