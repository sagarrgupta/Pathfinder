"""Runtime session helpers for chat execution.

This module centralizes per-request runtime assembly so API routes can stay
focused on HTTP concerns while graph execution details remain reusable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.config.settings import settings
from app.core.quality import infer_quality_path, summarize_trace
from app.services.execution_registry import (
    get_active_retrieval_strategy,
    get_active_text_model,
    get_execution_registry,
)
from app.services.runtime_policy import RuntimePolicySnapshot, evaluate_runtime_preflight
from app.services.request_planner import RequestPlan, build_request_plan


@dataclass(frozen=True)
class DependencySnapshot:
    """Lightweight dependency status captured at request start."""

    neo4j: str
    llm: str
    embeddings: str
    web_search: str


@dataclass(frozen=True)
class RuntimeSnapshot:
    """Structured runtime metadata returned with each completed turn."""

    session_id: str
    student_id: str
    selected_text_model: str
    selected_retrieval_mode: str
    advisor_mode: str
    compare_mode: bool
    is_global_upload: bool
    uploaded_file_count: int
    request_plan: dict[str, Any]
    web_provider_chain: list[str]
    document_ingestors: dict[str, str]
    dependency_status: DependencySnapshot
    runtime_policy: dict[str, Any]


@dataclass(frozen=True)
class ChatRuntimeSession:
    """Fully assembled runtime session for one chat turn."""

    query: str
    session_id: str
    student_id: str
    files: list[dict[str, Any]]
    is_global_upload: bool
    topic_guard_enabled: bool
    request_plan: RequestPlan
    dependency_status: DependencySnapshot
    runtime_snapshot: RuntimeSnapshot
    runtime_policy: RuntimePolicySnapshot
    advisor_mode: str

    def build_initial_state(self) -> dict[str, Any]:
        """Construct the initial LangGraph state for a fresh turn."""
        return {
            "messages": [("human", self.query)],
            "query": self.query,
            "files": self.files,
            "session_id": self.session_id,
            "student_id": self.student_id,
            "is_global_upload": self.is_global_upload,
            "topic_guard_enabled": self.topic_guard_enabled,
            "request_plan": self.request_plan.as_dict(),
            "runtime_policy": self.runtime_policy.as_dict(),
            "advisor_mode": self.advisor_mode,
            "step_progress": [],
            "citations": [],
            "plan": [],
            "next_node": "",
            "intent": "",
            "selected_specialist": "",
            "routing_scores": {},
            "routing_reason": "",
            "missing_info": [],
            "session_summary": {},
            "durable_profile_facts": {},
            "workflow": "",
            "student_strategy": {},
            "student_operating_model": {},
            "recommendation_outcome_profile": {},
            "decision_continuity": {},
            "target_entity": {},
            "source_policy": {},
            "task_graph": [],
            "working_memory": {},
            "compacted_session": {},
            "session_memory": {},
            "dependency_status": asdict(self.dependency_status),
            "recovery_events": [],
            "blocked_reasons": [],
            "stop_reason": "",
            "trace_summary": {},
            "short_memory_policy": {},
            "draft_answer": "",
            "final_answer": "",
            "is_blocked": False,
            "block_reason": "",
            "confidence_score": 0.0,
            "is_grounded": True,
            "profile_updates": [],
            "extracted_entities": [],
            "document_roles": [],
            "transcript_states": [],
            "targeted_web_questions": [],
            "retrieved_documents": [],
            "web_results": [],
            "profile_data": {},
            "semantic_memory": {},
            "memory_pack": {},
            "evidence_pack": {},
            "latest_ingestion_result": {},
            "conflicts": [],
            "evidence_records": [],
            "decision_payload": {},
            "tool_call_log": [],
            "specialist_output": {},
        }

    def build_graph_config(self) -> dict[str, Any]:
        """Build graph config for this turn."""
        return {
            "configurable": {"thread_id": f"{self.student_id}:{self.session_id}"},
            "recursion_limit": 15,
        }

    def build_done_payload(self, final_state: dict[str, Any]) -> dict[str, Any]:
        """Build the final SSE payload for a completed turn."""
        evidence_pack = final_state.get("evidence_pack", {}) or {}
        return {
            "session_id": self.session_id,
            "student_id": self.student_id,
            "confidence": final_state.get("confidence_score", 0.5),
            "citations": final_state.get("citations", []),
            "method": determine_method(final_state),
            "quality_path": infer_quality_path(final_state),
            "trace_summary": final_state.get("trace_summary") or summarize_trace(final_state),
            "blocked_reasons": final_state.get("blocked_reasons", []),
            "dependency_status": final_state.get("dependency_status", asdict(self.dependency_status)),
            "recovery_events": final_state.get("recovery_events", []),
            "runtime_policy": final_state.get("runtime_policy", self.runtime_policy.as_dict()),
            "stop_reason": final_state.get("stop_reason", ""),
            "student_strategy": final_state.get("student_strategy", {}),
            "student_operating_model": final_state.get("student_operating_model", {}),
            "recommendation_outcome_profile": final_state.get("recommendation_outcome_profile", {}),
            "decision_continuity": final_state.get("decision_continuity", {}),
            "selected_specialist": final_state.get("selected_specialist", ""),
            "routing_scores": final_state.get("routing_scores", {}),
            "routing_reason": final_state.get("routing_reason", ""),
            "retrieval_summary": evidence_pack.get("retrieval_summary", {}),
            "retrieval_trace": evidence_pack.get("retrieval_trace", []),
            "retrieval_diagnostics": evidence_pack.get("retrieval_diagnostics", {}),
            "retrieval_recovery_events": evidence_pack.get("recovery_events", []),
            "document_roles": final_state.get("document_roles", []),
            "transcript_states": final_state.get("transcript_states", []),
            "targeted_web_questions": final_state.get("targeted_web_questions", []),
            "session_compaction": (final_state.get("compacted_session", {}) or {}).get("conversation_digest", {}),
            "session_memory": final_state.get("session_memory", {}),
            "runtime_snapshot": asdict(self.runtime_snapshot),
        }


async def build_chat_runtime_session(
    *,
    query: str,
    session_id: str,
    student_id: str,
    files: list[dict[str, Any]],
    is_global_upload: bool,
    topic_guard_enabled: bool,
    advisor_mode: str = "adaptive",
) -> ChatRuntimeSession:
    """Assemble a runtime session for one chat request."""
    dependency_status = await get_dependency_status()
    registry = get_execution_registry()
    request_plan = build_request_plan(query, files, advisor_mode=advisor_mode)
    runtime_policy = evaluate_runtime_preflight(
        query=query,
        files=files,
        is_global_upload=is_global_upload,
        request_plan=request_plan.as_dict(),
        dependency_status=dependency_status,
        selected_retrieval_mode=get_active_retrieval_strategy(),
        compare_mode=False,
    )
    snapshot = RuntimeSnapshot(
        session_id=session_id,
        student_id=student_id,
        selected_text_model=get_active_text_model(),
        selected_retrieval_mode=get_active_retrieval_strategy(),
        advisor_mode=request_plan.advisor_mode,
        compare_mode=False,
        is_global_upload=is_global_upload,
        uploaded_file_count=len(files),
        request_plan=request_plan.as_dict(),
        web_provider_chain=list(registry.web_providers),
        document_ingestors=dict(registry.document_ingestors),
        dependency_status=DependencySnapshot(**dependency_status),
        runtime_policy=runtime_policy.as_dict(),
    )
    return ChatRuntimeSession(
        query=query,
        session_id=session_id,
        student_id=student_id,
        files=files,
        is_global_upload=is_global_upload,
        topic_guard_enabled=topic_guard_enabled,
        request_plan=request_plan,
        dependency_status=DependencySnapshot(**dependency_status),
        runtime_snapshot=snapshot,
        runtime_policy=runtime_policy,
        advisor_mode=request_plan.advisor_mode,
    )


def determine_method(state: dict[str, Any]) -> str:
    """Determine which retrieval methods were used."""
    methods = []
    if state.get("retrieved_documents"):
        methods.append("rag")
    if state.get("profile_data", {}).get("courses"):
        methods.append("graph")
    if state.get("web_results"):
        methods.append("web")
    return "+".join(methods) if methods else "direct"


async def get_dependency_status() -> dict[str, str]:
    """Check live dependency health for the current turn."""
    neo4j_status = "unknown"
    llm_status = "unknown"
    embeddings_status = "unknown"

    try:
        from app.adapters.neo4j.graph_store import get_driver

        driver = await get_driver()
        async with driver.session() as session:
            await session.run("RETURN 1")
        neo4j_status = "connected"
    except Exception:
        neo4j_status = "disconnected"

    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.LLM_BASE_URL.replace('/v1', '')}/v1/models")
            if resp.status_code == 200:
                payload = resp.json() if resp.content else {}
                models = payload.get("data", []) if isinstance(payload, dict) else []
                llm_status = "connected" if models else "no_model_loaded"
            else:
                llm_status = "error"
    except Exception:
        llm_status = "disconnected"

    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.OLLAMA_URL}/api/tags")
            embeddings_status = "connected" if resp.status_code == 200 else "error"
    except Exception:
        embeddings_status = "disconnected"

    web_search_status = "configured" if any(
        [
            settings.TAVILY_API_KEY,
            settings.GOOGLE_CSE_API_KEY,
            settings.BRAVE_API_KEY,
        ]
    ) else "fallback_only"

    return {
        "neo4j": neo4j_status,
        "llm": llm_status,
        "embeddings": embeddings_status,
        "web_search": web_search_status,
    }
