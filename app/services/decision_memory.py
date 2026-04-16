# """Decision-memory persistence and continuity helpers."""

# from __future__ import annotations

# from typing import Any

# from app.adapters.neo4j.graph_store import store_memory_item


# def build_decision_record(
#     *,
#     query: str,
#     final_state: dict[str, Any],
#     done_payload: dict[str, Any],
#     student_id: str,
#     session_id: str,
# ) -> dict[str, Any] | None:
#     """Build a compact specialist-turn memory record from a completed turn."""
#     final_answer = str(final_state.get("final_answer", "") or "").strip()
#     selected_specialist = str(final_state.get("selected_specialist", "") or "")
#     specialist_output = final_state.get("specialist_output", {}) or {}
#     provenance = list(specialist_output.get("provenance", []) or []) if isinstance(specialist_output, dict) else []
#     citations = list(done_payload.get("citations", []) or [])
#     if not final_answer:
#         return None

#     summary = final_answer[:700]
#     tool_names = [
#         str(item.get("tool", "")).strip()
#         for item in (final_state.get("tool_call_log", []) or [])
#         if isinstance(item, dict) and str(item.get("tool", "")).strip()
#     ][:8]
#     memory_patch = specialist_output.get("memory_patch") if isinstance(specialist_output, dict) else None

#     return {
#         "memory_type": "decision_record",
#         "summary": summary,
#         "source_ref": session_id,
#         "confidence": float(done_payload.get("confidence", 0.0) or 0.0),
#         "salience": 0.82,
#         "status": "resolved",
#         "time_scope": "long_term",
#         "tags": [selected_specialist or "general", "specialist_turn", "decision"],
#         "metadata": {
#             "title": f"{(selected_specialist or 'general').replace('_', ' ').title()} turn",
#             "selected_specialist": selected_specialist,
#             "query": query,
#             "tool_names": tool_names,
#             "provenance": provenance[:8],
#             "citation_count": len(citations),
#             "memory_patch": memory_patch,
#             "session_id": session_id,
#             "student_id": student_id,
#             "confidence": float(done_payload.get("confidence", 0.0) or 0.0),
#         },
#     }


# async def persist_decision_record(
#     *,
#     query: str,
#     final_state: dict[str, Any],
#     done_payload: dict[str, Any],
#     student_id: str,
#     session_id: str,
# ) -> dict[str, Any] | None:
#     """Persist a structured decision record for future related conversations."""
#     record = build_decision_record(
#         query=query,
#         final_state=final_state,
#         done_payload=done_payload,
#         student_id=student_id,
#         session_id=session_id,
#     )
#     if not record:
#         return None
#     return await store_memory_item(
#         student_id,
#         record["memory_type"],
#         record["summary"],
#         source_ref=record["source_ref"],
#         confidence=record["confidence"],
#         salience=record["salience"],
#         status=record["status"],
#         time_scope=record["time_scope"],
#         tags=record["tags"],
#         metadata=record["metadata"],
#     )
