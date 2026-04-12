"""Focused free-text profile ingestion helpers used by the API."""

from __future__ import annotations

import logging
import re

from app.adapters.neo4j.graph_store import update_student
from app.services.memory_ingestion import ingest_memory
from app.services.runtime_recovery import recovery_for_profile_ingestion_failure

log = logging.getLogger("pathfinder.services.profile_text")


async def process_free_text(text: str, student_id: str) -> dict[str, object]:
    """Process free-text profile input from the My Profile page."""
    try:
        result = await ingest_memory(
            student_id=student_id,
            source_type="profile_text",
            content=text,
            metadata={"entrypoint": "profile_text.process_free_text"},
        )
        return {
            "entities_extracted": len(result.get("candidate_facts", [])) + len(result.get("promoted_entities", [])),
            "student_properties_updated": bool(result.get("student_updates")),
            "memory_items_created": len(result.get("memory_items", [])),
        }
    except Exception as exc:
        log.warning("Profile text ingestion failed, applying fallback updates only: %s", exc)
        fallback_updates = _fallback_student_updates(text)
        if fallback_updates:
            await update_student(student_id, **fallback_updates)
        return {
            "entities_extracted": 0,
            "student_properties_updated": bool(fallback_updates),
            "memory_items_created": 0,
            "warning": "ingestion_failed_fallback_applied",
            "updated_fields": sorted(list(fallback_updates.keys())),
            "recovery_events": [
                recovery_for_profile_ingestion_failure("profile_text", str(exc), fallback_updates).as_dict()
            ],
        }


def _fallback_student_updates(text: str) -> dict[str, str]:
    """Best-effort extraction of core student fields when full ingestion fails."""
    raw = (text or "").strip()
    if not raw:
        return {}
    lowered = raw.casefold()
    updates: dict[str, str] = {}

    name_match = re.search(r"\bmy name is\s+([A-Za-z][A-Za-z .'-]{1,80})", raw, flags=re.IGNORECASE)
    if name_match:
        updates["name"] = name_match.group(1).strip()

    uni_match = re.search(r"\b(?:university|college|school)\s*[:\-]\s*([^\n.;]{3,120})", raw, flags=re.IGNORECASE)
    if uni_match:
        updates["university"] = uni_match.group(1).strip()

    program_match = re.search(r"\b(?:program|major|degree)\s*[:\-]\s*([^\n.;]{2,120})", raw, flags=re.IGNORECASE)
    if program_match:
        updates["program"] = program_match.group(1).strip()

    gpa_match = re.search(r"\bgpa\s*(?:is|=|:)?\s*([0-4](?:\.\d{1,2})?)", lowered)
    if gpa_match:
        updates["gpa"] = gpa_match.group(1)

    semester_match = re.search(r"\b(?:semester)\s*[:\-]\s*([^\n.;]{2,60})", raw, flags=re.IGNORECASE)
    if semester_match:
        updates["semester"] = semester_match.group(1).strip()
    elif "first semester" in lowered:
        updates["semester"] = "first semester"

    return updates
