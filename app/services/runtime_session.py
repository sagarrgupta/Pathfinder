"""Runtime session helpers for chat execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.config.settings import settings
from app.utils.runtime_utils import infer_method


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
            "reasoning": self.reasoning,
        }

    def build_graph_config(self) -> dict[str, Any]:
        """Build graph config for this turn."""
        return {
            "configurable": {"thread_id": f"{self.student_id}:{self.session_id}"},
            "recursion_limit": 15,
        }

    def build_done_payload(self, final_state: dict[str, Any]) -> dict[str, Any]:
        """Build the final SSE payload for a completed turn."""
        latest_ingestion = dict(final_state.get("latest_ingestion_result", {}) or {})
        return {
            "session_id": self.session_id,
            "student_id": self.student_id,
            "citations": final_state.get("citations", []),
            "method": infer_method(final_state),
            "dependency_status": asdict(self.dependency_status),
            "processing_issues": final_state.get("processing_issues", []),
            "stop_reason": final_state.get("stop_reason", ""),
            "selected_specialist": final_state.get("selected_specialist", ""),
            "routing_scores": final_state.get("routing_scores", {}),
            "routing_reason": final_state.get("routing_reason", ""),
            "tool_call_log": final_state.get("tool_call_log", []),
            "specialist_output": final_state.get("specialist_output", {}),
            "session_context": str(final_state.get("session_context", "") or ""),
            "long_context": str(final_state.get("long_context", "") or ""),
            "document_ingestion": latest_ingestion,
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
    normalized_reasoning = str(reasoning or "medium").strip().lower() or "medium"
    snapshot = RuntimeSnapshot(
        session_id=session_id,
        student_id=student_id,
        selected_text_model=settings.LLM_MODEL,
        reasoning=normalized_reasoning,
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

async def get_dependency_status() -> dict[str, str]:
    """Check live dependency health for the current turn."""
    neo4j_status = "unknown"
    llm_status = "unknown"
    embeddings_status = "unknown"

    try:
        from app.tools.graph_tools import get_driver

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
