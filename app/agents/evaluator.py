"""Node 10: Evaluator.

Checks the draft answer for groundedness, assigns a confidence score,
detects hallucinations, and passively learns profile updates from the conversation.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage

from app.adapters.llm.lmstudio import get_text_llm
from app.adapters.neo4j.graph_store import store_extracted_entities, update_student
from app.core.quality import (
    DecisionPayload,
    add_working_memory_item,
    complete_task,
    init_working_memory,
    summarize_trace,
)
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.evaluator")

_EVALUATION_PROMPT = """You are the Evaluator agent in Pathfinder. Your job is to assess the quality of a draft answer.

Evaluate the draft answer against the available sources and respond with JSON:
{{
    "is_grounded": true/false,
    "confidence_score": 0.0 to 1.0,
    "issues": ["list of any issues found"],
    "profile_updates": [
        {{"field": "FIELD_TYPE", "value": "detected value", "source": "conversation"}}
    ],
    "needs_disclaimer": true/false,
    "disclaimer": "optional disclaimer text if the answer contains uncertain claims"
}}

Scoring guide:
- 1.0: Every claim is directly supported by sources
- 0.8-0.9: Most claims supported, minor inferences
- 0.6-0.7: Some claims supported, some reasonable inferences
- 0.4-0.5: Limited source support, significant inferences
- 0.0-0.3: Mostly unsupported or fabricated

Key checks:
- Are specific course codes/names real or fabricated?
- Are university-specific claims backed by web results?
- Does the answer acknowledge what data it lacks?
- Is the advice appropriate given the available information?

IMPORTANT — Profile Updates (Passive Learning):
Scan the user's original query for NEW information about themselves that should be saved.
For each piece, set "field" to one of: name, gpa, university, program, email, semester,
interest, goal, skill, company, project, course.

Examples:
- "I'm interested in machine learning" → {{"field": "interest", "value": "Machine Learning", "source": "conversation"}}
- "I got an A in CSC 200" → {{"field": "course", "value": "CSC 200", "source": "conversation"}}
- "I want to work at Google" → {{"field": "goal", "value": "Work at Google", "source": "conversation"}}
- "My GPA is 3.8" → {{"field": "gpa", "value": "3.8", "source": "conversation"}}
- "I know Python and React" → [{{"field": "skill", "value": "Python"}}, {{"field": "skill", "value": "React"}}]

Only extract genuinely new information. Don't extract questions or hypotheticals.

Draft answer:
{draft}

Available sources:
{sources}

Original user query:
{query}
"""

_REWRITE_PROMPT = """You are the grounded answer repairer for Pathfinder.

The original draft may contain unsupported or fabricated claims.
Rewrite the answer using ONLY the verified source material below.

Rules:
1. Keep only claims that are directly supported by the sources.
2. If a specific course, requirement, or university-specific fact is not supported, do not mention it.
3. If the sources are insufficient to fully answer the question, say exactly what is still missing in 1-2 sentences.
4. Be concise and direct.
5. If sources exist, include inline markdown links naturally where helpful.
6. Never invent course codes, titles, prerequisites, schedules, or deadlines.

Original user query:
{query}

Unreliable draft:
{draft}

Issues detected:
{issues}

Verified sources:
{sources}
"""


async def evaluator(state: PathfinderState) -> PathfinderState:
    """Evaluate the draft answer for quality and groundedness."""
    draft = state.get("draft_answer", "")
    query = state.get("query", "")
    documents = state.get("retrieved_documents", [])
    web_results = state.get("web_results", [])
    evidence_records = state.get("evidence_records", [])
    decision_payload = state.get("decision_payload", {})
    working_memory = init_working_memory(state.get("working_memory", {}))
    task_graph = state.get("task_graph", [])
    blocked_reasons = list(state.get("blocked_reasons", []))

    step_progress = list(state.get("step_progress", []))
    step_progress.append("Verifying answer quality...")

    if not draft:
        # No draft to evaluate — nothing to do
        return {
            **state,
            "confidence_score": 0.0,
            "is_grounded": False,
            "step_progress": step_progress,
            "next_node": "responder",
        }

    llm = get_text_llm()

    # Compile sources
    sources = []
    for d in documents[:5]:
        sources.append(f"[Document: {d.get('filename', 'unknown')}] {d.get('text', '')[:1000]}")
    for w in web_results[:8]:
        title = w.get("title", "")
        url = w.get("url", "")
        content = w.get("content", "")
        sources.append(f"[Web: {title}] ({url}) {content[:1500]}")
    sources_text = "\n".join(sources) if sources else "No sources available."

    response = await llm.ainvoke([
        SystemMessage(content="You are an answer quality evaluator."),
        HumanMessage(content=_EVALUATION_PROMPT.format(
            draft=draft[:2000],
            sources=sources_text,
            query=query,
        )),
    ])

    content = response.content if isinstance(response.content, str) else str(response.content)

    # Parse evaluation
    try:
        json_start = content.find("{")
        json_end = content.rfind("}") + 1
        parsed = json.loads(content[json_start:json_end])
    except (json.JSONDecodeError, ValueError):
        parsed = {
            "is_grounded": False,
            "confidence_score": 0.0,
            "issues": ["Evaluator could not parse its own review output"],
            "profile_updates": [],
            "needs_disclaimer": False,
            "disclaimer": "",
        }

    is_grounded = parsed.get("is_grounded", True)
    confidence = parsed.get("confidence_score", 0.5)
    profile_updates = parsed.get("profile_updates", [])
    needs_disclaimer = parsed.get("needs_disclaimer", False)
    disclaimer = parsed.get("disclaimer", "")
    issues = parsed.get("issues", [])

    # ── Handle low-confidence / ungrounded answers ──
    final_draft = draft
    validated_payload = _validate_decision_payload(decision_payload, evidence_records)
    if validated_payload:
        decision_payload = validated_payload
        for item in validated_payload.get("blocked_or_uncertain_items", []):
            if item.get("kind") in {"blocked", "needs_verification"}:
                blocked_reasons.append(item.get("reason", ""))
                working_memory = add_working_memory_item(working_memory, "planner_blockers", item.get("reason", ""))

    must_rewrite = (confidence < 0.65) or (not is_grounded)
    if must_rewrite:
        rewrite = await _rewrite_grounded_answer(query, draft, issues, sources_text)
        if rewrite:
            final_draft = rewrite
            log.warning("Evaluator rewrote low-grounded answer (confidence %.2f)", confidence)
        elif confidence < 0.4 and not is_grounded:
            warning = (
                "I could not verify enough official information to answer this confidently. "
                "Please check the official catalog or share the specific program page you want me to analyze."
            )
            final_draft = warning
            blocked_reasons.append(warning)
    elif needs_disclaimer and disclaimer:
        final_draft = f"{draft}\n\n⚠️ *{disclaimer}*"

    # ── Passively learn: persist profile updates detected from conversation ──
    student_id = state.get("student_id", "default")
    if profile_updates:
        try:
            # Separate student-level properties from entity updates
            student_props = {}
            entities = []
            for update in profile_updates:
                field = update.get("field", "")
                value = update.get("value", "")
                if not field or not value:
                    continue
                # Student-level fields (name, gpa, university, etc.)
                if field.lower() in ("name", "gpa", "university", "program", "email", "semester"):
                    student_props[field.lower()] = value
                else:
                    # Treat as entity (interest, goal, skill, etc.)
                    label = _field_to_label(field)
                    entities.append({
                        "label": label,
                        "properties": {"name": value},
                        "relationship": _label_to_relationship(label),
                    })

            if student_props:
                await update_student(student_id, **student_props)
                log.info("Evaluator: passively updated student props: %s", list(student_props.keys()))

            if entities:
                count = await store_extracted_entities(entities, "conversation", student_id)
                log.info("Evaluator: passively stored %d entities from conversation", count)

        except Exception as exc:
            log.warning("Evaluator: failed to persist profile updates: %s", exc)

    step_progress.append(f"Confidence: {confidence:.0%} — Grounded: {'Yes' if is_grounded else 'Needs review'}")
    task_graph = complete_task(task_graph, "render_answer")
    trace_summary = summarize_trace({
        **state,
        "task_graph": task_graph,
        "working_memory": working_memory,
        "blocked_reasons": [reason for reason in blocked_reasons if reason],
        "confidence_score": confidence,
        "decision_payload": decision_payload,
    })

    log.info("Evaluator: confidence=%.2f grounded=%s updates=%d issues=%s",
             confidence, is_grounded, len(profile_updates), issues)

    return {
        **state,
        "draft_answer": final_draft,
        "confidence_score": confidence,
        "is_grounded": is_grounded,
        "profile_updates": profile_updates,
        "decision_payload": decision_payload,
        "working_memory": working_memory,
        "task_graph": task_graph,
        "blocked_reasons": [reason for reason in blocked_reasons if reason],
        "trace_summary": trace_summary,
        "step_progress": step_progress,
        "next_node": "responder",
    }


async def _rewrite_grounded_answer(
    query: str, draft: str, issues: list[str], sources_text: str
) -> str:
    """Attempt to repair an answer by restricting it to verified sources."""
    if not sources_text or sources_text == "No sources available.":
        return ""

    llm = get_text_llm()
    response = await llm.ainvoke([
        SystemMessage(content="You repair unsupported answers by rewriting them from verified evidence only."),
        HumanMessage(content=_REWRITE_PROMPT.format(
            query=query,
            draft=draft[:2500],
            issues=", ".join(issues[:8]) if issues else "None listed",
            sources=sources_text[:12000],
        )),
    ])
    content = response.content if isinstance(response.content, str) else str(response.content)
    return content.strip()


def _field_to_label(field: str) -> str:
    """Map a profile update field name to an entity label."""
    mapping = {
        "interest": "Interest", "interests": "Interest",
        "goal": "Goal", "goals": "Goal",
        "skill": "Skill", "skills": "Skill",
        "company": "Company", "experience": "Company",
        "project": "Project", "projects": "Project",
        "course": "Course", "courses": "Course",
    }
    return mapping.get(field.lower(), "Interest")


def _validate_decision_payload(
    payload: DecisionPayload, evidence_records: list[dict[str, Any]]
) -> DecisionPayload:
    """Drop unsupported recommendations from a structured planner payload."""
    if not payload:
        return {}

    supported_urls = {record.get("source_url", "") for record in evidence_records if record.get("source_url")}
    supported_codes = {
        record.get("value", {}).get("code", "")
        for record in evidence_records
        if isinstance(record.get("value"), dict)
    }

    source_refs = payload.get("source_refs", [])
    valid_refs = [ref for ref in source_refs if ref.get("url", "") in supported_urls or not ref.get("url")]
    evidence_texts = [
        " ".join(
            str(part)
            for part in (
                record.get("source_title", ""),
                record.get("excerpt", ""),
                record.get("value", {}).get("name", "") if isinstance(record.get("value"), dict) else "",
                record.get("value", {}).get("code", "") if isinstance(record.get("value"), dict) else "",
                record.get("value", {}).get("summary", "") if isinstance(record.get("value"), dict) else "",
            )
        ).lower()
        for record in evidence_records
    ]

    validated_recommendations = []
    for item in payload.get("recommended_items", []):
        codes = set(item.get("support_codes", []))
        has_code_support = bool(codes & supported_codes)
        has_ref_support = _item_has_textual_support(item, evidence_texts, valid_refs)
        if has_code_support or has_ref_support:
            validated_recommendations.append(item)

    validated = dict(payload)
    validated["recommended_items"] = validated_recommendations
    validated["source_refs"] = valid_refs

    dropped = len(payload.get("recommended_items", [])) - len(validated_recommendations)
    if dropped > 0:
        blocked = list(validated.get("blocked_or_uncertain_items", []))
        blocked.append({
            "label": "Some recommendations were removed",
            "reason": f"{dropped} unsupported recommendation(s) were dropped during quality validation.",
            "kind": "needs_verification",
        })
        validated["blocked_or_uncertain_items"] = blocked

    return validated


def _item_has_textual_support(
    item: dict[str, Any],
    evidence_texts: list[str],
    valid_refs: list[dict[str, Any]],
) -> bool:
    """Check whether a recommendation is textually grounded in evidence."""
    label = str(item.get("label", "")).strip().lower()
    reason = str(item.get("reason", "")).strip().lower()
    if not label and not reason:
        return False

    item_tokens = _support_tokens(label)
    if len(item_tokens) < 2 and not _looks_like_course_label(label):
        return False

    ref_texts = [
        " ".join(
            str(part)
            for part in (ref.get("title", ""), ref.get("excerpt", ""), ref.get("entity_type", ""))
        ).lower()
        for ref in valid_refs
    ]

    for text in evidence_texts + ref_texts:
        if _looks_like_course_label(label) and label in text:
            return True
        overlap = [token for token in item_tokens if token in text]
        if len(overlap) >= min(2, len(item_tokens)):
            return True
        if reason:
            reason_tokens = _support_tokens(reason)
            if len([token for token in reason_tokens if token in text]) >= 3:
                return True
    return False


def _support_tokens(text: str) -> list[str]:
    tokens = []
    for token in re.findall(r"[a-z0-9]{2,}", text.lower()):
        if token not in {"the", "and", "for", "with", "this", "that", "from", "your", "good", "best", "option"} and token not in tokens:
            tokens.append(token)
    return tokens


def _looks_like_course_label(label: str) -> bool:
    return bool(re.search(r"\b[A-Z]{2,4}\s?-?\d{3}[A-Z]?\b", label or "", re.I))


def _label_to_relationship(label: str) -> str:
    """Map an entity label to a relationship type."""
    mapping = {
        "Interest": "INTERESTED_IN",
        "Goal": "HAS_GOAL",
        "Skill": "HAS_SKILL",
        "Company": "WORKED_AT",
        "Project": "COMPLETED",
        "Course": "TOOK",
    }
    return mapping.get(label, "HAS")
