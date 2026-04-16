# """Transcript state builder.

# Builds a structured academic state object from transcript text so downstream
# planning can reason over completed/planned courses and milestones directly.
# The parser is intentionally format-tolerant and avoids assuming one school,
# one level, or one registrar export layout.
# """

# from __future__ import annotations

# import json
# import re
# from typing import Any


# _TERM_PATTERN = r"(?:Spring|Summer|Fall|Winter|Autumn|Monsoon|Quarter\s+\d|Q[1-4]|Semester\s+\d|Trimester\s+\d)\s+20\d{2}"
# _TERM_HEADER_RE = re.compile(
#     rf"(?P<term>{_TERM_PATTERN})\s+(?P<body>.*?)(?=(?:{_TERM_PATTERN})|(?:Non[- ]Course\s+Milestones?|Milestones?|Academic\s+Milestones?)|(?:End of Transcript|Unofficial Transcript|Totals?\b)|\Z)",
#     re.S | re.I,
# )
# _COURSE_LINE_RE = re.compile(
#     r"(?P<code>[A-Z]{2,6}\s+\d{2,4}[A-Z]?)\s+"
#     r"(?P<title>.+?)"
#     r"(?:\s+(?P<attempted>\d+(?:\.\d{1,3})?)\s+(?P<earned>\d+(?:\.\d{1,3})?)\s+(?P<grade>[A-Z][+-]?|CR|NC|P|NP|IP|W)\s+(?P<points>\d+(?:\.\d{1,3})?))?"
#     r"(?=\n|$)",
#     re.I,
# )
# _FIELD_PATTERNS: tuple[tuple[str, str], ...] = (
#     (r"(?:^|\n)\s*Name:\s*(.+)", "student_name"),
#     (r"(?:^|\n)\s*(?:Institution Info|Institution|College|University):\s*(.+)", "institution"),
#     (r"(?:^|\n)\s*(?:Program|Major|Degree Program|Academic Program):\s*(.+)", "program"),
#     (r"(?:^|\n)\s*(?:Plan|Track|Concentration|Specialization):\s*(.+)", "plan"),
# )


# def build_transcript_state(text: str, filename: str = "") -> dict[str, Any]:
#     """Parse transcript text into a structured state object."""
#     normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
#     personal = _extract_personal_info(normalized)
#     terms = _extract_terms(normalized)
#     milestones = _extract_milestones(normalized)
#     completed_courses = [course for term in terms for course in term.get("completed_courses", [])]
#     planned_courses = [course for term in terms for course in term.get("planned_courses", [])]
#     cumulative_gpa = _extract_cumulative_gpa(normalized)
#     academic_standing = _extract_latest_academic_standing(normalized)

#     return {
#         "document_kind": "transcript",
#         "filename": filename,
#         "student_name": personal.get("student_name", ""),
#         "institution": personal.get("institution", ""),
#         "program": personal.get("program", ""),
#         "plan": personal.get("plan", ""),
#         "cumulative_gpa": cumulative_gpa,
#         "academic_standing": academic_standing,
#         "completed_courses": completed_courses,
#         "planned_courses": planned_courses,
#         "milestones": milestones,
#         "terms": terms,
#         "summary": {
#             "completed_course_count": len(completed_courses),
#             "planned_course_count": len(planned_courses),
#             "milestone_count": len(milestones),
#             "latest_term": terms[-1]["term"] if terms else "",
#             "latest_completed_term": _latest_completed_term(terms),
#             "upcoming_term": _upcoming_term(terms),
#             "completed_course_codes": [item.get("code", "") for item in completed_courses[:20]],
#             "planned_course_codes": [item.get("code", "") for item in planned_courses[:12]],
#             "milestone_labels": [item.get("description", "") or item.get("name", "") for item in milestones[:8]],
#         },
#     }


# def load_transcript_states(
#     explicit_states: list[dict[str, Any]] | None,
#     semantic_memory: dict[str, Any] | None,
# ) -> list[dict[str, Any]]:
#     """Load transcript states from current-turn state and persisted evidence."""
#     loaded: list[dict[str, Any]] = []
#     seen: set[str] = set()

#     for item in explicit_states or []:
#         raw_state = item.get("state", {}) if isinstance(item, dict) else {}
#         state = dict(raw_state) if isinstance(raw_state, dict) else {}
#         key = json.dumps(state, sort_keys=True) if state else ""
#         if key and key not in seen:
#             seen.add(key)
#             loaded.append(state)

#     semantic_memory = semantic_memory if isinstance(semantic_memory, dict) else {}
#     for evidence in (semantic_memory.get("evidence", []) or []):
#         if str(evidence.get("source_type", "")).strip().lower() != "transcript_state":
#             continue
#         try:
#             state = json.loads(str(evidence.get("content", "") or "{}"))
#         except Exception:
#             continue
#         key = json.dumps(state, sort_keys=True) if state else ""
#         if key and key not in seen:
#             seen.add(key)
#             loaded.append(state)
#     return loaded


# def primary_transcript_state(
#     explicit_states: list[dict[str, Any]] | None,
#     semantic_memory: dict[str, Any] | None,
# ) -> dict[str, Any]:
#     """Return the most informative available transcript state."""
#     states = load_transcript_states(explicit_states, semantic_memory)
#     if not states:
#         return {}
#     states.sort(
#         key=lambda item: (
#             len(item.get("completed_courses", []) or []),
#             len(item.get("planned_courses", []) or []),
#             len(item.get("milestones", []) or []),
#         ),
#         reverse=True,
#     )
#     return states[0]


# def _extract_personal_info(text: str) -> dict[str, str]:
#     info: dict[str, str] = {}
#     for pattern, key in _FIELD_PATTERNS:
#         match = re.search(pattern, text, re.I)
#         if match:
#             info[key] = " ".join(match.group(1).split())
#     return info


# def _extract_terms(text: str) -> list[dict[str, Any]]:
#     terms: list[dict[str, Any]] = []
#     seen_terms: set[str] = set()
#     for match in _TERM_HEADER_RE.finditer(text):
#         term = " ".join(match.group("term").split())
#         key = term.casefold()
#         if key in seen_terms:
#             continue
#         seen_terms.add(key)
#         body = match.group("body")
#         courses = _extract_courses(body, term)
#         if not courses and len(body.strip()) < 20:
#             continue
#         completed_courses = [course for course in courses if course.get("status") == "completed"]
#         planned_courses = [course for course in courses if course.get("status") == "planned"]
#         terms.append(
#             {
#                 "term": term,
#                 "completed_courses": completed_courses,
#                 "planned_courses": planned_courses,
#                 "term_gpa": _extract_term_gpa(body),
#             }
#         )
#     return terms


# def _extract_courses(term_text: str, term: str) -> list[dict[str, Any]]:
#     courses: list[dict[str, Any]] = []
#     seen: set[tuple[str, str, str]] = set()
#     for match in _COURSE_LINE_RE.finditer(term_text):
#         code = " ".join(match.group("code").split()).upper()
#         title = " ".join((match.group("title") or "").split())
#         if not code or not title:
#             continue
#         if title.lower().startswith(("attempted earned", "cumulative gpa", "term gpa", "academic standing")):
#             continue
#         grade = (match.group("grade") or "").strip().upper()
#         attempted = match.group("attempted")
#         earned = match.group("earned")
#         status = _course_status(grade, attempted, earned, title)
#         item = {
#             "term": term,
#             "code": code,
#             "title": title,
#             "grade": grade,
#             "attempted_units": attempted or "",
#             "earned_units": earned or "",
#             "status": status,
#         }
#         key = (item["term"], item["code"], item["title"])
#         if key in seen:
#             continue
#         seen.add(key)
#         courses.append(item)
#     return courses


# def _course_status(grade: str, attempted: str | None, earned: str | None, title: str) -> str:
#     lowered_title = title.casefold()
#     if grade in {"IP", "W"}:
#         return "planned"
#     if grade:
#         return "completed"
#     if attempted is not None or earned is not None:
#         return "completed"
#     if any(token in lowered_title for token in ("planned", "registered", "in progress", "enrolled")):
#         return "planned"
#     return "planned"


# def _extract_term_gpa(term_text: str) -> str:
#     for pattern in (
#         r"Term GPA\s+([0-4]\.\d{2,3})",
#         r"Semester GPA\s+([0-4]\.\d{2,3})",
#         r"GPA this term\s+([0-4]\.\d{2,3})",
#     ):
#         match = re.search(pattern, term_text, re.I)
#         if match:
#             return match.group(1)
#     return ""


# def _extract_cumulative_gpa(text: str) -> str:
#     for pattern in (
#         r"Cumulative GPA\s+([0-4]\.\d{2,3})",
#         r"Overall GPA\s+([0-4]\.\d{2,3})",
#         r"Program GPA\s+([0-4]\.\d{2,3})",
#     ):
#         matches = re.findall(pattern, text, re.I)
#         if matches:
#             return matches[-1]
#     return ""


# def _extract_latest_academic_standing(text: str) -> str:
#     for pattern in (
#         r"Academic Standing Effective [^:]+:\s*([A-Z ]+)",
#         r"Academic Standing:\s*([A-Z ]+)",
#         r"Standing:\s*([A-Z ]+)",
#     ):
#         matches = re.findall(pattern, text, re.I)
#         if matches:
#             return " ".join(matches[-1].split())
#     return ""


# def _extract_milestones(text: str) -> list[dict[str, Any]]:
#     section = re.search(
#         r"(?:Non[- ]Course\s+Milestones?|Milestones?|Academic\s+Milestones?)(.*?)(?:End of Transcript|Unofficial Transcript|Totals?\b|\Z)",
#         text,
#         re.S | re.I,
#     )
#     if not section:
#         return []
#     body = section.group(1)
#     programs = re.findall(r"Program:\s*(.+)", body, re.I)
#     descriptions = re.findall(r"(?:Description|Milestone|Requirement):\s*(.+)", body, re.I)
#     statuses = re.findall(r"Status:\s*(.+)", body, re.I)
#     levels = re.findall(r"(?:Milestone Level|Level|Category):\s*(.+)", body, re.I)
#     milestones: list[dict[str, Any]] = []
#     count = max(len(descriptions), len(statuses), len(levels), len(programs))
#     for idx in range(count):
#         description = " ".join((descriptions[idx] if idx < len(descriptions) else "").split())
#         status = " ".join((statuses[idx] if idx < len(statuses) else "").split())
#         level = " ".join((levels[idx] if idx < len(levels) else "").split())
#         program = " ".join((programs[idx] if idx < len(programs) else "").split())
#         if not any((description, status, level, program)):
#             continue
#         milestones.append(
#             {
#                 "program": program,
#                 "description": description,
#                 "name": description,
#                 "status": status,
#                 "level": level,
#             }
#         )
#     return milestones


# def _latest_completed_term(terms: list[dict[str, Any]]) -> str:
#     completed = [term.get("term", "") for term in terms if term.get("completed_courses")]
#     return completed[-1] if completed else ""


# def _upcoming_term(terms: list[dict[str, Any]]) -> str:
#     for term in reversed(terms):
#         if term.get("planned_courses"):
#             return str(term.get("term", ""))
#     return ""
