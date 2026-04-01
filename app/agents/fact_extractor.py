"""Node: Fact Extractor.

Converts mixed web/profile/document context into structured evidence
records that downstream planners can reason over safely.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.adapters.llm.lmstudio import get_text_llm
from app.core.quality import (
    EvidenceRecord,
    academic_source_relevance,
    analyze_query_focus,
    classify_web_source,
    course_code_matches_level,
    extract_course_entries,
    extract_course_codes,
    extract_terms,
    extract_units,
    has_deadline_language,
    infer_target_level,
    infer_target_program,
    is_academic_source_relevant,
    looks_like_course_catalog_source,
)
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.fact_extractor")

_FACT_PROMPT = """You extract structured evidence records from trusted context for Pathfinder.

Return ONLY valid JSON in this form:
{
  "records": [
    {
      "source_type": "degree_page|schedule_page|admissions_page|certificate_page|job_page|profile_doc|general_web",
      "entity_type": "course|requirement|certificate|prerequisite|availability|deadline|job_role|skill|program_constraint",
      "value": {"name": "...", "code": "...", "details": "...", "units": 3, "terms": ["Fall 2026"], "kind": "..."},
      "source_url": "https://...",
      "source_title": "Page title",
      "excerpt": "short supporting excerpt",
      "confidence": 0.0,
      "time_scope": "catalog|live_schedule|timeless|unclear"
    }
  ]
}

Rules:
1. Only extract facts directly supported by the provided source text.
2. Preserve uncertainty and conflicting facts as separate records.
3. For academic pages, extract concrete course codes, requirement summaries, unit counts, prerequisite language, and availability details when present.
4. For job pages, extract role names, major skills, location/work-mode details, and any explicit requirements.
5. For comparison or summary questions, still keep facts atomic rather than writing prose summaries.
4. Use "profile_doc" for transcript/resume/document excerpts.
5. Keep excerpts short and specific.
6. Do not invent URLs, courses, or requirements.
"""


async def fact_extractor(state: PathfinderState) -> PathfinderState:
    """Build typed evidence records from available context."""
    profile = state.get("profile_data", {})
    web_results = state.get("web_results", [])
    documents = state.get("retrieved_documents", [])
    query = state.get("query", "")
    session_summary = state.get("session_summary", {})
    source_policy = state.get("source_policy", {})
    query_focus = analyze_query_focus(query)
    program_text = infer_target_program(profile, session_summary, query)
    level = infer_target_level(profile, session_summary, query)

    step_progress = list(state.get("step_progress", []))
    step_progress.append("Extracting grounded facts from sources...")

    heuristic_records = _heuristic_records(profile, documents, web_results, query_focus, program_text, level, source_policy)
    llm_records = await _llm_records(query, profile, documents, web_results, query_focus)

    evidence_records = _filter_records_for_context(
        _dedupe_records(heuristic_records + llm_records),
        program_text,
        level,
    )

    step_progress.append(f"Structured {len(evidence_records)} evidence records")
    log.info("Fact extractor produced %d evidence records", len(evidence_records))

    return {
        **state,
        "evidence_records": evidence_records,
        "step_progress": step_progress,
        "next_node": _determine_next(state),
    }


async def _llm_records(
    query: str,
    profile: dict[str, Any],
    documents: list[dict[str, Any]],
    web_results: list[dict[str, Any]],
    query_focus: dict[str, Any],
) -> list[EvidenceRecord]:
    """Use the LLM to extract higher-level evidence from mixed context."""
    context_parts = []

    if profile:
        personal = profile.get("personal", {})
        context_parts.append("PROFILE:\n" + json.dumps({
            "personal": personal,
            "courses": profile.get("courses", [])[:10],
            "skills": profile.get("skills", [])[:10],
            "goals": profile.get("goals", [])[:10],
        }, ensure_ascii=True))

    for doc in documents[:5]:
        context_parts.append(
            "DOCUMENT:\n" + json.dumps({
                "filename": doc.get("filename", ""),
                "page_number": doc.get("page_number"),
                "text": doc.get("text", "")[:800],
            }, ensure_ascii=True)
        )

    for web in web_results[:8]:
        source_type, time_scope = classify_web_source(
            web.get("url", ""),
            web.get("title", ""),
            web.get("content", ""),
        )
        context_parts.append(
            "WEB:\n" + json.dumps({
                "source_type": source_type,
                "time_scope": time_scope,
                "title": web.get("title", ""),
                "url": web.get("url", ""),
                "content": web.get("content", "")[:1800],
            }, ensure_ascii=True)
        )

    if not context_parts:
        return []

    llm = get_text_llm()
    response = await llm.ainvoke([
        SystemMessage(content=_FACT_PROMPT),
        HumanMessage(content=(
            f"User query:\n{query}\n\n"
            f"Query focus:\n{json.dumps(query_focus, ensure_ascii=True)}\n\n"
            "Context:\n" + "\n\n".join(context_parts[:12])
        )),
    ])

    content = response.content if isinstance(response.content, str) else str(response.content)
    try:
        json_start = content.find("{")
        json_end = content.rfind("}") + 1
        parsed = json.loads(content[json_start:json_end])
        records = parsed.get("records", [])
        return [r for r in records if isinstance(r, dict)]
    except Exception as exc:
        log.warning("Fact extractor LLM parse failed: %s", exc)
        return []


def _heuristic_records(
    profile: dict[str, Any],
    documents: list[dict[str, Any]],
    web_results: list[dict[str, Any]],
    query_focus: dict[str, Any],
    program_text: str,
    level: str,
    source_policy: dict[str, Any] | None = None,
) -> list[EvidenceRecord]:
    """Lightweight deterministic evidence extraction."""
    records: list[EvidenceRecord] = []

    for course in profile.get("courses", [])[:20]:
        code = course.get("code") or course.get("name", "")
        name = course.get("name") or course.get("code", "")
        if code or name:
            records.append({
                "source_type": "profile_doc",
                "entity_type": "course",
                "value": {"code": code, "name": name, "origin": "student_profile", "completed": True},
                "source_url": "",
                "source_title": "Student profile",
                "excerpt": f"Recorded completed course: {code or name}",
                "confidence": 0.98,
                "time_scope": "timeless",
            })

    for skill in profile.get("skills", [])[:20]:
        if skill.get("name"):
            records.append({
                "source_type": "profile_doc",
                "entity_type": "skill",
                "value": {
                    "name": skill.get("name", ""),
                    "origin": "student_profile",
                    "proficiency": skill.get("proficiency", ""),
                },
                "source_url": "",
                "source_title": "Student profile",
                "excerpt": f"Recorded skill: {skill.get('name', '')}",
                "confidence": 0.98,
                "time_scope": "timeless",
            })

    for doc in documents[:5]:
        text = doc.get("text", "")
        for code in extract_course_codes(text):
            records.append({
                "source_type": "profile_doc",
                "entity_type": "course",
                "value": {"code": code, "origin": "retrieved_document", "completed": True},
                "source_url": "",
                "source_title": doc.get("filename", "Document"),
                "excerpt": text[:220],
                "confidence": 0.75,
                "time_scope": "timeless",
            })

    source_policy = source_policy or {}
    primary_types = set(source_policy.get("primary_source_types", []))
    secondary_types = set(source_policy.get("secondary_source_types", []))

    for web in web_results[:8]:
        title = web.get("title", "")
        url = web.get("url", "")
        content = web.get("content", "")
        combined = f"{title}\n{content}"
        source_type, time_scope = classify_web_source(url, title, content)
        if primary_types and source_type not in primary_types and source_type not in secondary_types:
            continue
        academic_relevant = source_type not in {"degree_page", "schedule_page", "certificate_page", "admissions_page", "general_web"} or (
            query_focus.get("primary") != "academic"
        ) or is_academic_source_relevant(title, content, url, program_text, level)
        if source_type == "certificate_page" and query_focus.get("primary") in {"academic", "comparison"} and extract_course_codes(combined):
            academic_relevant = True

        if query_focus.get("primary") == "academic" and source_type in {"degree_page", "schedule_page", "certificate_page", "admissions_page", "general_web"} and not academic_relevant:
            continue

        course_entries = extract_course_entries(combined)
        codes = [entry["code"] for entry in course_entries] or extract_course_codes(combined)
        units = extract_units(combined)
        terms = extract_terms(combined)
        entry_name_by_code = {entry["code"]: entry["name"] for entry in course_entries}
        for code in codes[:12]:
            if not course_code_matches_level(code, level, title, content):
                continue
            entity_type = "availability" if source_type == "schedule_page" else "course"
            records.append({
                "source_type": source_type,
                "entity_type": entity_type,
                "value": {
                    "code": code,
                    "name": entry_name_by_code.get(code, ""),
                    "details": title,
                    "units": units[:2],
                    "terms": terms[:3],
                    "kind": (
                        "course_catalog_entry"
                        if looks_like_course_catalog_source(title, url) and entity_type == "course"
                        else "live_section" if entity_type == "availability" else "catalog_entry"
                    ),
                },
                "source_url": url,
                "source_title": title,
                "excerpt": content[:240],
                "confidence": 0.7 if source_type == "schedule_page" else 0.8,
                "time_scope": time_scope,
            })

        lowered = f"{title} {content}".lower()
        if ("require" in lowered or "units" in lowered or "breadth" in lowered) and academic_relevant:
            records.append({
                "source_type": source_type,
                "entity_type": "requirement",
                "value": {
                    "summary": title,
                    "units": units[:4],
                    "kind": "program_requirement",
                },
                "source_url": url,
                "source_title": title,
                "excerpt": content[:240],
                "confidence": 0.7,
                "time_scope": time_scope,
            })

        if source_type == "job_page" and title:
            records.append({
                "source_type": source_type,
                "entity_type": "job_role",
                "value": {
                    "name": title,
                    "work_mode": _extract_work_mode(lowered),
                    "location_hint": _extract_location_hint(content),
                },
                "source_url": url,
                "source_title": title,
                "excerpt": content[:240],
                "confidence": 0.7,
                "time_scope": time_scope,
            })

        if any(keyword in lowered for keyword in ("fully classified", "deficienc", "prerequisite", "admission requirement")) and academic_relevant:
            records.append({
                "source_type": source_type,
                "entity_type": "prerequisite" if "prerequisite" in lowered else "program_constraint",
                "value": {
                    "summary": title,
                    "constraint_text": content[:180],
                    "kind": "prerequisite" if "prerequisite" in lowered else "program_constraint",
                },
                "source_url": url,
                "source_title": title,
                "excerpt": content[:240],
                "confidence": 0.72,
                "time_scope": time_scope,
            })

        if has_deadline_language(combined):
            records.append({
                "source_type": source_type,
                "entity_type": "deadline",
                "value": {
                    "summary": title,
                    "terms": terms[:2],
                    "kind": "deadline_or_due_date",
                },
                "source_url": url,
                "source_title": title,
                "excerpt": content[:240],
                "confidence": 0.68,
                "time_scope": time_scope,
            })

        if source_type == "certificate_page" and query_focus.get("primary") in {"academic", "comparison"} and academic_relevant:
            records.append({
                "source_type": source_type,
                "entity_type": "certificate",
                "value": {
                    "name": title,
                    "units": units[:2],
                    "kind": "related_certificate",
                },
                "source_url": url,
                "source_title": title,
                "excerpt": content[:240],
                "confidence": 0.7,
                "time_scope": time_scope,
            })

    return records


def _filter_records_for_context(
    records: list[EvidenceRecord],
    program_text: str,
    level: str,
) -> list[EvidenceRecord]:
    """Drop academic records that do not match the student's program context."""
    filtered: list[EvidenceRecord] = []
    for record in records:
        source_type = record.get("source_type", "")
        entity_type = record.get("entity_type", "")
        title = record.get("source_title", "")
        excerpt = record.get("excerpt", "")
        url = record.get("source_url", "")

        if source_type in {"degree_page", "schedule_page", "certificate_page", "admissions_page", "general_web"} and entity_type in {
            "course", "availability", "requirement", "certificate", "prerequisite", "program_constraint"
        }:
            is_relevant = is_academic_source_relevant(title, excerpt, url, program_text, level)
            if source_type == "certificate_page" and entity_type in {"course", "certificate"} and record.get("value", {}).get("code", ""):
                is_relevant = True
            if not is_relevant:
                continue
            code = str((record.get("value", {}) or {}).get("code", ""))
            if code and not course_code_matches_level(code, level, title, excerpt):
                continue

        filtered.append(record)
    return filtered


def _dedupe_records(records: list[EvidenceRecord]) -> list[EvidenceRecord]:
    """Deduplicate evidence records conservatively."""
    deduped: list[EvidenceRecord] = []
    seen: set[tuple[str, str, str, str]] = set()

    for record in records:
        key = (
            record.get("entity_type", ""),
            json.dumps(record.get("value", {}), sort_keys=True),
            record.get("source_url", ""),
            record.get("time_scope", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)

    return deduped


def _extract_work_mode(text: str) -> str:
    if "remote" in text:
        return "remote"
    if "hybrid" in text:
        return "hybrid"
    if "on-site" in text or "onsite" in text:
        return "onsite"
    return ""


def _extract_location_hint(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:8]:
        if "," in line and len(line) < 80:
            return line
    return ""


def _determine_next(state: PathfinderState) -> str:
    """Determine next node after fact extraction."""
    plan = state.get("plan", [])
    try:
        idx = plan.index("fact_extractor")
        if idx + 1 < len(plan):
            return plan[idx + 1]
    except ValueError:
        pass
    return "evaluator"
