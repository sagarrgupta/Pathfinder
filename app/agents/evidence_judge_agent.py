"""Capability agent: evidence filtering and reranking."""

from __future__ import annotations

from app.core.state import PathfinderState


def _weighted_score(item: dict) -> float:
    return (
        float(item.get("score", item.get("match_score", 0.0))) * 0.55
        + float(item.get("confidence", 0.0)) * 0.25
        + float(item.get("salience", 0.0)) * 0.20
    )


def _dedupe(items: list[dict], key: str) -> list[dict]:
    seen = set()
    result = []
    for item in items:
        token = str(item.get(key, "")).strip().lower()
        if token and token in seen:
            continue
        if token:
            seen.add(token)
        result.append(item)
    return result


async def evidence_judge_agent(state: PathfinderState) -> PathfinderState:
    """Prune and rerank retrieved evidence before reasoning."""
    documents = _dedupe(
        sorted(state.get("retrieved_documents", []), key=_weighted_score, reverse=True),
        "id",
    )[:5]
    web_results = _dedupe(
        sorted(state.get("web_results", []), key=_weighted_score, reverse=True),
        "url",
    )[:5]
    semantic = state.get("semantic_memory", {})
    semantic["memory_items"] = _dedupe(
        sorted(semantic.get("memory_items", []), key=_weighted_score, reverse=True),
        "id",
    )[:6]
    semantic["candidate_facts"] = _dedupe(
        sorted(semantic.get("candidate_facts", []), key=_weighted_score, reverse=True),
        "id",
    )[:6]
    semantic["evidence"] = _dedupe(
        sorted(semantic.get("evidence", []), key=_weighted_score, reverse=True),
        "id",
    )[:4]
    rationale = list(state.get("answer_rationale", []))
    rationale.append(
        f"Evidence judge kept {len(documents)} docs, {len(web_results)} web results, "
        f"{len(semantic['candidate_facts'])} candidate facts after weighted reranking"
    )
    step_progress = list(state.get("step_progress", []))
    step_progress.append("Ranked and filtered evidence")
    execution_trace = list(state.get("execution_trace", []))
    execution_trace.append(
        {
            "agent": "evidence_judge_agent",
            "documents": len(documents),
            "web_results": len(web_results),
            "candidate_facts": len(semantic["candidate_facts"]),
        }
    )
    return {
        **state,
        "retrieved_documents": documents,
        "web_results": web_results,
        "semantic_memory": semantic,
        "answer_rationale": rationale,
        "execution_trace": execution_trace,
        "step_progress": step_progress,
    }
