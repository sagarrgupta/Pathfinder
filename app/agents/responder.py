"""Node 11: Responder.

Final node that formats the answer, attaches citations and metadata,
and prepares the output for SSE streaming.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage

from app.adapters.llm.lmstudio import get_text_llm, strip_repetition, is_garbage_output
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.responder")

_SYNTHESIS_PROMPT = """You are the final Responder in Pathfinder, an AI academic and career guidance assistant for students.

Your job is to take a draft answer and polish it into a personalized, well-formatted response.

Student name: {student_name}

Rules:
1. Keep the substance of the draft answer — don't remove important information.
2. Format with markdown: use headers (##), bullet points, tables, and bold for key info.
3. Weave citations naturally into the text with clickable links.
4. Tone: warm, professional, encouraging — like a knowledgeable mentor. Not generic or robotic.
5. If confidence is low, acknowledge uncertainty honestly but still be helpful.
6. End with 1-2 specific follow-up suggestions (not generic ones).
7. If the student's name is available, address them by first name occasionally — but don't overdo it.
8. Use "sources:" at the end to list URLs referenced (if any).

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

    # Extract student name for personalization
    profile = state.get("profile_data", {})
    personal = profile.get("personal", {}) if profile else {}
    student_name = personal.get("name", "").split()[0] if personal.get("name") else ""

    # If it's a greeting, generate a personalized welcome
    if intent == "greeting":
        if not draft:
            llm = get_text_llm()

            greeting_context = "The student has no profile yet." if not student_name else (
                f"The student's name is {student_name}."
            )

            # Build profile snapshot for personalized greeting
            if profile:
                skills_count = len(profile.get("skills", []))
                courses_count = len(profile.get("courses", []))
                docs_count = len(profile.get("documents", []))
                if skills_count or courses_count:
                    greeting_context += f" They have {courses_count} courses and {skills_count} skills in their profile."
                if docs_count:
                    greeting_context += f" They have {docs_count} documents uploaded."

            response = await llm.ainvoke([
                SystemMessage(content=(
                    "You are Pathfinder, a warm and knowledgeable AI academic and career guidance assistant "
                    "designed for students. "
                    "Respond to the user's greeting personally. If you know their name, use it. "
                    "Briefly mention what you can help with: course planning, career guidance, "
                    "interview prep, resume analysis, and web research. "
                    "If they have profile data, acknowledge it (e.g., 'I see you have your courses loaded'). "
                    "Keep it concise — 2-3 sentences max. Don't use bullet points for greetings.\n\n"
                    f"Context: {greeting_context}"
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

    # If the draft is garbage (model control tokens, etc.), discard it
    if draft and is_garbage_output(draft):
        log.warning("Responder received garbage draft (%d chars), discarding", len(draft))
        draft = ""

    # If no advisory agent produced a draft but we have data, generate
    # a substantive answer using the available profile + document chunks
    if not draft:
        step_progress.append("Generating answer from available data...")
        llm = get_text_llm()
        query = state.get("query", "")
        if not profile:
            profile = state.get("profile_data", {})
        documents = state.get("retrieved_documents", [])
        web_results = state.get("web_results", [])

        context_parts = []
        if not personal:
            personal = profile.get("personal", {}) if profile else {}
        if personal:
            context_parts.append("Student profile: " + ", ".join(
                f"{k}: {v}" for k, v in personal.items()
                if v and k not in ("id", "created_at", "updated_at")
            ))
        skills = profile.get("skills", [])
        if skills:
            context_parts.append("Skills: " + ", ".join(s.get("name", "") for s in skills))
        experience = profile.get("experience", [])
        if experience:
            context_parts.append("Experience: " + ", ".join(
                f"{e.get('role', '')} at {e.get('name', '')}" for e in experience
            ))
        if documents:
            context_parts.append("Relevant document excerpts:\n" + "\n".join(
                d.get("text", "")[:400] for d in documents[:5]
            ))
        if web_results:
            for r in web_results[:5]:
                source = r.get("source", "")
                content = r.get("content", "")
                if source == "direct_url":
                    context_parts.append(f"Web page content [{r.get('title', '')}]({r.get('url', '')}):\n{content[:6000]}")
                else:
                    context_parts.append(f"- {r.get('title', '')}: {content[:400]}")

        context = "\n\n".join(context_parts) if context_parts else "No data available."

        name_intro = f"The student's name is {student_name}. " if student_name else ""
        response = await llm.ainvoke([
            SystemMessage(content=(
                "You are Pathfinder, a warm and knowledgeable AI academic and career guidance assistant "
                "for students. "
                + name_intro +
                "Answer the student's question using the context provided below. "
                "If the context includes their resume or profile data, USE it to give "
                "a personalized, specific answer. Do NOT ask the student to tell you "
                "things that are already in the context. "
                "When summarizing web page content, be thorough and include key details. "
                "Format with markdown. Be helpful and actionable."
            )),
            HumanMessage(content=f"Context:\n{context}\n\nStudent's question: {query}"),
        ])
        draft = strip_repetition(response.content if isinstance(response.content, str) else str(response.content))

        return {
            **state,
            "final_answer": draft,
            "confidence_score": 0.6,
            "step_progress": step_progress,
        }

    # Polish the draft for non-trivial answers
    step_progress.append("Formatting your answer...")
    llm = get_text_llm()

    response = await llm.ainvoke([
        SystemMessage(content="You are a response formatter for Pathfinder. Polish and personalize the following answer."),
        HumanMessage(content=_SYNTHESIS_PROMPT.format(
            student_name=student_name or "the student",
            draft=draft[:4000],
            confidence=f"{confidence:.0%}",
            intent=intent,
        )),
    ])

    final = strip_repetition(response.content if isinstance(response.content, str) else str(response.content))

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
