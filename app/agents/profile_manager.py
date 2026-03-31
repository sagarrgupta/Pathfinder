"""Node 5: Profile Manager.

Handles all Neo4j knowledge graph interactions:
  - Load student profile
  - Semantic search over document chunks
  - Graph queries for structured data
  - CRUD operations on profile entities
  - Free-text profile input processing
"""

from __future__ import annotations

import logging
from typing import Any

from app.adapters.neo4j.graph_store import (
    ensure_student,
    get_full_profile,
)
from app.adapters.neo4j.vector_store import hybrid_search
from app.core.state import PathfinderState
from app.services.memory_ingestion import ingest_memory

log = logging.getLogger("pathfinder.agents.profile_manager")

async def profile_manager(state: PathfinderState) -> PathfinderState:
    """Load profile, search documents, and enrich state with personal data."""
    query = state.get("query", "")
    student_id = state.get("student_id", "")
    session_id = state.get("session_id", "")

    step_progress = list(state.get("step_progress", []))
    step_progress.append("Checking your academic profile...")

    # Ensure student exists
    await ensure_student(student_id)

    # Load full profile from KG
    profile = await get_full_profile(student_id)

    # Semantic search over stored documents
    step_progress.append("Searching your documents...")
    retrieved = await hybrid_search(
        query=query,
        k=5,
        student_id=student_id,
        session_id=session_id,
    )

    step_progress.append(
        f"Found {len(retrieved)} relevant document chunks, "
        f"{len(profile.get('courses', []))} courses, "
        f"{len(profile.get('skills', []))} skills in your profile"
    )

    log.info(
        "Profile manager: %d chunks, %d courses, %d skills",
        len(retrieved),
        len(profile.get("courses", [])),
        len(profile.get("skills", [])),
    )

    return {
        **state,
        "profile_data": profile,
        "retrieved_documents": retrieved,
        "step_progress": step_progress,
        "next_node": _determine_next(state),
    }


async def process_free_text(
    text: str, student_id: str
) -> dict[str, Any]:
    """Process free-text input from the My Profile page.

    Extracts layered memory and promotes strong items into the KG.
    """
    result = await ingest_memory(
        student_id=student_id,
        source_type="profile_text",
        content=text,
        metadata={"entrypoint": "profile_manager.process_free_text"},
    )
    return {
        "entities_extracted": len(result.get("candidate_facts", []))
        + len(result.get("promoted_entities", [])),
        "student_properties_updated": bool(result.get("student_updates")),
        "memory_items_created": len(result.get("memory_items", [])),
    }


def _determine_next(state: PathfinderState) -> str:
    """Determine next node after profile management."""
    plan = state.get("plan", [])
    try:
        idx = plan.index("profile_manager")
        if idx + 1 < len(plan):
            return plan[idx + 1]
    except ValueError:
        pass
    return "evaluator"
