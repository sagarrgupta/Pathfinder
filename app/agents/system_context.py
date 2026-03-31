"""Compact shared system context for LLM-facing Pathfinder steps."""

from __future__ import annotations

from typing import Iterable

_SYSTEM_BRIEF = (
    "You are operating inside Pathfinder, a student guidance system. "
    "Code executes tools, validation, persistence, and routing. "
    "Your role is to return compact structured decisions for the current step only."
)

_CAPABILITY_DESCRIPTIONS = {
    "profile_memory_agent": "Loads stable student profile facts from memory and graph state.",
    "semantic_memory_agent": "Retrieves reusable facts, evidence, and prior memory relevant to the query.",
    "document_evidence_agent": "Extracts and prioritizes current-turn attached document evidence.",
    "web_researcher": "Finds current or external information from the web and provided URLs.",
    "evidence_judge_agent": "Reranks and filters gathered profile, document, and web evidence.",
    "conflict_resolution_agent": "Handles conflicting facts and uncertainty before final reasoning.",
    "missing_info_agent": "Determines what important information is missing but not blocking.",
    "academic_strategy_agent": "Produces academic guidance using available evidence.",
    "career_strategy_agent": "Produces career guidance using available evidence.",
    "interview_coach_agent": "Produces interview preparation guidance using available evidence.",
    "decision_comparison_agent": "Compares options, tradeoffs, and alternatives.",
    "document_understanding_agent": "Summarizes or analyzes attached documents directly.",
    "plan_action_agent": "Turns guidance into a concrete action plan and follow-up steps.",
    "answer_composer_agent": "Formats a polished student-facing final response.",
    "memory_writer_agent": "Extracts reusable long-term memory from the current turn when appropriate.",
}


def build_step_system_prompt(
    *,
    step_name: str,
    objective: str,
    output_schema: str,
    relevant_capabilities: Iterable[str] = (),
    extra_rules: Iterable[str] = (),
) -> str:
    """Build a compact system prompt with only the context needed for one step."""
    capability_lines = []
    for name in relevant_capabilities:
        description = _CAPABILITY_DESCRIPTIONS.get(name)
        if description:
            capability_lines.append(f"- {name}: {description}")

    rules = [f"- {rule}" for rule in extra_rules if rule]

    sections = [
        _SYSTEM_BRIEF,
        f"Current step: {step_name}.",
        f"Objective: {objective}",
    ]
    if capability_lines:
        sections.append("Relevant capabilities:\n" + "\n".join(capability_lines))
    if rules:
        sections.append("Step rules:\n" + "\n".join(rules))
    sections.append("Required output:\n" + output_schema.strip())
    return "\n\n".join(sections)
