"""Retrieval planning, memory-pack construction, and lightweight caching."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import logging
import re
import time
from typing import Any

from app.adapters.neo4j.graph_store import get_due_saved_recommendations, get_full_profile, get_relevant_memories
from app.adapters.neo4j.vector_store import hybrid_search
from app.core.quality import (
    classify_web_source,
    build_session_summary,
    derive_decision_continuity,
    derive_recommendation_outcome_profile,
    derive_student_operating_model,
    infer_evidence_tiers,
)
from app.services.execution_registry import execute_web_search, get_active_retrieval_strategy
from app.services.conflict_semantics import split_conflict_groups
from app.services.runtime_recovery import recovery_for_web_search_failure, recovery_for_weak_retrieval

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

_TOKEN_RE = re.compile(r"[a-z0-9]{2,}", re.I)


@dataclass(frozen=True)
class RetrievalContext:
    student_id: str
    domain: str
    task_type: str
    reasoning_depth: str
    query: str
    needs_web: bool | None
    plan: dict[str, Any]
    sources: dict[str, Any]
    profile: dict[str, Any]
    student_operating_model: dict[str, Any]
    recommendation_outcome_profile: dict[str, Any]
    memory: dict[str, Any]
    documents: list[dict[str, Any]]
    web_results: list[dict[str, Any]]
    saved_recommendations: list[dict[str, Any]]
    recovery_events: list[dict[str, Any]]


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
    force_refresh: bool = False,
    profile_override: dict[str, Any] | None = None,
    documents_override: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fetch a compact, relevance-focused memory pack for reasoning."""
    key = _cache_key(student_id, domain, task_type, reasoning_depth, query)
    if not force_refresh:
        cached = _cache_get(key)
        if cached:
            return cached

    context = await _prepare_retrieval_context(
        student_id=student_id,
        domain=domain,
        task_type=task_type,
        reasoning_depth=reasoning_depth,
        query=query,
        needs_web=needs_web,
        profile_override=profile_override,
        documents_override=documents_override,
    )
    strategy_name = get_active_retrieval_strategy()
    strategy = _get_retrieval_strategy(strategy_name)
    pack = await strategy(context)
    _cache_set(key, pack)
    return pack


async def _prepare_retrieval_context(
    *,
    student_id: str,
    domain: str,
    task_type: str,
    reasoning_depth: str,
    query: str,
    needs_web: bool | None = None,
    profile_override: dict[str, Any] | None = None,
    documents_override: list[dict[str, Any]] | None = None,
) -> RetrievalContext:
    plan = build_retrieval_plan(
        student_id=student_id,
        domain=domain,
        task_type=task_type,
        reasoning_depth=reasoning_depth,
        query=query,
        needs_web=needs_web,
    )
    sources = plan["sources"]
    profile_task = _noop(profile_override) if profile_override is not None else (
        get_full_profile(student_id) if sources["profile"] else _noop({})
    )
    memory_task = get_relevant_memories(student_id, query) if sources["memory"] else _noop(
        {"memory_items": [], "candidate_facts": [], "evidence": []}
    )
    docs_task = _noop(documents_override) if documents_override is not None else (
        hybrid_search(query, k=5, student_id=student_id) if sources["documents"] else _noop([])
    )
    web_task = _search_web(query) if sources["web"] else _noop({"results": [], "recovery_events": []})
    plans_task = get_due_saved_recommendations(student_id) if sources["memory"] else _noop([])

    profile, memory, documents, web_payload, saved_recommendations = await asyncio.gather(
        profile_task, memory_task, docs_task, web_task, plans_task
    )
    web_payload = web_payload or {}
    if sources["web"]:
        web_payload = await _retry_web_if_weak(
            query=query,
            domain=domain,
            profile=profile or {},
            initial_payload=web_payload,
        )
    return RetrievalContext(
        student_id=student_id,
        domain=domain,
        task_type=task_type,
        reasoning_depth=reasoning_depth,
        query=query,
        needs_web=needs_web,
        plan=plan,
        sources=sources,
        profile=profile or {},
        student_operating_model=derive_student_operating_model(
            build_session_summary(profile or {}, [], query),
            profile or {},
            query,
        ),
        recommendation_outcome_profile=derive_recommendation_outcome_profile(saved_recommendations or []),
        memory=memory or {},
        documents=list(documents or []),
        web_results=list(web_payload.get("results", []) or []),
        saved_recommendations=list(saved_recommendations or []),
        recovery_events=list(web_payload.get("recovery_events", []) or []),
    )


async def _memory_pack_strategy(context: RetrievalContext) -> dict[str, Any]:
    profile = context.profile
    student_operating_model = context.student_operating_model
    recommendation_outcome_profile = context.recommendation_outcome_profile
    memory = _rerank_memory_items(context.memory, context.query, profile, student_operating_model)
    documents = _rerank_documents(context.documents, context.query, profile, student_operating_model)
    web_results = _rerank_web_results(context.web_results, context.query, profile, student_operating_model)
    saved_recommendations = _rerank_saved_recommendations(
        context.saved_recommendations,
        context.query,
        profile,
        student_operating_model,
        recommendation_outcome_profile,
    )
    always_on = _build_personal_context(profile)
    scoped_profile = _filter_profile(profile, context.domain)
    conflicts = _collect_conflicts(profile, memory)
    decision_records = [
        item for item in (memory.get("memory_items", []) or [])
        if str(item.get("memory_type", "") or "").strip().lower() == "decision_record"
    ][:5]
    decision_continuity = derive_decision_continuity(context.query, decision_records)
    retrieval_trace = _build_retrieval_trace(context, memory, documents, web_results, saved_recommendations)
    recovery_events = list(context.recovery_events or [])
    evidence_quality = _compute_evidence_quality_summary(
        context.query,
        context.domain,
        profile,
        documents,
        web_results,
        saved_recommendations,
    )
    if (
        not documents
        and not web_results
        and not (memory.get("candidate_facts", []) or memory.get("memory_items", []))
    ) or float(evidence_quality.get("overall_quality", 0.0) or 0.0) < 0.42:
        recovery_events.append(recovery_for_weak_retrieval(context.query, context.domain).as_dict())
    return {
        "strategy": "memory_pack",
        "plan": context.plan,
        "always_on_context": always_on,
        "profile_context": scoped_profile,
        "semantic_memory": memory,
        "documents": documents[:5],
        "web_results": web_results[:5],
        "conflicts": conflicts,
        "saved_recommendations": saved_recommendations[:5],
        "decision_records": decision_records,
        "decision_continuity": decision_continuity,
        "retrieval_trace": retrieval_trace,
        "retrieval_diagnostics": _build_retrieval_diagnostics(
            profile,
            student_operating_model,
            recommendation_outcome_profile,
            memory,
            documents,
            web_results,
            evidence_quality,
        ),
        "recovery_events": recovery_events,
    }


def _get_retrieval_strategy(name: str):
    strategies = {
        "memory_pack": _memory_pack_strategy,
    }
    return strategies.get(name, _memory_pack_strategy)


async def _search_web(query: str) -> dict[str, Any]:
    try:
        return {"results": await execute_web_search(query, max_results=4), "recovery_events": []}
    except Exception as exc:
        log.warning("Web retrieval failed: %s", exc)
        return {
            "results": [],
            "recovery_events": [recovery_for_web_search_failure(query, str(exc)).as_dict()],
        }


async def _retry_web_if_weak(
    *,
    query: str,
    domain: str,
    profile: dict[str, Any],
    initial_payload: dict[str, Any],
) -> dict[str, Any]:
    results = list((initial_payload or {}).get("results", []) or [])
    recovery_events = list((initial_payload or {}).get("recovery_events", []) or [])
    if not _should_retry_web(domain, results, profile):
        return {"results": results, "recovery_events": recovery_events}
    retry_query = _build_official_retry_query(query, domain, profile)
    if not retry_query or retry_query.strip().casefold() == query.strip().casefold():
        return {"results": results, "recovery_events": recovery_events}
    try:
        retry_results = await execute_web_search(retry_query, max_results=4)
    except Exception as exc:
        recovery_events.append(recovery_for_web_search_failure(retry_query, str(exc)).as_dict())
        return {"results": results, "recovery_events": recovery_events}
    combined = _dedupe_web_results(results + list(retry_results or []), limit=6)
    if combined != results:
        recovery_events.append(
            {
                "scenario": "retrieval_retry",
                "status": "recovered",
                "reason": "Initial web evidence looked weak, so Pathfinder retried with a more official targeted query.",
                "attempted_steps": ["detect_low_quality_web_results", "retry_with_official_query"],
                "metadata": {
                    "initial_query": query[:160],
                    "retry_query": retry_query[:200],
                    "domain": domain,
                },
            }
        )
    return {"results": combined, "recovery_events": recovery_events}


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


def _dedupe_web_results(results: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in results:
        url = str((item or {}).get("url", "") or "").strip()
        key = url.casefold() or str((item or {}).get("title", "") or "").strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= limit:
            break
    return deduped


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


def _tokenize(text: str) -> set[str]:
    return {token.casefold() for token in _TOKEN_RE.findall(text or "")}


def _profile_signal_terms(profile: dict[str, Any]) -> set[str]:
    terms: set[str] = set()
    personal = profile.get("personal", {}) or {}
    for key in ("program", "university"):
        terms |= _tokenize(str(personal.get(key, "")))
    for collection_name in ("skills", "goals", "preferences", "interests", "constraints", "courses"):
        for item in profile.get(collection_name, [])[:12]:
            terms |= _tokenize(str(item.get("name", "") or item.get("code", "") or item.get("value", "")))
    for fact in profile.get("profile_facts", [])[:20]:
        terms |= _tokenize(str(fact.get("value", "")))
    temporal_profile = profile.get("temporal_profile", {}) or {}
    for fact in (temporal_profile.get("stable_facts", []) or [])[:12]:
        terms |= _tokenize(str(fact.get("value", "")))
    for fact in (temporal_profile.get("evolving_facts", []) or [])[:12]:
        terms |= _tokenize(str(fact.get("value", "")))
    for fact in (temporal_profile.get("temporary_facts", []) or [])[:6]:
        terms |= _tokenize(str(fact.get("value", "")))
    return terms


def _operating_model_terms(student_operating_model: dict[str, Any]) -> set[str]:
    terms: set[str] = set()
    risk = str((student_operating_model or {}).get("risk_tolerance", ""))
    load = str((student_operating_model or {}).get("workload_preference", ""))
    urgency = str((student_operating_model or {}).get("internship_urgency", ""))
    planning = str((student_operating_model or {}).get("planning_style", ""))
    if risk == "conservative":
        terms |= {"safe", "stable", "realistic", "verified", "supported"}
    elif risk == "ambitious":
        terms |= {"advanced", "stretch", "ambitious", "competitive", "deeper"}
    if load == "lighter":
        terms |= {"manageable", "balanced", "light", "sustainable"}
    elif load == "heavier_if_valuable":
        terms |= {"intensive", "rigorous", "advanced"}
    if urgency == "high":
        terms |= {"internship", "job", "practical", "hiring", "resume"}
    if planning == "exploratory":
        terms |= {"option", "alternative", "path", "explore"}
    return terms


def _temporal_weight(item: dict[str, Any]) -> float:
    status = str(item.get("status") or "").lower()
    stability = str(item.get("stability") or "evolving").lower()
    if status in {"superseded", "archived"}:
        return -1.2
    if stability == "stable":
        return 0.25
    if stability == "evolving":
        return 0.1
    if stability == "temporary":
        return -0.05
    return 0.0


def _operating_model_bonus(text: str, student_operating_model: dict[str, Any]) -> tuple[float, list[str]]:
    model_terms = _operating_model_terms(student_operating_model)
    if not model_terms:
        return 0.0, []
    hits = sorted(_tokenize(text) & model_terms)
    if not hits:
        return 0.0, []
    score = min(0.45, 0.12 * len(hits))
    return round(score, 4), hits[:4]


def _recommendation_outcome_bonus(
    text: str,
    recommendation_type: str,
    recommendation_outcome_profile: dict[str, Any],
) -> tuple[float, list[str]]:
    preferred_types = {
        str(item).strip().lower()
        for item in (recommendation_outcome_profile or {}).get("preferred_recommendation_types", []) or []
        if str(item).strip()
    }
    follow_through_style = str((recommendation_outcome_profile or {}).get("follow_through_style", ""))
    hits: list[str] = []
    score = 0.0
    lowered_type = str(recommendation_type or "").strip().lower()
    if lowered_type and lowered_type in preferred_types:
        hits.append(f"type:{lowered_type}")
        score += 0.25
    if follow_through_style == "high_follow_through" and any(token in text.casefold() for token in ("next step", "action", "apply", "verify")):
        hits.append("follow_through")
        score += 0.12
    if follow_through_style == "prefers_small_commits" and any(token in text.casefold() for token in ("small", "first", "one", "manageable")):
        hits.append("small_commit")
        score += 0.12
    if follow_through_style == "selective_commitment" and any(token in text.casefold() for token in ("best-supported", "verified", "realistic")):
        hits.append("selective_fit")
        score += 0.08
    return round(min(0.45, score), 4), hits[:4]


def _overlap_score(text: str, query_terms: set[str], profile_terms: set[str]) -> tuple[float, list[str]]:
    text_terms = _tokenize(text)
    query_hits = sorted(query_terms & text_terms)
    profile_hits = sorted(profile_terms & text_terms)
    score = (len(query_hits) * 1.0) + (len(profile_hits) * 0.35)
    return score, query_hits[:5] + [hit for hit in profile_hits[:5] if hit not in query_hits[:5]]


def _rerank_documents(
    documents: list[dict[str, Any]],
    query: str,
    profile: dict[str, Any],
    student_operating_model: dict[str, Any],
) -> list[dict[str, Any]]:
    query_terms = _tokenize(query)
    profile_terms = _profile_signal_terms(profile)
    scored: list[dict[str, Any]] = []
    for document in documents or []:
        text = " ".join(
            [
                str(document.get("filename", "")),
                str(document.get("title", "")),
                str(document.get("text", ""))[:1400],
            ]
        )
        overlap, matched_terms = _overlap_score(text, query_terms, profile_terms)
        operating_bonus, operating_hits = _operating_model_bonus(text, student_operating_model)
        document_trust_bonus, trust_meta = _document_trust_bonus(document)
        policy_bonus = _policy_importance_bonus(query, text, "profile_doc")
        base_score = float(document.get("score", 0.0) or 0.0)
        quality_score = round((document_trust_bonus * 0.7) + min(0.3, policy_bonus), 4)
        retrieval_score = round(base_score + overlap + operating_bonus + quality_score, 4)
        enriched = dict(document)
        enriched["retrieval_score"] = retrieval_score
        enriched["retrieval_reason"] = {
            "base_score": round(base_score, 4),
            "query_profile_overlap": round(overlap, 4),
            "matched_terms": matched_terms,
            "operating_model_bonus": operating_bonus,
            "operating_model_hits": operating_hits,
            "quality_score": quality_score,
            "policy_importance_bonus": round(policy_bonus, 4),
            **trust_meta,
        }
        scored.append(enriched)
    scored.sort(key=lambda item: (float(item.get("retrieval_score", 0.0) or 0.0), float(item.get("score", 0.0) or 0.0)), reverse=True)
    return scored


def _web_source_weight(url: str, title: str) -> float:
    lowered = f"{url} {title}".casefold()
    if ".edu" in lowered or ".gov" in lowered:
        return 1.2
    if any(token in lowered for token in ("catalog", "bulletin", "curriculum", "admission", "registrar")):
        return 0.7
    return 0.15


def _freshness_weight(freshness_tier: str) -> float:
    lowered = str(freshness_tier or "").lower()
    if lowered == "live":
        return 1.0
    if lowered == "catalog":
        return 0.75
    if lowered == "timeless":
        return 0.55
    return 0.25


def _trust_weight(trust_tier: str) -> float:
    lowered = str(trust_tier or "").lower()
    if lowered == "primary_official":
        return 1.0
    if lowered == "secondary_official":
        return 0.75
    if lowered == "user_profile":
        return 0.6
    return 0.25


def _fit_weight(fit_tier: str) -> float:
    lowered = str(fit_tier or "").lower()
    if lowered == "direct":
        return 1.0
    if lowered == "adjacent":
        return 0.6
    return 0.2


def _policy_importance_bonus(query: str, text: str, source_type: str) -> float:
    query_lower = str(query or "").casefold()
    text_lower = str(text or "").casefold()
    policy_query = any(
        token in query_lower
        for token in ("requirement", "requirements", "policy", "deadline", "prerequisite", "eligibility", "admission")
    )
    if not policy_query:
        return 0.0
    if source_type in {"degree_page", "admissions_page", "schedule_page"}:
        return 0.45
    if any(token in text_lower for token in ("requirement", "policy", "deadline", "prerequisite", "eligibility")):
        return 0.2
    return 0.0


def _document_trust_bonus(document: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    filename = str(document.get("filename", "") or "")
    title = str(document.get("title", "") or "")
    text = " ".join([filename, title]).casefold()
    scope = str(document.get("scope", "") or "").casefold()
    trust = 0.35
    kind = "general_document"
    if any(token in text for token in ("transcript", "resume", "cv", "syllabus", "catalog", "program", "handbook")):
        trust = 0.75
        kind = "structured_profile_document"
    if scope == "global":
        trust += 0.05
    return trust, {"document_trust": round(trust, 4), "document_kind": kind}


def _build_official_retry_query(query: str, domain: str, profile: dict[str, Any]) -> str:
    personal = profile.get("personal", {}) or {}
    university = str(personal.get("university", "") or "").strip()
    program = str(personal.get("program", "") or "").strip()
    suffix = "official"
    if domain == "academic":
        suffix = "official catalog requirements"
    elif domain == "career":
        suffix = "official job requirements"
    elif domain == "research":
        suffix = "official program research"
    parts = [query.strip()]
    if university:
        parts.append(f"\"{university}\"")
    if program:
        parts.append(f"\"{program}\"")
    parts.append(suffix)
    parts.append("site:.edu")
    return " ".join(part for part in parts if part)


def _web_quality_meta(result: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    personal = profile.get("personal", {}) or {}
    program_text = str(personal.get("program", "") or "")
    institution_text = str(personal.get("university", "") or "")
    level = "graduate" if any(token in program_text.casefold() for token in ("master", "graduate", "ms", "phd")) else "undergraduate"
    source_type, _time_scope = classify_web_source(
        str(result.get("url", "")),
        str(result.get("title", "")),
        str(result.get("content", "")),
    )
    trust_tier, fit_tier, freshness_tier = infer_evidence_tiers(
        str(result.get("url", "")),
        source_type,
        program_text,
        level,
        str(result.get("title", "")),
        str(result.get("content", "")),
        institution_text,
    )
    return {
        "source_type": source_type,
        "trust_tier": trust_tier,
        "fit_tier": fit_tier,
        "freshness_tier": freshness_tier,
    }


def _web_quality_score(result: dict[str, Any], profile: dict[str, Any]) -> float:
    meta = _web_quality_meta(result, profile)
    return round(
        (_trust_weight(meta["trust_tier"]) * 0.45)
        + (_fit_weight(meta["fit_tier"]) * 0.3)
        + (_freshness_weight(meta["freshness_tier"]) * 0.25),
        4,
    )


def _should_retry_web(domain: str, results: list[dict[str, Any]], profile: dict[str, Any]) -> bool:
    if domain not in {"academic", "career", "research"}:
        return False
    if not results:
        return True
    scores = [_web_quality_score(item, profile) for item in results[:3]]
    average = sum(scores) / max(1, len(scores))
    official_hits = sum(1 for item in results[:4] if _web_quality_meta(item, profile).get("trust_tier") == "primary_official")
    return average < 0.56 or official_hits == 0


def _rerank_web_results(
    results: list[dict[str, Any]],
    query: str,
    profile: dict[str, Any],
    student_operating_model: dict[str, Any],
) -> list[dict[str, Any]]:
    query_terms = _tokenize(query)
    profile_terms = _profile_signal_terms(profile)
    scored: list[dict[str, Any]] = []
    for result in results or []:
        text = " ".join(
            [
                str(result.get("title", "")),
                str(result.get("url", "")),
                str(result.get("content", ""))[:1600],
            ]
        )
        overlap, matched_terms = _overlap_score(text, query_terms, profile_terms)
        operating_bonus, operating_hits = _operating_model_bonus(text, student_operating_model)
        weight = _web_source_weight(str(result.get("url", "")), str(result.get("title", "")))
        quality_meta = _web_quality_meta(result, profile)
        quality_score = _web_quality_score(result, profile)
        policy_bonus = _policy_importance_bonus(query, text, quality_meta["source_type"])
        retrieval_score = round(overlap + weight + operating_bonus + quality_score + policy_bonus, 4)
        enriched = dict(result)
        enriched["retrieval_score"] = retrieval_score
        enriched["retrieval_reason"] = {
            "source_weight": round(weight, 4),
            "query_profile_overlap": round(overlap, 4),
            "matched_terms": matched_terms,
            "operating_model_bonus": operating_bonus,
            "operating_model_hits": operating_hits,
            "quality_score": quality_score,
            "policy_importance_bonus": round(policy_bonus, 4),
            **quality_meta,
        }
        scored.append(enriched)
    scored.sort(key=lambda item: float(item.get("retrieval_score", 0.0) or 0.0), reverse=True)
    return scored


def _rerank_memory_items(
    memory: dict[str, Any],
    query: str,
    profile: dict[str, Any],
    student_operating_model: dict[str, Any],
) -> dict[str, Any]:
    query_terms = _tokenize(query)
    profile_terms = _profile_signal_terms(profile)
    reranked = dict(memory or {})
    for key, fields in {
        "candidate_facts": ("fact_type", "value"),
        "memory_items": ("memory_type", "summary"),
        "evidence": ("source_type", "content"),
    }.items():
        scored: list[dict[str, Any]] = []
        for item in reranked.get(key, []) or []:
            text = " ".join(str(item.get(field, "")) for field in fields)
            overlap, matched_terms = _overlap_score(text, query_terms, profile_terms)
            operating_bonus, operating_hits = _operating_model_bonus(text, student_operating_model)
            confidence = float(item.get("confidence", 0.0) or 0.0)
            salience = float(item.get("salience", 0.0) or 0.0)
            temporal_bonus = _temporal_weight(item) if key == "candidate_facts" else 0.0
            decision_bonus = 0.18 if key == "memory_items" and str(item.get("memory_type", "") or "").strip().lower() == "decision_record" else 0.0
            match_score = round(overlap + confidence + salience + temporal_bonus + operating_bonus + decision_bonus, 4)
            enriched = dict(item)
            enriched["match_score"] = match_score
            enriched["retrieval_reason"] = {
                "query_profile_overlap": round(overlap, 4),
                "matched_terms": matched_terms,
                "confidence": round(confidence, 4),
                "salience": round(salience, 4),
                "temporal_bonus": round(temporal_bonus, 4),
                "operating_model_bonus": operating_bonus,
                "operating_model_hits": operating_hits,
                "decision_bonus": round(decision_bonus, 4),
            }
            scored.append(enriched)
        scored.sort(key=lambda item: float(item.get("match_score", 0.0) or 0.0), reverse=True)
        reranked[key] = scored
    return reranked


def _saved_recommendation_status_weight(item: dict[str, Any]) -> float:
    metadata = item.get("metadata", {}) or {}
    outcome_status = str(metadata.get("outcome_status") or metadata.get("status") or "active").strip().lower()
    if outcome_status == "accepted":
        return 0.35
    if outcome_status == "completed":
        return 0.2
    if outcome_status == "postponed":
        return 0.05
    if outcome_status == "ignored":
        return -0.35
    return 0.1


def _rerank_saved_recommendations(
    saved_recommendations: list[dict[str, Any]],
    query: str,
    profile: dict[str, Any],
    student_operating_model: dict[str, Any],
    recommendation_outcome_profile: dict[str, Any],
) -> list[dict[str, Any]]:
    query_terms = _tokenize(query)
    profile_terms = _profile_signal_terms(profile)
    scored: list[dict[str, Any]] = []
    for item in saved_recommendations or []:
        metadata = item.get("metadata", {}) or {}
        recommendation_type = str(item.get("memory_type", "saved_plan")).replace("saved_", "")
        text = " ".join(
            [
                str(metadata.get("title", "")),
                str(item.get("summary", "")),
                " ".join(str(action) for action in (metadata.get("actions", []) or [])[:5]),
                str(metadata.get("follow_up_prompt", "")),
            ]
        )
        overlap, matched_terms = _overlap_score(text, query_terms, profile_terms)
        operating_bonus, operating_hits = _operating_model_bonus(text, student_operating_model)
        outcome_bonus, outcome_hits = _recommendation_outcome_bonus(text, recommendation_type, recommendation_outcome_profile)
        status_weight = _saved_recommendation_status_weight(item)
        retrieval_score = round(overlap + operating_bonus + outcome_bonus + status_weight, 4)
        enriched = dict(item)
        enriched["retrieval_score"] = retrieval_score
        enriched["retrieval_reason"] = {
            "query_profile_overlap": round(overlap, 4),
            "matched_terms": matched_terms,
            "operating_model_bonus": operating_bonus,
            "operating_model_hits": operating_hits,
            "outcome_profile_bonus": outcome_bonus,
            "outcome_profile_hits": outcome_hits,
            "status_weight": round(status_weight, 4),
        }
        scored.append(enriched)
    scored.sort(key=lambda item: float(item.get("retrieval_score", 0.0) or 0.0), reverse=True)
    return scored


def _build_retrieval_trace(
    context: RetrievalContext,
    memory: dict[str, Any],
    documents: list[dict[str, Any]],
    web_results: list[dict[str, Any]],
    saved_recommendations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    for item in documents[:5]:
        trace.append({
            "source": "documents",
            "label": item.get("filename", item.get("title", "document")),
            "score": float(item.get("retrieval_score", item.get("score", 0.0)) or 0.0),
            "reason": item.get("retrieval_reason", {}),
        })
    for item in web_results[:4]:
        trace.append({
            "source": "web",
            "label": item.get("title", item.get("url", "web_result")),
            "score": float(item.get("retrieval_score", 0.0) or 0.0),
            "reason": item.get("retrieval_reason", {}),
        })
    for item in (memory.get("candidate_facts", []) or [])[:4]:
        trace.append({
            "source": "candidate_facts",
            "label": item.get("value", item.get("fact_type", "candidate_fact")),
            "score": float(item.get("match_score", 0.0) or 0.0),
            "reason": item.get("retrieval_reason", {}),
        })
    for item in (saved_recommendations or [])[:3]:
        trace.append({
            "source": "saved_recommendations",
            "label": (item.get("metadata", {}) or {}).get("title", item.get("summary", "saved_recommendation")),
            "score": float(item.get("retrieval_score", 0.0) or 0.0),
            "reason": item.get("retrieval_reason", {}),
        })
    return trace


def _build_retrieval_diagnostics(
    profile: dict[str, Any],
    student_operating_model: dict[str, Any],
    recommendation_outcome_profile: dict[str, Any],
    memory: dict[str, Any],
    documents: list[dict[str, Any]],
    web_results: list[dict[str, Any]],
    evidence_quality: dict[str, Any],
) -> dict[str, Any]:
    profile_terms = sorted(_profile_signal_terms(profile))
    return {
        "profile_signal_terms": profile_terms[:20],
        "operating_model": dict(student_operating_model or {}),
        "recommendation_outcome_profile": dict(recommendation_outcome_profile or {}),
        "evidence_quality": dict(evidence_quality or {}),
        "candidate_fact_hits": len(memory.get("candidate_facts", []) or []),
        "memory_item_hits": len(memory.get("memory_items", []) or []),
        "document_hits": len(documents),
        "web_hits": len(web_results),
        "top_document": documents[0].get("filename", "") if documents else "",
        "top_web_result": web_results[0].get("url", "") if web_results else "",
    }


def _compute_evidence_quality_summary(
    query: str,
    domain: str,
    profile: dict[str, Any],
    documents: list[dict[str, Any]],
    web_results: list[dict[str, Any]],
    saved_recommendations: list[dict[str, Any]],
) -> dict[str, Any]:
    doc_scores = [
        float((item.get("retrieval_reason", {}) or {}).get("quality_score", 0.0) or 0.0)
        for item in (documents or [])[:5]
    ]
    web_scores = [
        float((item.get("retrieval_reason", {}) or {}).get("quality_score", _web_quality_score(item, profile)) or 0.0)
        for item in (web_results or [])[:5]
    ]
    saved_scores = [float(item.get("retrieval_score", 0.0) or 0.0) for item in (saved_recommendations or [])[:3]]
    official_web_hits = sum(
        1
        for item in (web_results or [])[:5]
        if str(((item.get("retrieval_reason", {}) or {}).get("trust_tier", "")).lower()) == "primary_official"
    )
    policy_aligned_hits = sum(
        1
        for item in (web_results or [])[:5]
        if float(((item.get("retrieval_reason", {}) or {}).get("policy_importance_bonus", 0.0) or 0.0) > 0.0)
    ) + sum(
        1
        for item in (documents or [])[:5]
        if float(((item.get("retrieval_reason", {}) or {}).get("policy_importance_bonus", 0.0) or 0.0) > 0.0)
    )
    document_trust_avg = round(sum(doc_scores) / max(1, len(doc_scores)), 4) if doc_scores else 0.0
    web_quality_avg = round(sum(web_scores) / max(1, len(web_scores)), 4) if web_scores else 0.0
    saved_recommendation_signal = round(sum(saved_scores) / max(1, len(saved_scores)), 4) if saved_scores else 0.0
    overall_quality = round(
        (document_trust_avg * 0.3) + (web_quality_avg * 0.5) + (min(1.0, saved_recommendation_signal / 3.0) * 0.2),
        4,
    )
    return {
        "query": query[:160],
        "domain": domain,
        "document_trust_avg": document_trust_avg,
        "web_quality_avg": web_quality_avg,
        "saved_recommendation_signal": saved_recommendation_signal,
        "official_web_hits": official_web_hits,
        "policy_aligned_hits": policy_aligned_hits,
        "overall_quality": overall_quality,
    }
