"""Explicit runtime policy evaluation for operational control-plane decisions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class RuntimePolicyDecision:
    """One explicit runtime policy outcome."""

    policy: str
    outcome: str
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RuntimePolicySnapshot:
    """Collected runtime policy outcomes for one turn."""

    decisions: list[RuntimePolicyDecision]
    blocked: bool = False
    blocked_reason: str = ""
    compare_mode_allowed: bool = True
    web_research_allowed: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "decisions": [decision.as_dict() for decision in self.decisions],
            "blocked": self.blocked,
            "blocked_reason": self.blocked_reason,
            "compare_mode_allowed": self.compare_mode_allowed,
            "web_research_allowed": self.web_research_allowed,
        }


def evaluate_runtime_preflight(
    *,
    query: str,
    files: list[dict[str, Any]],
    is_global_upload: bool,
    request_plan: dict[str, Any],
    dependency_status: dict[str, Any],
    selected_retrieval_mode: str,
    compare_mode: bool = False,
) -> RuntimePolicySnapshot:
    """Evaluate request-start operational policies."""
    lowered = (query or "").lower()
    decisions: list[RuntimePolicyDecision] = []

    if files:
        decisions.append(
            RuntimePolicyDecision(
                policy="upload_scope",
                outcome="allow",
                reason="Files were uploaded for this turn.",
                metadata={
                    "uploaded_file_count": len(files),
                    "is_global_upload": bool(is_global_upload),
                },
            )
        )

    if "http://" in lowered or "https://" in lowered:
        decisions.append(
            RuntimePolicyDecision(
                policy="url_detection",
                outcome="prefer_web_research",
                reason="The query contains a URL, so web research should stay available.",
                metadata={"query_has_url": True},
            )
        )

    compare_mode_allowed = not (compare_mode and bool(files))
    decisions.append(
        RuntimePolicyDecision(
            policy="compare_mode",
            outcome="allow" if compare_mode_allowed else "deny",
            reason=(
                "Compare mode is allowed for this turn."
                if compare_mode_allowed
                else "Compare mode should not run in the same turn as document uploads."
            ),
            metadata={
                "compare_mode": bool(compare_mode),
                "uploaded_file_count": len(files),
            },
        )
    )

    web_search_status = str(dependency_status.get("web_search", "unknown"))
    web_research_allowed = web_search_status in {"configured", "fallback_only"}
    decisions.append(
        RuntimePolicyDecision(
            policy="web_search_availability",
            outcome="allow" if web_research_allowed else "degraded",
            reason=(
                "Web search is available through the configured provider chain."
                if web_research_allowed
                else "Web search is unavailable, so Pathfinder should stay on local evidence only."
            ),
            metadata={"web_search_status": web_search_status},
        )
    )

    decisions.append(
        RuntimePolicyDecision(
            policy="retrieval_strategy",
            outcome="active",
            reason="The active retrieval strategy was resolved at request start.",
            metadata={
                "selected_retrieval_mode": selected_retrieval_mode,
                "request_plan_reasons": list(request_plan.get("reasons", []) or []),
            },
        )
    )

    return RuntimePolicySnapshot(
        decisions=decisions,
        blocked=not compare_mode_allowed,
        blocked_reason=(
            "Compare mode is disabled for turns that upload files."
            if not compare_mode_allowed
            else ""
        ),
        compare_mode_allowed=compare_mode_allowed,
        web_research_allowed=web_research_allowed,
    )


def dependency_gate_for_workflow(workflow: str, dependency_status: dict[str, Any]) -> str:
    """Central dependency policy for advisory workflow gating."""
    llm_status = str(dependency_status.get("llm", "unknown"))
    if llm_status == "no_model_loaded":
        return (
            "LM Studio is reachable, but no model is loaded right now, so I cannot complete this advising turn. "
            "Please load a model in LM Studio and retry."
        )
    if llm_status != "connected":
        return (
            "LLM runtime is unavailable right now, so I cannot complete this advising turn. "
            "Please restart LM Studio and retry."
        )

    neo4j_status = str(dependency_status.get("neo4j", "unknown"))
    if neo4j_status != "connected":
        return (
            "Neo4j is unavailable, so profile/memory-backed advising is blocked. "
            "Please restart Neo4j and retry."
        )

    embeddings_status = str(dependency_status.get("embeddings", "unknown"))
    if workflow in {
        "academic_planning",
        "program_understanding",
        "eligibility_check",
        "comparison_guidance",
        "career_alignment",
        "document_guidance",
    } and embeddings_status != "connected":
        return (
            "Embedding service is unavailable, so evidence retrieval is blocked. "
            "Please start Ollama (embeddings) and retry."
        )

    return ""


def workflow_needs_web_research(workflow: str, source_policy: dict[str, Any]) -> bool:
    """Operational policy for whether a workflow should include web research."""
    if workflow == "student_state_update":
        return False
    if workflow in {
        "academic_planning",
        "program_understanding",
        "eligibility_check",
        "comparison_guidance",
        "career_alignment",
        "document_guidance",
    }:
        return True
    return bool(source_policy.get("requires_live_data")) or bool(source_policy.get("primary_source_types"))


def apply_runtime_plan_policies(
    plan: list[str],
    workflow: str,
    source_policy: dict[str, Any],
) -> tuple[list[str], list[RuntimePolicyDecision]]:
    """Apply runtime plan guardrails and return the normalized plan plus decisions."""
    cleaned: list[str] = []
    seen: set[str] = set()
    decisions: list[RuntimePolicyDecision] = []

    for node in plan:
        if node in seen:
            continue
        seen.add(node)
        cleaned.append(node)

    if len(cleaned) != len(plan):
        decisions.append(
            RuntimePolicyDecision(
                policy="dedupe_plan_nodes",
                outcome="normalized",
                reason="Duplicate nodes were removed from the workflow plan.",
                metadata={"original_length": len(plan), "normalized_length": len(cleaned)},
            )
        )

    if workflow == "student_state_update":
        normalized = [node for node in cleaned if node in {"profile_manager"}] or ["profile_manager"]
        decisions.append(
            RuntimePolicyDecision(
                policy="student_state_update_scope",
                outcome="restricted",
                reason="Student-state updates should stay lightweight and deterministic.",
                metadata={"normalized_plan": normalized},
            )
        )
        return normalized, decisions

    if "web_researcher" in cleaned and not workflow_needs_web_research(workflow, source_policy):
        cleaned = [node for node in cleaned if node != "web_researcher"]
        decisions.append(
            RuntimePolicyDecision(
                policy="web_research_scope",
                outcome="removed",
                reason="Web research was removed because the workflow does not require it.",
                metadata={"workflow": workflow},
            )
        )

    if "fact_extractor" in cleaned and "web_researcher" not in cleaned and "doc_analyst" not in cleaned:
        cleaned = [node for node in cleaned if node != "fact_extractor"]
        decisions.append(
            RuntimePolicyDecision(
                policy="fact_extractor_dependency",
                outcome="removed",
                reason="Fact extraction was removed because no upstream evidence-producing node is present.",
                metadata={"workflow": workflow},
            )
        )

    if not decisions:
        decisions.append(
            RuntimePolicyDecision(
                policy="plan_guardrails",
                outcome="pass_through",
                reason="The workflow plan already satisfied runtime guardrails.",
                metadata={"workflow": workflow},
            )
        )

    return cleaned, decisions
