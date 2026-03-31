"""Capability agent: final answer composition."""

from __future__ import annotations

import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.adapters.llm.lmstudio import get_text_llm, strip_repetition
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.answer_composer")

_PROMPT = """You are Pathfinder's final Answer Composer.

Turn the draft analysis into a polished, personalized student-facing answer.

Rules:
- Preserve the core recommendation and reasoning from the draft.
- Mention the student context naturally, not mechanically.
- If missing information exists, mention only the highest-value follow-up data.
- If conflicts matter, acknowledge uncertainty briefly without sounding repetitive.
- When recommended actions are available, present them as clear next steps.
- Use markdown headings/bullets only when they help readability.
- Keep the tone warm, capable, and evidence-aware.
"""


def _pretty_fact_type(value: str) -> str:
    return value.replace("_", " ").strip() if value else "profile"


def _clean_goalish_text(value: str) -> str:
    text = (value or "").strip().rstrip(".")
    text = re.sub(r"^(my current (main )?goal is|my goal is|goal:)\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(i (prefer|want|am aiming for|am targeting))\s*", "", text, flags=re.IGNORECASE)
    return text.strip()


def _build_profile_update_summary(state: PathfinderState, latest_profile_update: dict, personal: dict) -> str:
    ingestion = state.get("latest_ingestion_result", {}) or {}
    promoted = ingestion.get("promoted_entities", []) or []
    candidate_facts = ingestion.get("candidate_facts", []) or []

    for fact in candidate_facts:
        fact_type = str(fact.get("fact_type", "")).strip().lower()
        value = str(fact.get("value", "")).strip()
        if not value:
            continue
        cleaned = _clean_goalish_text(value)
        if fact_type == "goal":
            return f"your goal to **{cleaned or value}**"
        if fact_type == "preference":
            return f"your preference for **{cleaned or value}**"
        if fact_type == "constraint":
            return f"your constraint: **{cleaned or value}**"
        if fact_type == "skill":
            return f"your skill **{value}**"

    for entity in promoted:
        label = str(entity.get("_label") or entity.get("label") or "")
        name = str(entity.get("name", "")).strip()
        if not name:
            continue
        if label == "Goal":
            return f"your goal to **{_clean_goalish_text(name) or name}**"
        if label == "Preference":
            return f"your preference for **{_clean_goalish_text(name) or name}**"
        if label == "Constraint":
            return f"your constraint: **{name}**"
        return f"your {_pretty_fact_type(label).lower()} **{name}**"

    summary_bits = []
    if latest_profile_update.get("name"):
        summary_bits.append(latest_profile_update["name"])
    if latest_profile_update.get("program"):
        summary_bits.append(latest_profile_update["program"])
    if latest_profile_update.get("university"):
        summary_bits.append(latest_profile_update["university"])
    if latest_profile_update.get("gpa"):
        summary_bits.append(f"GPA {latest_profile_update['gpa']}")
    if len(summary_bits) >= 2:
        return f"**{' at '.join(summary_bits[-2:])}**"
    if summary_bits:
        return f"**{summary_bits[0]}**"
    return ""


async def answer_composer_agent(state: PathfinderState) -> PathfinderState:
    """Compose the final answer, unless a specialist already owns it directly."""
    step_progress = list(state.get("step_progress", []))
    step_progress.append("Composing final answer...")

    if state.get("is_blocked"):
        return {**state, "final_answer": state.get("block_reason", ""), "step_progress": step_progress}

    if state.get("answer_style") == "direct_specialist" and state.get("final_answer"):
        step_progress.append("Direct specialist answer kept")
        return {**state, "step_progress": step_progress}

    draft = state.get("draft_answer", "").strip()
    profile = state.get("profile_data", {})
    personal = profile.get("personal", {}) if profile else {}
    latest_profile_update = (state.get("profile_updates", []) or [{}])[-1] if state.get("profile_updates") else {}
    student_name = (personal.get("name") or "").strip()
    active_profile_label = student_name or state.get("student_id", "your active profile")
    query = state.get("query", "")
    query_lower = query.lower()

    if not draft and state.get("intent") == "greeting":
        final = (
            f"Hello! I'm currently using the **{active_profile_label}** profile."
            " What would you like help with next?"
        )
        step_progress.append("Final answer ready")
        return {**state, "final_answer": final, "step_progress": step_progress}

    if (
        not draft
        and state.get("intent") == "general"
        and state.get("task_type") == "clarify"
        and not state.get("needs_profile")
        and not state.get("needs_documents")
        and not state.get("needs_web")
    ):
        final = (
            "I can help with academic planning, career direction, interview prep, and profile-based recommendations. "
            "I can also use your saved profile, uploaded documents, and when needed web research to give more grounded answers.\n\n"
            "You can ask things like: `help me plan my semester`, `what roles fit my profile`, `review this resume`, or `prepare me for a backend interview`."
        )
        step_progress.append("Final answer ready")
        return {**state, "final_answer": final, "step_progress": step_progress}

    if not draft and state.get("intent") == "profile" and state.get("task_type") == "update":
        ingestion = state.get("latest_ingestion_result", {}) or {}
        profile_update_error = str(ingestion.get("profile_update_error", "")).strip()
        if profile_update_error:
            final = (
                "I couldn’t update your profile from that link because I couldn’t access the page directly. "
                "If you paste the profile text here or upload an exported resume/PDF, I can add the information for you."
            )
            step_progress.append("Final answer ready")
            return {**state, "final_answer": final, "step_progress": step_progress}
        summary = _build_profile_update_summary(state, latest_profile_update, personal)
        final = (
            "Thanks, I’ve updated your profile"
            + (f" with {summary}." if summary else ".")
            + " I’ll use this context in future answers."
        )
        step_progress.append("Final answer ready")
        return {**state, "final_answer": final, "step_progress": step_progress}

    if state.get("intent") == "profile" and state.get("task_type") == "summarize" and "gpa" in query_lower:
        gpa = latest_profile_update.get("gpa") or personal.get("gpa")
        final = (
            f"Your GPA is **{gpa}**."
            if gpa
            else "I don’t have your GPA in profile memory yet. If you share it or upload a transcript, I’ll remember it for future answers."
        )
        step_progress.append("Final answer ready")
        return {**state, "final_answer": final, "step_progress": step_progress}

    if not draft and state.get("intent") == "profile" and state.get("task_type") == "summarize":
        if "gpa" in query_lower:
            gpa = latest_profile_update.get("gpa") or personal.get("gpa")
            final = (
                f"Your GPA is **{gpa}**."
                if gpa
                else "I don’t have your GPA in profile memory yet. If you share it or upload a transcript, I’ll remember it for future answers."
            )
        elif "name" in query_lower:
            final = (
                f"Your name is **{latest_profile_update.get('name') or personal.get('name')}**."
                if (latest_profile_update.get("name") or personal.get("name"))
                else "I don’t have your name stored yet."
            )
        elif "university" in query_lower or "college" in query_lower:
            university = latest_profile_update.get("university") or personal.get("university")
            final = (
                f"You currently study at **{university}**."
                if university
                else "I don’t have your university stored yet."
            )
        elif "program" in query_lower or "major" in query_lower:
            program = latest_profile_update.get("program") or personal.get("program")
            final = (
                f"Your current program is **{program}**."
                if program
                else "I don’t have your program stored yet."
            )
        else:
            known = []
            for label, value in (
                ("name", latest_profile_update.get("name") or personal.get("name")),
                ("university", latest_profile_update.get("university") or personal.get("university")),
                ("program", latest_profile_update.get("program") or personal.get("program")),
                ("GPA", latest_profile_update.get("gpa") or personal.get("gpa")),
            ):
                if value:
                    known.append(f"{label}: {value}")
            final = "Here’s what I currently know about you:\n\n- " + "\n- ".join(known) if known else "I don’t have much profile memory yet. Share a few details and I’ll build it up over time."
        step_progress.append("Final answer ready")
        return {**state, "final_answer": final, "step_progress": step_progress}

    if not draft:
        draft = "I do not have enough evidence to give a strong personalized answer yet."

    citations = state.get("citations", [])
    sources = []
    for citation in citations[:6]:
        source = citation.get("source")
        title = citation.get("metadata", {}).get("title")
        if source:
            sources.append(f"{title or source}")

    student_name = (student_name or "the student").split(" ")[0]
    llm = get_text_llm()

    response = await llm.ainvoke(
        [
            SystemMessage(content=_PROMPT),
            HumanMessage(
                content=(
                    f"Student: {student_name}\n"
                    f"Intent: {state.get('intent', 'general')}\n"
                    f"Question: {query}\n"
                    f"Confidence: {state.get('confidence_score', 0.5):.0%}\n"
                    f"Missing info: {', '.join(state.get('missing_info', [])) or 'none'}\n"
                    f"Conflicts: {len(state.get('conflicts', []))}\n"
                    f"Recommended actions: {state.get('recommended_actions', [])}\n"
                    f"Rationale: {state.get('answer_rationale', [])}\n"
                    f"Sources: {sources}\n\n"
                    f"Draft:\n{draft}"
                )
            ),
        ]
    )
    final = strip_repetition(response.content if isinstance(response.content, str) else str(response.content))

    if state.get("recommended_actions"):
        action_lines = "\n".join(f"- {item}" for item in state["recommended_actions"][:3])
        if "Suggested next steps" not in final:
            final = f"{final}\n\n## Suggested next steps\n{action_lines}"

    if sources:
        source_lines = "\n".join(f"- {item}" for item in sources[:5])
        if "Sources" not in final:
            final = f"{final}\n\n## Sources\n{source_lines}"

    step_progress.append("Final answer ready")
    return {**state, "final_answer": final, "step_progress": step_progress}
