# """Document role inference helpers.

# Infers the semantic role of an uploaded document from filename and extracted
# text so downstream policy can reason over transcript/resume/degree-plan style
# evidence explicitly.
# """

# from __future__ import annotations

# import re
# from typing import Any


# def infer_document_role(filename: str, text: str, file_type: str = "unknown") -> dict[str, Any]:
#     """Infer a semantic document role from filename and extracted text."""
#     filename_text = str(filename or "").strip()
#     combined = f"{filename_text}\n{text or ''}"
#     lowered = combined.casefold()

#     transcript_signals = _collect_signals(
#         lowered,
#         (
#             "transcript",
#             "cumulative gpa",
#             "cum totals",
#             "non-course milestones",
#             "end of transcript",
#             "grade points",
#             "term gpa",
#             "academic standing",
#             "attempted earned",
#         ),
#     )
#     transcript_code_hits = len(re.findall(r"\b[a-z]{2,4}\s*\d{3}[a-z]?\b", lowered))
#     if transcript_code_hits >= 6:
#         transcript_signals.append("many_course_codes")

#     resume_signals = _collect_signals(
#         lowered,
#         (
#             "resume",
#             "curriculum vitae",
#             "professional experience",
#             "work experience",
#             "skills",
#             "projects",
#             "software engineer",
#         ),
#     )
#     degree_plan_signals = _collect_signals(
#         lowered,
#         (
#             "degree plan",
#             "program requirements",
#             "course sequence",
#             "recommended schedule",
#             "study plan",
#             "roadmap",
#         ),
#     )
#     syllabus_signals = _collect_signals(
#         lowered,
#         (
#             "syllabus",
#             "learning outcomes",
#             "course schedule",
#             "grading policy",
#             "office hours",
#         ),
#     )
#     handbook_signals = _collect_signals(
#         lowered,
#         (
#             "student handbook",
#             "graduate handbook",
#             "policy handbook",
#             "program handbook",
#         ),
#     )

#     scored = [
#         ("transcript", _role_score(transcript_signals, file_type, filename_text, expected_terms=("transcript",))),
#         ("resume", _role_score(resume_signals, file_type, filename_text, expected_terms=("resume", "cv"))),
#         ("degree_plan", _role_score(degree_plan_signals, file_type, filename_text, expected_terms=("plan", "roadmap"))),
#         ("syllabus", _role_score(syllabus_signals, file_type, filename_text, expected_terms=("syllabus",))),
#         ("handbook", _role_score(handbook_signals, file_type, filename_text, expected_terms=("handbook",))),
#     ]
#     scored.sort(key=lambda item: item[1]["score"], reverse=True)
#     top_role, top_meta = scored[0]

#     if top_meta["score"] < 0.28:
#         return {
#             "role": "general_document",
#             "confidence": 0.18 if text.strip() else 0.0,
#             "signals": top_meta["signals"][:4],
#             "file_type": file_type,
#         }

#     return {
#         "role": top_role,
#         "confidence": round(min(0.98, top_meta["score"]), 2),
#         "signals": top_meta["signals"][:6],
#         "file_type": file_type,
#     }


# def _collect_signals(lowered_text: str, phrases: tuple[str, ...]) -> list[str]:
#     return [phrase for phrase in phrases if phrase in lowered_text]


# def _role_score(
#     signals: list[str],
#     file_type: str,
#     filename: str,
#     *,
#     expected_terms: tuple[str, ...],
# ) -> dict[str, Any]:
#     score = 0.12 * len(signals)
#     lowered_filename = filename.casefold()
#     if file_type in {"pdf", "docx", "text"}:
#         score += 0.04
#     if any(term in lowered_filename for term in expected_terms):
#         score += 0.22
#     return {"score": round(score, 4), "signals": signals}
