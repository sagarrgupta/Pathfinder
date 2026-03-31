"""Capability agent: document evidence retrieval/processing."""

from __future__ import annotations

from app.adapters.neo4j.graph_store import get_full_profile
from app.agents.doc_analyst import doc_analyst
from app.core.state import PathfinderState


async def document_evidence_agent(state: PathfinderState) -> PathfinderState:
    """Process uploaded docs when present, otherwise keep retrieved evidence as-is."""
    if state.get("files"):
        result = await doc_analyst(state)
        step_progress = list(result.get("step_progress", []))
        step_progress.append("Document evidence prepared")
        sources = list(result.get("retrieval_sources", state.get("retrieval_sources", [])))
        if "documents" not in sources:
            sources.append("documents")
        result["profile_data"] = await get_full_profile(state.get("student_id", ""))
        result["retrieval_sources"] = sources
        result["step_progress"] = step_progress
        return result
    step_progress = list(state.get("step_progress", []))
    step_progress.append("Reused existing document evidence")
    sources = list(state.get("retrieval_sources", []))
    if state.get("retrieved_documents") and "documents" not in sources:
        sources.append("documents")
    return {**state, "retrieval_sources": sources, "step_progress": step_progress}
