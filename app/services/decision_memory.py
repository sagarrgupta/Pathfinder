"""Decision-memory persistence and continuity helpers."""

from __future__ import annotations

from typing import Any

from app.adapters.neo4j.graph_store import store_memory_item


def build_decision_record(
    *,
    query: str,
    final_state: dict[str, Any],
    done_payload: dict[str, Any],
    student_id: str,
    session_id: str,
) -> dict[str, Any] | None:
    """Build a structured decision record from a completed turn."""
    raw_payload = final_state.get("decision_payload", {}) or {}
    decision_payload = dict(raw_payload) if isinstance(raw_payload, dict) else {}
    final_answer = str(final_state.get("final_answer", "") or "").strip()
    workflow = str(final_state.get("workflow", "") or "")
    if not decision_payload and not final_answer:
        return None

    recommended_items = [
        item for item in (decision_payload.get("recommended_items", []) or [])
        if isinstance(item, dict)
    ]
    recommendation_labels = [
        str(item.get("label", "")).strip()
        for item in recommended_items
        if str(item.get("label", "")).strip()
    ][:5]
    source_refs = [
        ref for ref in (decision_payload.get("source_refs", []) or [])
        if isinstance(ref, dict)
    ][:5]
    summary = final_answer[:700] if final_answer else " ".join(recommendation_labels[:3]).strip()
    if not summary:
        return None

    return {
        "memory_type": "decision_record",
        "summary": summary,
        "source_ref": session_id,
        "confidence": float(done_payload.get("confidence", 0.0) or 0.0),
        "salience": 0.82,
        "status": "resolved",
        "time_scope": "long_term",
        "tags": [workflow or "general_guidance", str(decision_payload.get("decision_type", "decision") or "decision"), "decision"],
        "metadata": {
            "title": str(decision_payload.get("decision_type", workflow or "decision")).replace("_", " ").strip().title(),
            "workflow": workflow,
            "decision_type": str(decision_payload.get("decision_type", "") or ""),
            "query": query,
            "student_strategy": done_payload.get("student_strategy", {}),
            "student_operating_model": done_payload.get("student_operating_model", {}),
            "recommendation_labels": recommendation_labels,
            "assumptions": list(decision_payload.get("assumptions", []) or [])[:6],
            "next_best_action": str(decision_payload.get("next_best_action", "") or ""),
            "recommendation_paths": list(decision_payload.get("recommendation_paths", []) or [])[:3],
            "source_refs": source_refs,
            "session_id": session_id,
            "student_id": student_id,
            "confidence": float(done_payload.get("confidence", 0.0) or 0.0),
        },
    }


async def persist_decision_record(
    *,
    query: str,
    final_state: dict[str, Any],
    done_payload: dict[str, Any],
    student_id: str,
    session_id: str,
) -> dict[str, Any] | None:
    """Persist a structured decision record for future related conversations."""
    record = build_decision_record(
        query=query,
        final_state=final_state,
        done_payload=done_payload,
        student_id=student_id,
        session_id=session_id,
    )
    if not record:
        return None
    return await store_memory_item(
        student_id,
        record["memory_type"],
        record["summary"],
        source_ref=record["source_ref"],
        confidence=record["confidence"],
        salience=record["salience"],
        status=record["status"],
        time_scope=record["time_scope"],
        tags=record["tags"],
        metadata=record["metadata"],
    )
