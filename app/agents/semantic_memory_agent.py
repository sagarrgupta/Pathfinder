"""Capability agent: hybrid semantic memory retrieval."""

from __future__ import annotations

from app.core.state import PathfinderState
from app.services.retrieval import build_memory_pack


async def semantic_memory_agent(state: PathfinderState) -> PathfinderState:
    """Build a relevance-focused memory pack."""
    pack = await build_memory_pack(
        student_id=state.get("student_id", ""),
        domain=state.get("intent", "general"),
        task_type=state.get("task_type", "general"),
        reasoning_depth=state.get("reasoning_depth", "standard"),
        query=state.get("query", ""),
        needs_web=state.get("needs_web"),
    )
    step_progress = list(state.get("step_progress", []))
    step_progress.append("Built semantic memory pack")
    sources = list(state.get("retrieval_sources", []))
    if "memory" not in sources:
        sources.append("memory")
    retrieval_summary = {
        "memory_items": len(pack.get("semantic_memory", {}).get("memory_items", [])),
        "candidate_facts": len(pack.get("semantic_memory", {}).get("candidate_facts", [])),
        "evidence": len(pack.get("semantic_memory", {}).get("evidence", [])),
        "documents": len(pack.get("documents", [])),
        "web_results": len(pack.get("web_results", [])),
        "conflicts": len(pack.get("conflicts", [])),
    }
    execution_trace = list(state.get("execution_trace", []))
    execution_trace.append({"agent": "semantic_memory_agent", "summary": retrieval_summary})
    return {
        **state,
        "memory_pack": pack,
        "semantic_memory": pack.get("semantic_memory", {}),
        "conflicts": pack.get("conflicts", []),
        "saved_recommendations": pack.get("saved_recommendations", []),
        "graph_results": pack.get("profile_context", {}),
        "retrieved_documents": pack.get("documents", []),
        "web_results": pack.get("web_results", []),
        "retrieval_sources": sources,
        "retrieval_summary": retrieval_summary,
        "execution_trace": execution_trace,
        "step_progress": step_progress,
    }
