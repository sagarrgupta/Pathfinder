"""Runtime session helpers for chat execution.

This module centralizes per-request runtime assembly so API routes can stay
focused on HTTP concerns while graph execution details remain reusable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.config.settings import settings
from app.core.quality import infer_quality_path
from app.services.execution_registry import (
    get_active_retrieval_strategy,
    get_active_text_model,
    get_execution_registry,
)


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
    reasoning: str
    selected_retrieval_mode: str
    compare_mode: bool
    uploaded_file_count: int
    request_plan: dict[str, Any]
    web_provider_chain: list[str]
    document_ingestors: dict[str, str]
    dependency_status: DependencySnapshot


@dataclass(frozen=True)
class ChatRuntimeSession:
    """Fully assembled runtime session for one chat turn."""

    query: str
    session_id: str
    student_id: str
    files: list[dict[str, Any]]
    topic_guard_enabled: bool
    dependency_status: DependencySnapshot
    runtime_snapshot: RuntimeSnapshot
    reasoning: str

    def build_initial_state(self) -> dict[str, Any]:
        """Construct the initial LangGraph state for a fresh turn."""
        return {
            "messages": [("human", self.query)],
            "query": self.query,
            "files": self.files,
            "session_id": self.session_id,
            "student_id": self.student_id,
            "topic_guard_enabled": self.topic_guard_enabled,
            "request_plan": {
                "reasoning": self.reasoning,
                "has_files": bool(self.files),
                "has_url": ("http://" in self.query.lower() or "https://" in self.query.lower()),
                "reasons": [],
            },
            "reasoning": self.reasoning,
            "step_progress": [],
            "citations": [],
            "next_node": "",
            "selected_specialist": "",
            "routing_scores": {},
            "routing_reason": "",
            "session_summary": {},
            "durable_profile_facts": {},
            "dependency_status": asdict(self.dependency_status),
            "recovery_events": [],
            "stop_reason": "",
            "draft_answer": "",
            "final_answer": "",
            "is_blocked": False,
            "block_reason": "",
            "confidence_score": 0.0,
            "is_grounded": True,
            "extracted_entities": [],
            "document_roles": [],
            "transcript_states": [],
            "retrieved_documents": [],
            "web_results": [],
            "profile_data": {},
            "semantic_memory": {},
            "tool_call_log": [],
            "specialist_output": {},
            "long_context_payload": {},
        }

    def build_graph_config(self) -> dict[str, Any]:
        """Build graph config for this turn."""
        return {
            "configurable": {"thread_id": f"{self.student_id}:{self.session_id}"},
            "recursion_limit": 15,
        }

    def build_done_payload(self, final_state: dict[str, Any]) -> dict[str, Any]:
        """Build the final SSE payload for a completed turn."""
        return {
            "session_id": self.session_id,
            "student_id": self.student_id,
            "confidence": final_state.get("confidence_score", 0.5),
            "citations": final_state.get("citations", []),
            "method": determine_method(final_state),
            "quality_path": infer_quality_path(final_state),
            "dependency_status": final_state.get("dependency_status", asdict(self.dependency_status)),
            "recovery_events": final_state.get("recovery_events", []),
            "stop_reason": final_state.get("stop_reason", ""),
            "selected_specialist": final_state.get("selected_specialist", ""),
            "routing_scores": final_state.get("routing_scores", {}),
            "routing_reason": final_state.get("routing_reason", ""),
            "document_roles": final_state.get("document_roles", []),
            "transcript_states": final_state.get("transcript_states", []),
            "tool_call_log": final_state.get("tool_call_log", []),
            "specialist_output": final_state.get("specialist_output", {}),
            "long_context_payload": final_state.get("long_context_payload", {}),
            "runtime_snapshot": asdict(self.runtime_snapshot),
        }


async def build_chat_runtime_session(
    *,
    query: str,
    session_id: str,
    student_id: str,
    files: list[dict[str, Any]],
    topic_guard_enabled: bool,
    reasoning: str = "medium",
) -> ChatRuntimeSession:
    """Assemble a runtime session for one chat request."""
    dependency_status = await get_dependency_status()
    registry = get_execution_registry()
    normalized_reasoning = str(reasoning or "medium").strip().lower() or "medium"
    request_plan = {
        "reasoning": normalized_reasoning,
        "has_files": bool(files),
        "has_url": ("http://" in query.lower() or "https://" in query.lower()),
        "reasons": [],
    }
    snapshot = RuntimeSnapshot(
        session_id=session_id,
        student_id=student_id,
        selected_text_model=get_active_text_model(),
        reasoning=normalized_reasoning,
        selected_retrieval_mode=get_active_retrieval_strategy(),
        compare_mode=False,
        uploaded_file_count=len(files),
        request_plan=request_plan,
        web_provider_chain=list(registry.web_providers),
        document_ingestors=dict(registry.document_ingestors),
        dependency_status=DependencySnapshot(**dependency_status),
    )
    return ChatRuntimeSession(
        query=query,
        session_id=session_id,
        student_id=student_id,
        files=files,
        topic_guard_enabled=topic_guard_enabled,
        dependency_status=DependencySnapshot(**dependency_status),
        runtime_snapshot=snapshot,
        reasoning=normalized_reasoning,
    )


def determine_method(state: dict[str, Any]) -> str:
    """Determine which retrieval methods were used."""
    tool_call_log = list(state.get("tool_call_log", []) or [])
    successful_tools = [
        str(item.get("tool", "") or "")
        for item in tool_call_log
        if isinstance(item, dict) and item.get("status") == "ok"
    ]
    if not successful_tools:
        return "direct"

    methods = []
    if any(name in {"search_documents_semantic", "fetch_document_snippet", "list_document_groups"} for name in successful_tools):
        methods.append("rag")
    if any(
        name in {
            "get_profile_summary",
            "list_entity_types",
            "typed_node_lookup",
            "typed_relation_lookup",
            "fetch_node_by_id",
            "fetch_relation_detail",
            "view_durable_memory_summary",
            "search_memory_semantic",
        }
        for name in successful_tools
    ):
        methods.append("graph")
    if any(name in {"search_web", "fetch_url", "find_official_sources"} for name in successful_tools):
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
            try:
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
                resp = await client.get(f"{settings.OLLAMA_URL}/api/tags")
                embeddings_status = "connected" if resp.status_code == 200 else "error"
            except Exception:
                embeddings_status = "disconnected"
    except Exception:
        llm_status = "disconnected"
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
