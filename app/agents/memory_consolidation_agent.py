"""Capability agent: event-driven memory consolidation."""

from __future__ import annotations

from app.core.state import PathfinderState
from app.services.consolidation import maybe_consolidate_memory


async def memory_consolidation_agent(state: PathfinderState) -> PathfinderState:
    """Run a lightweight consolidation pass."""
    summary = await maybe_consolidate_memory(state.get("student_id", ""), "runtime")
    step_progress = list(state.get("step_progress", []))
    step_progress.append("Consolidated layered memory")
    return {**state, "consolidation_summary": summary, "step_progress": step_progress}
