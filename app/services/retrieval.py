"""Retrieval planning, memory-pack construction, and lightweight caching."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Any

from app.adapters.neo4j.graph_store import get_due_saved_recommendations, get_full_profile, get_relevant_memories
from app.adapters.neo4j.vector_store import hybrid_search
from app.adapters.web_search.fallback_chain import search
from app.services.conflict_semantics import split_conflict_groups

log = logging.getLogger("pathfinder.retrieval")

_RETRIEVAL_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 120.0

_INTENT_FIELDS = {
    "academic": ("courses", "goals", "constraints", "preferences", "documents"),
    "career": ("skills", "experience", "projects", "goals", "preferences", "documents"),
    "interview": ("skills", "experience", "projects", "behavioral_patterns", "documents"),
    "document": ("documents", "candidate_facts", "memory_items"),
    "research": ("goals", "preferences", "documents"),
    "profile": ("all_entities",),
    "general": ("goals", "preferences", "constraints", "memory_items"),
}

_CONFLICT_PRONE_FACT_TYPES = {
    "preference",
    "constraint",
}


def _cache_key(student_id: str, domain: str, task_type: str, reasoning_depth: str, query: str) -> str:
    payload = "|".join([student_id, domain, task_type, reasoning_depth, query.strip().lower()])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> dict[str, Any] | None:
    cached = _RETRIEVAL_CACHE.get(key)
    if not cached:
        return None
    ts, value = cached
    if time.time() - ts > _CACHE_TTL_SECONDS:
        _RETRIEVAL_CACHE.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: dict[str, Any]) -> None:
    _RETRIEVAL_CACHE[key] = (time.time(), value)


def build_retrieval_plan(
    *,
    student_id: str,
    domain: str,
    task_type: str,
    reasoning_depth: str,
    query: str,
    needs_web: bool | None = None,
) -> dict[str, Any]:
    """Create a bounded retrieval plan for the current question."""
    source_flags = {
        "profile": True,
        "memory": True,
        "documents": domain in {"academic", "career", "interview", "document", "profile"},
        "web": bool(needs_web) if needs_web is not None else (domain in {"academic", "career", "research"} or "http" in query.lower()),
    }
    if reasoning_depth == "light":
        source_flags["web"] = source_flags["web"] and ("http" in query.lower() or domain == "research")
    return {
        "student_id": student_id,
        "domain": domain,
        "task_type": task_type,
        "reasoning_depth": reasoning_depth,
        "sources": source_flags,
    }


async def build_memory_pack(
    *,
    student_id: str,
    domain: str,
    task_type: str,
    reasoning_depth: str,
    query: str,
    needs_web: bool | None = None,
) -> dict[str, Any]:
    """Fetch a compact, relevance-focused memory pack for reasoning."""
    key = _cache_key(student_id, domain, task_type, reasoning_depth, query)
    cached = _cache_get(key)
    if cached:
        return cached

    plan = build_retrieval_plan(
        student_id=student_id,
        domain=domain,
        task_type=task_type,
        reasoning_depth=reasoning_depth,
        query=query,
        needs_web=needs_web,
    )
    sources = plan["sources"]

    profile_task = get_full_profile(student_id) if sources["profile"] else _noop({})
    memory_task = get_relevant_memories(student_id, query) if sources["memory"] else _noop(
        {"memory_items": [], "candidate_facts": [], "evidence": []}
    )
    docs_task = hybrid_search(query, k=5, student_id=student_id) if sources["documents"] else _noop([])
    web_task = _search_web(query) if sources["web"] else _noop([])
    plans_task = get_due_saved_recommendations(student_id) if sources["memory"] else _noop([])

    profile, memory, documents, web_results, saved_recommendations = await asyncio.gather(
        profile_task, memory_task, docs_task, web_task, plans_task
    )

    always_on = _build_personal_context(profile)
    scoped_profile = _filter_profile(profile, domain)
    conflicts = _collect_conflicts(profile, memory)
    pack = {
        "plan": plan,
        "always_on_context": always_on,
        "profile_context": scoped_profile,
        "semantic_memory": memory,
        "documents": documents[:5],
        "web_results": web_results[:5],
        "conflicts": conflicts,
        "saved_recommendations": saved_recommendations[:5],
    }
    _cache_set(key, pack)
    return pack


async def _search_web(query: str) -> list[dict[str, Any]]:
    try:
        return await search(query, max_results=4)
    except Exception as exc:
        log.warning("Web retrieval failed: %s", exc)
        return []


async def _noop(value: Any) -> Any:
    return value


def _build_personal_context(profile: dict[str, Any]) -> dict[str, Any]:
    personal = profile.get("personal", {})
    return {
        "name": personal.get("name"),
        "university": personal.get("university"),
        "program": personal.get("program"),
        "semester": personal.get("semester"),
        "top_goal": (profile.get("goals") or [{}])[0].get("name") if profile.get("goals") else None,
    }


def _filter_profile(profile: dict[str, Any], domain: str) -> dict[str, Any]:
    fields = _INTENT_FIELDS.get(domain, _INTENT_FIELDS["general"])
    return {field: profile.get(field, []) for field in fields}


def _collect_conflicts(profile: dict[str, Any], memory: dict[str, Any]) -> list[dict[str, Any]]:
    conflicts = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for fact in memory.get("candidate_facts", []) + profile.get("candidate_facts", []):
        if not fact:
            continue
        if fact.get("status") in {"superseded", "archived"}:
            continue
        fact_type = fact.get("fact_type", "generic")
        grouped.setdefault(fact_type, []).append(fact)

    for fact_type, items in grouped.items():
        if fact_type not in _CONFLICT_PRONE_FACT_TYPES:
            continue
        conflict_groups, _ = split_conflict_groups(fact_type, items)
        for group in conflict_groups:
            explicit = [item for item in group if item.get("status") == "conflicted"]
            ranked = sorted(
                explicit or group,
                key=lambda item: float(item.get("confidence", 0.0) or 0.0),
                reverse=True,
            )
            top = dict(ranked[0])
            top["conflict_kind"] = "explicit" if explicit else "bifurcated"
            top["alternatives"] = [str(item.get("value", "")).strip() for item in ranked[1:3] if str(item.get("value", "")).strip()]
            top["fact_type"] = fact_type
            conflicts.append(top)
    deduped = []
    seen = set()
    for conflict in conflicts:
        key = (conflict.get("id"), conflict.get("fact_type"), conflict.get("value"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(conflict)
    return deduped[:5]
