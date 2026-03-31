"""Capability agent: write reusable memory from the current turn."""

from __future__ import annotations

from app.core.state import PathfinderState
from app.services.consolidation import maybe_consolidate_memory
from app.services.memory_ingestion import ingest_memory


async def memory_writer_agent(state: PathfinderState) -> PathfinderState:
    """Extract reusable long-term memory from the current turn."""
    query = state.get("query", "").strip()
    if not query:
        return state
    latest_ingestion = state.get("latest_ingestion_result", {}) or {}
    step_progress = list(state.get("step_progress", []))
    if (
        state.get("intent") == "profile"
        and state.get("task_type") == "update"
        and latest_ingestion.get("profile_update_error")
    ):
        step_progress.append("Skipped memory writeback because the linked page could not be read")
        return {
            **state,
            "step_progress": step_progress,
        }
    ingestion = await ingest_memory(
        student_id=state.get("student_id", ""),
        source_type="chat_turn",
        content=query,
        source_ref=state.get("session_id"),
        session_id=state.get("session_id"),
        metadata={"intent": state.get("intent"), "task_type": state.get("task_type")},
    )
    consolidation_summary = state.get("consolidation_summary", {})
    if ingestion.get("consolidation_needed"):
        consolidation_summary = await maybe_consolidate_memory(
            state.get("student_id", ""), "chat_turn"
        )
    wrote_memory = bool(
        ingestion.get("student_updates")
        or ingestion.get("candidate_facts")
        or ingestion.get("promoted_entities")
    )
    step_progress.append(
        "Saved reusable memory from this turn" if wrote_memory else "No reusable memory was saved from this turn"
    )
    return {
        **state,
        "consolidation_summary": consolidation_summary,
        "step_progress": step_progress,
    }
