"""Shared layered-memory ingestion pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.adapters.embeddings.ollama import get_embeddings
from app.adapters.llm.lmstudio import get_text_llm
from app.adapters.neo4j.graph_store import (
    ensure_student,
    link_memory_to_evidence,
    mark_candidate_fact_promoted,
    store_candidate_fact,
    store_evidence,
    store_memory_item,
    update_student,
)
from app.core.prompts import MEMORY_INGESTION_EXTRACTION_PROMPT
from app.utils.json_extract import parse_json_object

log = logging.getLogger("pathfinder.memory.ingestion")

_EXTRACTION_PROMPT = MEMORY_INGESTION_EXTRACTION_PROMPT

_CORE_LABELS = {
    "goal": ("Goal", "HAS_GOAL"),
    "skill": ("Skill", "HAS_SKILL"),
    "interest": ("Interest", "INTERESTED_IN"),
    "course": ("Course", "TOOK"),
    "experience": ("Company", "WORKED_AT"),
    "project": ("Project", "COMPLETED"),
    "constraint": ("Constraint", "HAS_CONSTRAINT"),
    "preference": ("Preference", "HAS_PREFERENCE"),
    "behavior": ("BehavioralPattern", "HAS_BEHAVIOR"),
}

_AGGRESSIVE_PROMOTION_TYPES = {"goal", "skill", "interest", "preference"}
_AGGRESSIVE_PROMOTION_CONFIDENCE = 0.8
_AGGRESSIVE_PROMOTION_SALIENCE = 0.72


@dataclass(frozen=True)
class CandidateFactRecord:
    """Normalized candidate fact ready for storage."""

    fact_type: str
    value: str
    normalized_value: str
    confidence: float
    salience: float
    time_scope: str
    route: str
    stability: str
    evidence_kind: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ProfileFactRecord:
    """Unified durable profile fact projected from core entities or student properties."""

    fact_type: str
    value: str
    normalized_value: str
    source_kind: str
    stability: str
    confidence: float
    status: str
    metadata: dict[str, Any]


def _title_case_words(value: str) -> str:
    return " ".join(part.capitalize() for part in value.split() if part)


def _semantic_fact_key(fact_type: str, value: str) -> str:
    text = _clean_candidate_value(fact_type, value).casefold()
    if not text:
        return ""
    if fact_type == "goal":
        replacements = {
            "obtain": "get",
            "seeking": "get",
            "looking": "get",
            "want": "get",
            "wanting": "get",
            "enter": "industry",
            "entering": "industry",
            "internships": "internship",
            "roles": "role",
            "jobs": "job",
        }
        stopwords = {"to", "a", "an", "the", "and", "go", "into", "first", "for", "my"}
        tokens = []
        for token in re.findall(r"[a-z0-9]+", text):
            mapped = replacements.get(token, token)
            if mapped not in stopwords:
                tokens.append(mapped)
        return " ".join(sorted(dict.fromkeys(tokens)))
    if fact_type in {"preference", "constraint", "interest"}:
        tokens = [token for token in re.findall(r"[a-z0-9]+", text) if token not in {"a", "an", "the", "my"}]
        return " ".join(sorted(dict.fromkeys(tokens)))
    return text


def _semantic_fact_tokens(fact_type: str, value: str) -> set[str]:
    key = _semantic_fact_key(fact_type, value)
    return {token for token in key.split() if token}


def _facts_are_semantic_duplicates(existing: dict[str, Any], candidate: dict[str, Any]) -> bool:
    fact_type = str(candidate.get("fact_type") or existing.get("fact_type") or "").lower()
    if not fact_type or fact_type != str(existing.get("fact_type") or "").lower():
        return False
    if fact_type == "goal":
        existing_tokens = _semantic_fact_tokens(fact_type, str(existing.get("value", "")))
        candidate_tokens = _semantic_fact_tokens(fact_type, str(candidate.get("value", "")))
        if not existing_tokens or not candidate_tokens:
            return False
        overlap = len(existing_tokens & candidate_tokens)
        union = len(existing_tokens | candidate_tokens)
        if union == 0:
            return False
        similarity = overlap / union
        return similarity >= 0.8 or existing_tokens.issubset(candidate_tokens) or candidate_tokens.issubset(existing_tokens)
    return _semantic_fact_key(fact_type, str(existing.get("value", ""))) == _semantic_fact_key(
        fact_type, str(candidate.get("value", ""))
    )


def _fact_preference_score(fact: dict[str, Any]) -> tuple[float, int, int]:
    metadata = _metadata_dict(fact.get("metadata"))
    source = str(metadata.get("source") or "").strip().lower()
    confidence = _safe_float(fact.get("confidence"), 0.5)
    cleaned_value = _clean_candidate_value(str(fact.get("fact_type") or ""), str(fact.get("value") or ""))
    source_bonus = 1 if source == "heuristic_extraction" else 0
    return (confidence, source_bonus, len(cleaned_value))


def _merge_candidate_fact(existing: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    preferred = candidate if _fact_preference_score(candidate) >= _fact_preference_score(existing) else existing
    other = existing if preferred is candidate else candidate
    merged_metadata = {
        **_metadata_dict(other.get("metadata")),
        **_metadata_dict(preferred.get("metadata")),
    }
    merged_metadata.setdefault("merged_values", [])
    merged_values = [value for value in merged_metadata["merged_values"] if isinstance(value, str) and value.strip()]
    for value in (str(existing.get("value", "")).strip(), str(candidate.get("value", "")).strip()):
        if value and value != str(preferred.get("value", "")).strip() and value not in merged_values:
            merged_values.append(value)
    if merged_values:
        merged_metadata["merged_values"] = merged_values
    return {
        **other,
        **preferred,
        "confidence": max(_safe_float(existing.get("confidence"), 0.5), _safe_float(candidate.get("confidence"), 0.5)),
        "salience": max(_safe_float(existing.get("salience"), 0.5), _safe_float(candidate.get("salience"), 0.5)),
        "metadata": merged_metadata,
    }


def _clean_candidate_value(fact_type: str, value: str) -> str:
    text = (value or "").strip().rstrip(".")
    if not text:
        return ""
    if fact_type == "goal":
        text = re.sub(
            r"^(my current (main )?goal is|my goal is|goal:|seeking|looking for|aiming for|want(?:ing)?|want to)\s+",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"\binternships\b", "internship", text, flags=re.IGNORECASE)
        text = re.sub(r"\bjobs\b", "job", text, flags=re.IGNORECASE)
        text = re.sub(r"\broles\b", "role", text, flags=re.IGNORECASE)
    elif fact_type in {"preference", "interest"}:
        text = re.sub(r"^(i prefer|prefer|interested in)\s+", "", text, flags=re.IGNORECASE)
    elif fact_type == "skill":
        text = re.sub(r"^(skills?( include)?|strongest in|experienced in|skilled in|i know)\s+", "", text, flags=re.IGNORECASE)
    elif fact_type == "constraint":
        text = re.sub(r"^(constraint:|i can only|i have)\s+", "", text, flags=re.IGNORECASE)
    return text.strip()


def _classify_fact_stability(fact_type: str, value: str, metadata: dict[str, Any], time_scope: str) -> str:
    explicit = str(metadata.get("stability", "") or "").strip().lower()
    if explicit in {"stable", "evolving", "temporary"}:
        return explicit
    lowered = value.casefold()
    if time_scope == "short_term":
        return "temporary"
    if fact_type in {"goal", "interest", "preference", "constraint", "behavior"}:
        if any(token in lowered for token in ("this semester", "right now", "currently", "for now", "temporarily")):
            return "temporary"
        return "evolving"
    return "stable"


def _evidence_kind(metadata: dict[str, Any]) -> str:
    explicit = str(metadata.get("evidence_kind", "") or "").strip().lower()
    if explicit in {"direct_statement", "document_fact", "inference"}:
        return explicit
    if bool(metadata.get("is_direct_statement")):
        return "direct_statement"
    return "inference"


def _normalize_fact_metadata(
    *,
    fact_type: str,
    value: str,
    route: str,
    time_scope: str,
    metadata: dict[str, Any] | None,
) -> tuple[str, str, str, dict[str, Any]]:
    base = dict(metadata) if isinstance(metadata, dict) else {}
    normalized_value = str(base.get("normalized_value") or _semantic_fact_key(fact_type, value) or value).strip()
    evidence_kind = _evidence_kind(base)
    stability = _classify_fact_stability(fact_type, value, base, time_scope)
    if route == "resolved_core" and stability == "temporary":
        stability = "evolving"
    base["normalized_value"] = normalized_value
    base["stability"] = stability
    base["evidence_kind"] = evidence_kind
    base["is_direct_statement"] = evidence_kind == "direct_statement"
    return normalized_value, stability, evidence_kind, base


def _clean_student_property(key: str, value: str) -> str:
    text = (value or "").strip().rstrip(".")
    if not text:
        return ""
    if key == "email":
        return text.lower()
    if key == "gpa":
        match = re.search(r"\b([0-4](?:\.\d{1,2})?)\b", text)
        return match.group(1) if match else ""
    if key == "semester":
        digit_match = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", text, re.IGNORECASE)
        if digit_match:
            return digit_match.group(1)
        return text
    if key in {"name", "program"}:
        return _title_case_words(text)
    return text


def _heuristic_student_properties(text: str) -> dict[str, str]:
    properties: dict[str, str] = {}
    patterns = {
        "email": [
            r"\b([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})\b",
        ],
        "gpa": [
            r"\bgpa(?: is|:)?\s*([0-4](?:\.\d{1,2})?)\b",
            r"\b([0-4](?:\.\d{1,2})?)\s*gpa\b",
        ],
        "semester": [
            r"\b(?:i am in|i'm in|currently in|in)\s+my\s+(\d{1,2})(?:st|nd|rd|th)?\s+semester\b",
            r"\bsemester(?: is|:)?\s*(\d{1,2})\b",
        ],
        "name": [
            r"\b(?:my name is|i am|i'm)\s+([A-Za-z]+(?:\s+[A-Za-z]+){0,2})\b",
        ],
        "university": [
            r"\b(?:student at|study at|studying at|at)\s+([A-Z][A-Za-z0-9&,\- ]{4,80})",
        ],
        "program": [
            r"\b(?:a|an)\s+([A-Za-z][A-Za-z&/ +\-]{2,60})\s+student\b",
            r"\bmajor(?:ing)? in\s+([A-Za-z][A-Za-z&/ +\-]{2,60})\b",
            r"\bprogram(?: is|:)?\s+([A-Za-z][A-Za-z&/ +\-]{2,60})\b",
        ],
    }

    for key, regexes in patterns.items():
        for pattern in regexes:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            cleaned = _clean_student_property(key, match.group(1))
            if cleaned:
                properties[key] = cleaned
                break
    return properties


def _heuristic_candidate_facts(text: str) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    patterns = [
        ("goal", r"\b(?:my current (?:main )?goal is|my goal is|i want to|i'm aiming for|i am aiming for|seeking)\s+([^.;\n]+)"),
        ("preference", r"\b(?:i prefer|my preference is|i'd prefer)\s+([^.;\n]+)"),
        ("constraint", r"\b(?:i can only|i have limited|my budget is|i need)\s+([^.;\n]+)"),
        ("skill", r"\b(?:skills? include|strongest in|experienced in|skilled in|i know)\s+([^.;\n]+)"),
    ]
    for fact_type, pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            raw_value = match.group(1).strip()
            value = _clean_candidate_value(fact_type, raw_value)
            if not value:
                continue
            facts.append(
                {
                    "fact_type": fact_type,
                    "value": value,
                    "confidence": 0.82 if fact_type in {"goal", "preference", "constraint"} else 0.78,
                    "salience": 0.8 if fact_type in {"goal", "preference", "constraint"} else 0.72,
                    "time_scope": "long_term",
                    "route": "resolved_core" if fact_type in _CORE_LABELS else "candidate_structured",
                    "metadata": {
                        "source": "heuristic_extraction",
                        "source_span": raw_value,
                        "evidence_kind": "direct_statement",
                        "is_direct_statement": True,
                    },
                }
            )
    return facts


def _merge_student_updates(*updates: dict[str, Any]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for update_map in updates:
        for key, value in (update_map or {}).items():
            cleaned = _clean_student_property(key, str(value))
            if cleaned:
                merged[key] = cleaned
    return merged


def _normalize_candidate_fact(fact: dict[str, Any], student_updates: dict[str, str]) -> list[dict[str, Any]]:
    fact_type = str(fact.get("fact_type", "generic")).lower().strip()
    value = _clean_candidate_value(fact_type, str(fact.get("value", "")))
    if not value:
        return []
    if fact_type == "identity" and any(student_updates.get(key) for key in ("name", "university", "program", "semester", "gpa", "email")):
        return []

    route = fact.get("route", "candidate_structured")
    confidence = _safe_float(fact.get("confidence"), 0.6)
    salience = _safe_float(fact.get("salience"), 0.6)
    time_scope = fact.get("time_scope", "long_term")
    normalized_value, stability, evidence_kind, metadata = _normalize_fact_metadata(
        fact_type=fact_type,
        value=value,
        route=route,
        time_scope=time_scope,
        metadata=_metadata_dict(fact.get("metadata")),
    )
    normalized_facts: list[dict[str, Any]] = []

    for expanded_value in _expand_core_values(fact_type, value):
        cleaned = _clean_candidate_value(fact_type, expanded_value)
        if not cleaned:
            continue
        normalized_facts.append(
            {
                "fact_type": fact_type,
                "value": cleaned,
                "confidence": confidence,
                "salience": salience,
                "time_scope": time_scope,
                "route": route,
                "normalized_value": normalized_value or _semantic_fact_key(fact_type, cleaned),
                "stability": stability,
                "evidence_kind": evidence_kind,
                "metadata": metadata,
            }
        )
    return normalized_facts


def _prepare_extraction(text: str, extraction: dict[str, Any]) -> dict[str, Any]:
    heuristic_properties = _heuristic_student_properties(text)
    heuristic_facts = _heuristic_candidate_facts(text)
    student_updates = _merge_student_updates(extraction.get("student_properties", {}), heuristic_properties)

    candidate_facts: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for fact in [*(extraction.get("candidate_facts", []) or []), *heuristic_facts]:
        for normalized in _normalize_candidate_fact(fact, student_updates):
            key = (normalized["fact_type"], _semantic_fact_key(normalized["fact_type"], normalized["value"]))
            if key in seen:
                continue
            duplicate_index = next(
                (
                    idx
                    for idx, existing in enumerate(candidate_facts)
                    if _facts_are_semantic_duplicates(existing, normalized)
                ),
                None,
            )
            if duplicate_index is not None:
                candidate_facts[duplicate_index] = _merge_candidate_fact(candidate_facts[duplicate_index], normalized)
                seen.add(
                    (
                        candidate_facts[duplicate_index]["fact_type"],
                        _semantic_fact_key(
                            candidate_facts[duplicate_index]["fact_type"],
                            candidate_facts[duplicate_index]["value"],
                        ),
                    )
                )
                continue
            seen.add(key)
            candidate_facts.append(normalized)

    generic_memories = []
    seen_memory: set[tuple[str, str]] = set()
    for memory in extraction.get("generic_memories", []) or []:
        summary = str(memory.get("summary", "")).strip().rstrip(".")
        if not summary:
            continue
        key = (str(memory.get("memory_type", "generic")).lower(), summary.casefold())
        if key in seen_memory:
            continue
        seen_memory.add(key)
        generic_memories.append(
            {
                **memory,
                "summary": summary,
                "confidence": _safe_float(memory.get("confidence"), 0.55),
                "salience": _safe_float(memory.get("salience"), 0.55),
            }
        )

    return {
        "student_properties": student_updates,
        "candidate_facts": candidate_facts,
        "generic_memories": generic_memories,
    }



def _expand_core_values(fact_type: str, value: str) -> list[str]:
    text = _clean_candidate_value(fact_type, value)
    if not text:
        return []
    if fact_type not in {"skill", "interest"}:
        return [text]
    normalized = re.sub(r"\s+(and|&)\s+", ",", text, flags=re.IGNORECASE)
    parts = [part.strip(" .") for part in normalized.split(",")]
    unique: list[str] = []
    seen: set[str] = set()
    for part in parts:
        key = part.casefold()
        if part and key not in seen:
            unique.append(part)
            seen.add(key)
    return unique or [text]


def _safe_float(value: Any, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _should_promote_candidate_structured(
    fact_type: str,
    route: str,
    confidence: float,
    salience: float,
    stored_fact: dict[str, Any] | None = None,
) -> bool:
    """Promote high-confidence structured facts into core nodes when safe."""
    if route == "resolved_core":
        return fact_type in _CORE_LABELS
    if route != "candidate_structured":
        return False
    if fact_type not in _AGGRESSIVE_PROMOTION_TYPES:
        return False
    stored_fact = stored_fact or {}
    support_count = int(stored_fact.get("support_count") or 0)
    direct_statement_count = int(stored_fact.get("direct_statement_count") or 0)
    document_support_count = int(stored_fact.get("document_support_count") or 0)
    promotion_score = _safe_float(stored_fact.get("promotion_score"), 0.0)
    if confidence >= _AGGRESSIVE_PROMOTION_CONFIDENCE and salience >= _AGGRESSIVE_PROMOTION_SALIENCE:
        return True
    if direct_statement_count > 0 and confidence >= 0.76 and promotion_score >= 0.72:
        return True
    if support_count >= 2 and promotion_score >= 0.74:
        return True
    if document_support_count > 0 and confidence >= 0.7 and salience >= 0.68:
        return True
    return False


async def ingest_memory(
    *,
    student_id: str,
    source_type: str,
    content: str,
    source_ref: str | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ingest new information into Pathfinder's layered memory."""
    await ensure_student(student_id)

    text = (content or "").strip()
    if not text:
        return {"evidence": None, "candidate_facts": [], "memory_items": [], "student_updates": {}}

    embeddings = get_embeddings()
    embedding = embeddings.embed_query(text[:4000])

    evidence = await store_evidence(
        student_id,
        source_type,
        text[:12000],
        source_ref=source_ref,
        session_id=session_id,
        metadata=metadata or {},
        embedding=embedding,
    )

    extraction = _prepare_extraction(text, await _extract_memory_candidates(text))
    student_updates = extraction.get("student_properties", {})
    if student_updates:
        await update_student(student_id, **student_updates)

    candidate_results: list[dict[str, Any]] = []
    memory_results: list[dict[str, Any]] = []
    promoted_entities: list[dict[str, Any]] = []
    seen_fact_keys: set[tuple[str, str]] = set()

    for fact in extraction.get("candidate_facts", []):
        route = fact.get("route", "candidate_structured")
        fact_type = str(fact.get("fact_type", "generic")).lower()
        value = str(fact.get("value", "")).strip()
        if not value:
            continue
        if fact_type == "identity" and any(student_updates.get(key) for key in ("name", "university", "program", "semester", "gpa", "email")):
            continue

        confidence = _safe_float(fact.get("confidence"), 0.6)
        salience = _safe_float(fact.get("salience"), 0.6)
        status = "resolved" if route == "resolved_core" else "candidate"
        normalized_value = str(fact.get("normalized_value") or _semantic_fact_key(fact_type, value) or value).strip()
        stability = str(fact.get("stability") or "evolving").strip().lower()
        fact_metadata = _metadata_dict(fact.get("metadata"))
        evidence_kind = str(fact.get("evidence_kind") or _evidence_kind(fact_metadata)).strip().lower()

        fact_key = (fact_type, _semantic_fact_key(fact_type, value))
        if fact_key in seen_fact_keys:
            continue
        seen_fact_keys.add(fact_key)
        fact_embedding = embeddings.embed_query(value)
        stored_fact = await store_candidate_fact(
            student_id,
            fact_type,
            value,
            source_ref=evidence["id"],
            confidence=confidence,
            salience=salience,
            status=status,
            time_scope=fact.get("time_scope", "long_term"),
            normalized_value=normalized_value,
            stability=stability,
            evidence_kind=evidence_kind,
            metadata=fact_metadata,
            embedding=fact_embedding,
            source_type=source_type,
        )
        await link_memory_to_evidence("CandidateFact", stored_fact["id"], evidence["id"])
        candidate_results.append(stored_fact)

        if _should_promote_candidate_structured(fact_type, route, confidence, salience, stored_fact):
            promoted_list = await _promote_to_core(student_id, fact_type, value, stored_fact)
            if promoted_list:
                stored_fact = await mark_candidate_fact_promoted(stored_fact["id"])
                candidate_results[-1] = stored_fact
                promoted_entities.extend(promoted_list)

    for memory in extraction.get("generic_memories", []):
        route = memory.get("route", "generic_long_term")
        if route == "short_term_only":
            continue
        summary = str(memory.get("summary", "")).strip()
        if not summary:
            continue
        mem_embedding = embeddings.embed_query(summary)
        stored_memory = await store_memory_item(
            student_id,
            str(memory.get("memory_type", "generic")),
            summary,
            source_ref=evidence["id"],
            confidence=_safe_float(memory.get("confidence"), 0.55),
            salience=_safe_float(memory.get("salience"), 0.55),
            status="candidate",
            time_scope=memory.get("time_scope", "long_term"),
            tags=memory.get("tags", []),
            metadata=_metadata_dict(memory.get("metadata")),
            embedding=mem_embedding,
        )
        await link_memory_to_evidence("MemoryItem", stored_memory["id"], evidence["id"])
        memory_results.append(stored_memory)

    consolidation_needed = bool(candidate_results or memory_results or promoted_entities)

    return {
        "evidence": evidence,
        "candidate_facts": candidate_results,
        "memory_items": memory_results,
        "promoted_entities": promoted_entities,
        "student_updates": student_updates,
        "consolidation_needed": consolidation_needed,
    }


async def _extract_memory_candidates(text: str) -> dict[str, Any]:
    """Use the LLM to extract candidate memory objects."""
    llm = get_text_llm()
    response = await llm.ainvoke(
        [
            SystemMessage(content=_EXTRACTION_PROMPT),
            HumanMessage(content=text[:6000]),
        ]
    )
    content = response.content if isinstance(response.content, str) else str(response.content)
    try:
        parsed = parse_json_object(content)
        if isinstance(parsed, dict):
            return parsed
    except Exception as exc:
        log.warning("Memory extraction parse failed: %s", exc)
    return {"student_properties": {}, "candidate_facts": [], "generic_memories": []}


async def _promote_to_core(
    student_id: str, fact_type: str, value: str, stored_fact: dict[str, Any]
) -> list[dict[str, Any]]:
    """Promote a high-confidence candidate fact into the controlled core ontology."""
    from app.adapters.neo4j.graph_store import create_entity

    label_rel = _CORE_LABELS.get(fact_type)
    if not label_rel:
        return []
    label, relationship = label_rel
    promoted: list[dict[str, Any]] = []
    metadata = _metadata_dict(stored_fact.get("metadata"))
    for expanded_value in _expand_core_values(fact_type, value):
        properties = {
            "name": expanded_value,
            "student_id": student_id,
            "confidence": stored_fact.get("confidence", 0.0),
            "source_kind": "candidate_fact",
            "confirmation_state": "confirmed",
            "promoted_from_candidate_id": stored_fact.get("id", ""),
            "support_count": stored_fact.get("support_count", metadata.get("support_count", 1)),
            "direct_statement_count": stored_fact.get(
                "direct_statement_count", metadata.get("direct_statement_count", 0)
            ),
            "document_support_count": stored_fact.get(
                "document_support_count", metadata.get("document_support_count", 0)
            ),
            "revision_count": stored_fact.get("revision_count", metadata.get("revision_count", 1)),
            "promotion_score": stored_fact.get("promotion_score", 0.0),
            **metadata,
        }
        entity = await create_entity(label, properties, student_id, relationship)
        if entity:
            entity["_label"] = label
            promoted.append(entity)
    return promoted


def _metadata_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}
