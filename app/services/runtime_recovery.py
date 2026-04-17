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
