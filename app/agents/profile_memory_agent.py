"""Capability agent: structured profile retrieval."""

from __future__ import annotations

from app.adapters.neo4j.graph_store import ensure_student, get_full_profile
from app.core.state import PathfinderState
from app.services.memory_ingestion import ingest_memory


async def profile_memory_agent(state: PathfinderState) -> PathfinderState:
    """Load the active student's structured profile."""
    student_id = state.get("student_id", "")
    await ensure_student(student_id)
    step_progress = list(state.get("step_progress", []))
    profile_updates = list(state.get("profile_updates", []))

    if state.get("intent") == "profile" and state.get("task_type") == "update" and state.get("query", "").strip():
        latest_result: dict = {}
        web_results = state.get("web_results", []) or []
        has_url_query = "http://" in state.get("query", "").lower() or "https://" in state.get("query", "").lower()
        direct_url_results = [item for item in web_results if item.get("source") == "direct_url" and item.get("content")]
        if direct_url_results:
            combined_content = []
            source_urls = []
            for item in direct_url_results[:2]:
                title = str(item.get("title") or "Web page").strip()
                url = str(item.get("url") or "").strip()
                content = str(item.get("content") or "").strip()
                if not content:
                    continue
                if url:
                    source_urls.append(url)
                combined_content.append(f"{title}\nURL: {url}\n\n{content[:12000]}")
            if combined_content:
                latest_result = await ingest_memory(
                    student_id=student_id,
                    source_type="profile_update_web",
                    content="\n\n".join(combined_content),
                    source_ref=",".join(source_urls) or state.get("session_id"),
                    session_id=state.get("session_id"),
                    metadata={
                        "intent": state.get("intent"),
                        "task_type": state.get("task_type"),
                        "source": "direct_url",
                        "urls": source_urls,
                    },
                )
                student_updates = latest_result.get("student_updates", {})
                if student_updates:
                    profile_updates.append(student_updates)
                step_progress.append("Applied profile information from the linked page")
        if has_url_query:
            ingestion_result = latest_result or {
                "student_updates": {},
                "candidate_facts": [],
                "promoted_entities": [],
                "profile_update_error": "Could not access the linked page",
            }
            if direct_url_results:
                step_progress.append("Used linked page content for profile enrichment")
            else:
                step_progress.append("Could not learn from the linked page")
        else:
            ingestion_result = await ingest_memory(
                student_id=student_id,
                source_type="profile_update_turn",
                content=state.get("query", ""),
                source_ref=state.get("session_id"),
                session_id=state.get("session_id"),
                metadata={"intent": state.get("intent"), "task_type": state.get("task_type")},
            )
            student_updates = ingestion_result.get("student_updates", {})
            if student_updates:
                profile_updates.append(student_updates)
            step_progress.append("Applied current-turn profile information")
    else:
        ingestion_result = state.get("latest_ingestion_result", {})

    profile = await get_full_profile(student_id)
    step_progress.append("Loaded structured profile context")
    sources = list(state.get("retrieval_sources", []))
    if "profile" not in sources:
        sources.append("profile")
    rationale = list(state.get("answer_rationale", []))
    if state.get("intent") == "profile" and state.get("task_type") == "update":
        rationale.append("Used the user's current-turn profile details before answering")
    return {
        **state,
        "profile_data": profile,
        "retrieval_sources": sources,
        "step_progress": step_progress,
        "answer_rationale": rationale,
        "profile_updates": profile_updates,
        "latest_ingestion_result": ingestion_result,
    }
