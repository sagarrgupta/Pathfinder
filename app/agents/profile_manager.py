"""Node 5: Profile Manager.

Handles all Neo4j knowledge graph interactions:
  - Load student profile
  - Semantic search over document chunks
  - Graph queries for structured data
  - CRUD operations on profile entities
  - Free-text profile input processing
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage

from app.adapters.llm.lmstudio import get_text_llm
from app.adapters.neo4j.graph_store import (
    ensure_student,
    get_full_profile,
    store_extracted_entities,
    update_student,
)
from app.adapters.neo4j.vector_store import hybrid_search
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.profile_manager")

_TEXT_EXTRACTION_PROMPT = """You are a profile data extractor. The user has entered free-text information about themselves.
Extract structured entities from this text.

Respond with valid JSON:
{{
    "entities": [
        {{"label": "Skill", "properties": {{"name": "Python", "proficiency": "advanced"}}, "relationship": "HAS_SKILL"}},
        {{"label": "Goal", "properties": {{"name": "PhD in CS", "type": "phd", "field": "Computer Science"}}, "relationship": "HAS_GOAL"}}
    ],
    "student_properties": {{"name": "John", "gpa": "3.5"}}
}}

Possible labels: Course, Skill, Company, Goal, Interest, Project, Department
Possible relationships: TOOK, HAS_SKILL, WORKED_AT, HAS_GOAL, INTERESTED_IN, COMPLETED, IN_DEPARTMENT

User text: {text}
"""


async def profile_manager(state: PathfinderState) -> PathfinderState:
    """Load profile, search documents, and enrich state with personal data."""
    query = state.get("query", "")
    student_id = state.get("student_id", "default")
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
    text: str, student_id: str = "default"
) -> dict[str, Any]:
    """Process free-text input from the My Profile page.

    Extracts entities and stores them in the KG.
    """
    llm = get_text_llm()

    response = await llm.ainvoke([
        SystemMessage(content="You are a profile data extractor."),
        HumanMessage(content=_TEXT_EXTRACTION_PROMPT.format(text=text)),
    ])

    content = response.content if isinstance(response.content, str) else str(response.content)

    try:
        json_start = content.find("{")
        json_end = content.rfind("}") + 1
        parsed = json.loads(content[json_start:json_end])
    except (json.JSONDecodeError, ValueError):
        return {"entities_extracted": 0, "error": "Could not parse entities from text"}

    entities = parsed.get("entities", [])
    student_props = parsed.get("student_properties", {})

    count = await store_extracted_entities(entities, "free_text_input", student_id)

    if student_props:
        await update_student(student_id, **{k: v for k, v in student_props.items() if v})

    return {"entities_extracted": count, "student_properties_updated": bool(student_props)}


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
