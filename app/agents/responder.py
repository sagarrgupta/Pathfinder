"""Node 11: Responder.

Final node that formats the answer, attaches citations and metadata,
and prepares the output for SSE streaming.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage

from app.adapters.llm.lmstudio import get_text_llm
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.responder")

_SYNTHESIS_PROMPT = """You are the final Responder in Pathfinder. Your job is to take a draft answer and
polish it into a clear, well-formatted response for the student.

Rules:
1. Keep the substance of the draft answer — don't remove important information.
2. Format with markdown: use headers, bullet points, and bold for key info.
3. If there are citations, weave them naturally into the text.
4. Keep the tone friendly, professional, and encouraging.
5. If confidence is low, acknowledge uncertainty honestly.
6. End with a clear next step or follow-up suggestion when appropriate.

Draft answer: {draft}
Confidence: {confidence}
Intent: {intent}
"""


async def responder(state: PathfinderState) -> PathfinderState:
    """Format the final answer and prepare for output."""
    draft = state.get("draft_answer", "")
    final_already = state.get("final_answer", "")
    intent = state.get("intent", "general")
    confidence = state.get("confidence_score", 0.5)
    is_blocked = state.get("is_blocked", False)
    block_reason = state.get("block_reason", "")

    step_progress = list(state.get("step_progress", []))

    # If blocked by input guard, return the block reason directly
    if is_blocked:
        return {
            **state,
            "final_answer": block_reason,
            "step_progress": step_progress,
        }

    # If a previous node (e.g. clarifier) already set final_answer, keep it
    if final_already and not draft:
        step_progress.append("Response ready!")
        return {
            **state,
            "step_progress": step_progress,
        }

    # Handle document upload: summarize what was extracted
    if intent == "document" and not draft:
        profile = state.get("profile_data", {})
        entities = state.get("extracted_entities", [])
        docs = state.get("retrieved_documents", [])

        summary_parts = ["## ✅ Document Processed Successfully\n"]
        summary_parts.append(f"I've processed your uploaded document and stored **{len(docs)}** relevant text chunks.\n")

        if entities:
            summary_parts.append(f"### Extracted Information ({len(entities)} items)\n")
            for e in entities[:10]:
                label = e.get("label", "")
                name = e.get("properties", {}).get("name", "")
                extra = ""
                if label == "Course":
                    grade = e.get("properties", {}).get("grade", "")
                    extra = f" (Grade: {grade})" if grade else ""
                summary_parts.append(f"- **{label}**: {name}{extra}")
        else:
            summary_parts.append("I stored the document text for future reference, but couldn't extract specific entities (courses, skills, etc.) automatically.")
            summary_parts.append("You can add this information manually in the **My Profile** section.")

        # Show updated profile snapshot
        personal = profile.get("personal", {})
        courses = profile.get("courses", [])
        skills = profile.get("skills", [])
        if courses or skills:
            summary_parts.append("\n### Your Updated Profile")
            if courses:
                course_list = ", ".join(c.get("name", c.get("code", "?")) for c in courses[:10])
                summary_parts.append(f"- **Courses**: {course_list}")
            if skills:
                skill_list = ", ".join(s.get("name", "") for s in skills[:10])
                summary_parts.append(f"- **Skills**: {skill_list}")

        summary_parts.append("\n---\n**What would you like to do next?** You can ask me for course recommendations, career advice, or anything else!")

        draft = "\n".join(summary_parts)
        return {
            **state,
            "final_answer": draft,
            "confidence_score": 0.95,
            "step_progress": step_progress,
        }

    # If it's a greeting or simple response, use draft directly
    if intent == "greeting" or not draft:
        if not draft:
            llm = get_text_llm()
            response = await llm.ainvoke([
                SystemMessage(content=(
                    "You are Pathfinder, a friendly AI academic and career guidance assistant. "
                    "Respond to the user's greeting or simple question warmly. "
                    "Mention that you can help with academic advising, career planning, "
                    "and interview preparation."
                )),
                HumanMessage(content=state.get("query", "Hello")),
            ])
            draft = response.content if isinstance(response.content, str) else str(response.content)

        return {
            **state,
            "final_answer": draft,
            "confidence_score": 1.0,
            "step_progress": step_progress,
        }

    # Polish the draft for non-trivial answers
    step_progress.append("Formatting your answer...")
    llm = get_text_llm()

    response = await llm.ainvoke([
        SystemMessage(content="You are a response formatter. Polish and format the following answer."),
        HumanMessage(content=_SYNTHESIS_PROMPT.format(
            draft=draft[:3000],
            confidence=f"{confidence:.0%}",
            intent=intent,
        )),
    ])

    final = response.content if isinstance(response.content, str) else str(response.content)

    # Determine method for metadata
    method = _determine_method(state)

    step_progress.append("Response ready!")
    log.info("Responder: method=%s confidence=%.2f", method, confidence)

    return {
        **state,
        "final_answer": final,
        "step_progress": step_progress,
    }


def _determine_method(state: PathfinderState) -> str:
    """Determine which retrieval methods were used."""
    methods = []
    if state.get("retrieved_documents"):
        methods.append("rag")
    if state.get("graph_results") or state.get("profile_data", {}).get("courses"):
        methods.append("graph")
    if state.get("web_results"):
        methods.append("web")
    return "+".join(methods) if methods else "direct"
