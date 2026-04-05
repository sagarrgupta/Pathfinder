"""Structured recovery recipes for common Pathfinder runtime failures."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class RecoveryEvent:
    """Structured recovery event for one automatic degradation or escalation."""

    scenario: str
    status: str
    reason: str
    attempted_steps: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def recovery_for_dependency_gate(workflow: str, dependency_status: dict[str, Any], blocker: str) -> list[RecoveryEvent]:
    """Return explicit recovery events for dependency-gated workflows."""
    events: list[RecoveryEvent] = []
    llm_status = str(dependency_status.get("llm", "unknown"))
    neo4j_status = str(dependency_status.get("neo4j", "unknown"))
    embeddings_status = str(dependency_status.get("embeddings", "unknown"))

    if llm_status == "no_model_loaded":
        events.append(
            RecoveryEvent(
                scenario="llm_no_model_loaded",
                status="escalated",
                reason=blocker,
                attempted_steps=["check_lmstudio_models", "attempt_default_model_load", "preserve_turn_state"],
                metadata={"workflow": workflow, "llm_status": llm_status},
            )
        )
        return events

    if llm_status != "connected":
        events.append(
            RecoveryEvent(
                scenario="llm_unavailable",
                status="escalated",
                reason=blocker,
                attempted_steps=["check_lmstudio_models", "preserve_turn_state"],
                metadata={"workflow": workflow, "llm_status": llm_status},
            )
        )
        return events

    if neo4j_status != "connected":
        events.append(
            RecoveryEvent(
                scenario="neo4j_unavailable",
                status="escalated",
                reason=blocker,
                attempted_steps=["preserve_turn_state", "skip_profile_backed_reasoning"],
                metadata={"workflow": workflow, "neo4j_status": neo4j_status},
            )
        )
        return events

    if embeddings_status != "connected":
        events.append(
            RecoveryEvent(
                scenario="embeddings_unavailable",
                status="degraded",
                reason=blocker,
                attempted_steps=["attempt_local_only_reasoning", "disable_document_retrieval"],
                metadata={"workflow": workflow, "embeddings_status": embeddings_status},
            )
        )
    return events


def recovery_for_web_search_failure(query: str, error: str) -> RecoveryEvent:
    """Recovery event for failed web search degraded to local evidence only."""
    return RecoveryEvent(
        scenario="web_search_failure",
        status="degraded",
        reason="Web retrieval failed, so Pathfinder continued with local evidence only.",
        attempted_steps=["fallback_to_local_evidence", "preserve_retrieval_turn"],
        metadata={"query": query[:160], "error": error},
    )


def recovery_for_profile_ingestion_failure(
    source: str,
    error: str,
    fallback_updates: dict[str, Any] | None = None,
) -> RecoveryEvent:
    """Recovery event for profile ingestion that degraded to best-effort updates."""
    fallback_updates = fallback_updates or {}
    return RecoveryEvent(
        scenario="profile_ingestion_failure",
        status="degraded" if fallback_updates else "escalated",
        reason="Structured profile ingestion failed, so Pathfinder used best-effort profile updates where possible.",
        attempted_steps=["apply_best_effort_field_updates"] if fallback_updates else ["preserve_raw_profile_text"],
        metadata={
            "source": source,
            "error": error,
            "fallback_fields": sorted(list(fallback_updates.keys())),
        },
    )


def recovery_for_document_extraction_failure(filename: str, file_type: str, error: str) -> RecoveryEvent:
    """Recovery event for document extraction failures."""
    return RecoveryEvent(
        scenario="document_extraction_failure",
        status="degraded",
        reason="Document text extraction failed, so Pathfinder skipped or partially processed the file.",
        attempted_steps=["skip_failed_document", "continue_other_files"],
        metadata={"filename": filename, "file_type": file_type, "error": error},
    )


def recovery_for_empty_document_extraction(filename: str, file_type: str) -> RecoveryEvent:
    """Recovery event for files that produced no usable extracted text."""
    return RecoveryEvent(
        scenario="document_extraction_empty",
        status="degraded",
        reason="No usable text could be extracted from the uploaded file.",
        attempted_steps=["skip_empty_document", "continue_other_files"],
        metadata={"filename": filename, "file_type": file_type},
    )


def recovery_for_document_embedding_failure(filename: str, error: str) -> RecoveryEvent:
    """Recovery event for chunking/embedding storage failures."""
    return RecoveryEvent(
        scenario="document_embedding_failure",
        status="degraded",
        reason="Document embedding or chunk storage failed, so Pathfinder continued without vector retrieval for that file.",
        attempted_steps=["preserve_document_node", "continue_entity_extraction"],
        metadata={"filename": filename, "error": error},
    )


def recovery_for_entity_extraction_failure(filename: str, error: str) -> RecoveryEvent:
    """Recovery event for entity extraction failures during document analysis."""
    return RecoveryEvent(
        scenario="entity_extraction_failure",
        status="degraded",
        reason="Entity extraction failed for the document, so Pathfinder kept the extracted text but skipped knowledge-graph enrichment for that file.",
        attempted_steps=["preserve_text_chunks", "skip_entity_graph_enrichment"],
        metadata={"filename": filename, "error": error},
    )


def recovery_for_weak_retrieval(query: str, domain: str) -> RecoveryEvent:
    """Recovery event when retrieval produces very thin evidence."""
    return RecoveryEvent(
        scenario="weak_retrieval",
        status="degraded",
        reason="Retrieved evidence was thin, so Pathfinder continued with limited context and should answer more conservatively.",
        attempted_steps=["fallback_to_available_profile_and_memory", "preserve_turn_progress"],
        metadata={"query": query[:160], "domain": domain},
    )
