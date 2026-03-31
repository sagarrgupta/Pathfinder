from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class PromptCase:
    name: str
    query: str


CASES = [
    PromptCase("greeting", "hello"),
    PromptCase("profile_name", "What is my name?"),
    PromptCase("profile_gpa", "What is my GPA right now?"),
    PromptCase("profile_summary", "What do you know about me right now?"),
    PromptCase("career_short", "Based on my profile, suggest two career directions for me in short."),
    PromptCase("career_market", "What jobs can I get this year that fit me?"),
    PromptCase("career_compare", "Compare backend engineer vs data engineer for me."),
    PromptCase("interview_plan", "Prepare me for a backend interview."),
    PromptCase("academic_courses", "What courses should I take next semester?"),
    PromptCase("academic_from_scratch", "Help me plan my semester from scratch."),
    PromptCase("academic_borderline", "Can you help me think through whether moving closer to campus would improve my semester routine?"),
    PromptCase("url_summary", "Review this page for me: https://catalog.csus.edu/course-search/"),
    PromptCase("url_profile_update", "Use this page to update my profile: https://example.com/my-linkedin"),
    PromptCase("preferences", "I prefer remote roles and small teams."),
    PromptCase("followup_recall", "What did you recommend last time?"),
    PromptCase("decision_tradeoff", "I want to decide whether to focus on GPA or projects this semester."),
    PromptCase("course_relevance", "Which kinds of classes would help me for backend roles?"),
    PromptCase("offtopic_borderline", "Should I move closer to campus or stay home?"),
    PromptCase("offtopic_clear", "Write me a blueberry pancake recipe."),
    PromptCase("weather", "What is the weather in Paris today?"),
    PromptCase("smalltalk", "thanks"),
    PromptCase("planning_steps", "Give me a step by step roadmap for landing a backend internship."),
]


def run_case(base_url: str, student_id: str, case: PromptCase, timeout_seconds: float) -> dict[str, Any]:
    try:
        response = requests.post(
            f"{base_url}/api/v1/chat",
            data={"student_id": student_id, "query": case.query},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
    except Exception as exc:
        return {
            "name": case.name,
            "query": case.query,
            "error": {"message": str(exc)},
            "answer": "",
            "done": {},
            "progress": [],
        }

    progress = []
    final_answer = []
    done = {}
    error = None
    for raw_line in response.text.splitlines():
        if raw_line.startswith("event: "):
            current_event = raw_line.split("event: ", 1)[1].strip()
            continue
        if not raw_line.startswith("data: "):
            continue
        payload = raw_line.split("data: ", 1)[1]
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = {"raw": payload}
        if current_event == "progress":
            progress.append(parsed)
        elif current_event == "token":
            final_answer.append(parsed.get("content", ""))
        elif current_event == "done":
            done = parsed
        elif current_event == "error":
            error = parsed

    return {
        "name": case.name,
        "query": case.query,
        "error": error,
        "answer": "".join(final_answer).strip(),
        "done": done,
        "progress": progress,
    }


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8002"
    student_id = sys.argv[2] if len(sys.argv) > 2 else "student_72efc125b7c4"
    timeout_seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 45.0

    results = [run_case(base_url, student_id, case, timeout_seconds) for case in CASES]
    for item in results:
        done = item.get("done", {}) or {}
        metadata = done.get("metadata", {}) or {}
        planner_trace = metadata.get("planner_trace", [])
        method = done.get("method") or metadata.get("method") or ""
        blocked = bool(item.get("error")) or "blocked" in (item.get("answer", "").lower())
        print(
            json.dumps(
                {
                    "name": item["name"],
                    "query": item["query"],
                    "blocked": blocked,
                    "method": method,
                    "confidence": done.get("confidence"),
                    "missing_info": metadata.get("missing_info", []),
                    "sources": metadata.get("sources", []),
                    "planner_trace": planner_trace,
                    "answer_preview": item.get("answer", "")[:220],
                    "error": item.get("error"),
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
