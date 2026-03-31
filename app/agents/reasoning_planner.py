"""Capability agent: controlled dynamic planner."""

from __future__ import annotations

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.system_context import build_step_system_prompt
from app.adapters.llm.lmstudio import get_text_llm
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.agents.reasoning_planner")

_ALLOWED_CAPABILITIES = {
    "profile_memory_agent",
    "semantic_memory_agent",
    "document_evidence_agent",
    "web_researcher",
    "evidence_judge_agent",
    "conflict_resolution_agent",
    "missing_info_agent",
    "academic_strategy_agent",
    "career_strategy_agent",
    "interview_coach_agent",
    "decision_comparison_agent",
    "document_understanding_agent",
    "plan_action_agent",
    "answer_composer_agent",
    "memory_writer_agent",
    "memory_consolidation_agent",
}

_DYNAMIC_PLANNER_PROMPT = build_step_system_prompt(
    step_name="reasoning_planner",
    objective=(
        "Choose the smallest sufficient capability pipeline for this request and explain whether "
        "web, documents, profile context, evidence fusion, conflict checking, missing-info checks, memory writing, "
        "and deeper planning are required."
    ),
    relevant_capabilities=(
        "profile_memory_agent",
        "semantic_memory_agent",
        "document_evidence_agent",
        "web_researcher",
        "evidence_judge_agent",
        "conflict_resolution_agent",
        "missing_info_agent",
        "academic_strategy_agent",
        "career_strategy_agent",
        "interview_coach_agent",
        "decision_comparison_agent",
        "document_understanding_agent",
        "plan_action_agent",
        "answer_composer_agent",
        "memory_writer_agent",
    ),
    extra_rules=(
        "Turn on web_researcher when the answer needs current or external facts, institutional pages, job market signals, reviews, schedules, catalogs, or any URL content.",
        "Leave web off for pure profile recall, direct profile updates, and purely attached-document analysis unless external evidence materially improves the answer.",
        "Use plan_action_agent when the user wants a roadmap, multi-step plan, from-scratch guidance, or tradeoff-heavy planning.",
        "For lightweight meta/help/clarification requests, prefer a very small path and often skip retrieval entirely.",
        "Choose a primary reasoning agent only when one is clearly needed. Otherwise use none.",
        "Keep must_include minimal but sufficient because code will execute the plan step by step.",
    ),
    output_schema="""
Return ONLY JSON:
{
  "needs_web": true,
  "needs_profile": true,
  "needs_documents": false,
  "reasoning_depth": "light|standard|deep",
  "primary_agent": "academic_strategy_agent|career_strategy_agent|interview_coach_agent|decision_comparison_agent|document_understanding_agent|none",
  "response_mode": "direct|composed",
  "needs_evidence_judge": true,
  "needs_conflict_check": true,
  "needs_missing_info": true,
  "write_memory": true,
  "must_include": ["capability_name"],
  "web_search_hint": "short explanation of what web research should look for",
  "reasoning": "short explanation"
}
""",
)


def _query_requires_web(query: str, domain: str, task_type: str) -> bool:
    lower = (query or "").lower()
    if "http://" in lower or "https://" in lower:
        return True

    academic_external = (
        "next semester",
        "plan my semester",
        "semester from scratch",
        "from scratch",
        "what courses should i take",
        "should i take next semester",
        "course catalog",
        "academic calendar",
        "registration",
        "program requirements",
        "degree requirements",
    )
    career_external = (
        "what jobs can i get",
        "job market",
        "job listing",
        "job listings",
        "open roles",
        "openings",
        "salary",
        "hiring",
    )
    research_external = (
        "review this",
        "summarize this page",
        "read this",
        "compare universities",
        "compare programs",
    )

    if domain == "academic" and any(token in lower for token in academic_external):
        return True
    if domain == "career" and any(token in lower for token in career_external):
        return True
    if domain == "research" and any(token in lower for token in research_external):
        return True
    return False


def _has_external_cues(query: str) -> bool:
    lower = (query or "").lower()
    cues = (
        "http://",
        "https://",
        "today",
        "this year",
        "latest",
        "current",
        "currently",
        "job market",
        "open roles",
        "openings",
        "salary",
        "deadline",
        "deadlines",
        "schedule",
        "catalog",
        "reviews",
        "ranking",
        "compare universities",
        "compare programs",
        "company",
        "companies",
    )
    return any(cue in lower for cue in cues)


def _should_suppress_web(query: str, domain: str, task_type: str) -> bool:
    lower = (query or "").lower()
    if _has_external_cues(query):
        return False
    if domain == "academic" and task_type in {"recommend", "general"}:
        return True
    if domain == "interview":
        return True
    if domain == "career" and any(
        phrase in lower
        for phrase in (
            "based on my profile",
            "based on my background",
            "for me in short",
            "fit me",
            "fit my profile",
        )
    ):
        return True
    return False


def _planner_context(state: PathfinderState) -> str:
    files = state.get("files", []) or []
    filenames = [item.get("filename", "unknown") for item in files[:4]]
    return (
        f"Query: {state.get('query', '')}\n"
        f"Interpreted query: {state.get('interpreted_query', '')}\n"
        f"Interpreted goal: {state.get('interpreted_goal', '')}\n"
        f"Interpreted constraints: {state.get('interpreted_constraints', [])}\n"
        f"Interpreted search brief: {state.get('interpreted_search_brief', '')}\n"
        f"Intent: {state.get('intent', 'general')}\n"
        f"Task type: {state.get('task_type', 'general')}\n"
        f"Current depth: {state.get('reasoning_depth', 'standard')}\n"
        f"Current flags: needs_web={bool(state.get('needs_web'))}, "
        f"needs_documents={bool(state.get('needs_documents'))}, "
        f"needs_profile={bool(state.get('needs_profile', True))}\n"
        f"Files attached: {filenames if filenames else 'none'}\n"
        f"Student id present: {bool(state.get('student_id'))}\n"
        f"Existing retrieval summary: {state.get('retrieval_summary', {}) or 'none'}"
    )


async def _dynamic_planner_refinement(state: PathfinderState) -> dict[str, object]:
    llm = get_text_llm()
    try:
        response = await llm.ainvoke(
            [
                SystemMessage(content=_DYNAMIC_PLANNER_PROMPT),
                HumanMessage(content=_planner_context(state)),
            ]
        )
        content = response.content if isinstance(response.content, str) else str(response.content)
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(content[start:end])
            must_include = [cap for cap in parsed.get("must_include", []) if cap in _ALLOWED_CAPABILITIES]
            depth = str(parsed.get("reasoning_depth", state.get("reasoning_depth", "standard")))
            if depth not in {"light", "standard", "deep"}:
                depth = str(state.get("reasoning_depth", "standard"))
            primary_agent = str(parsed.get("primary_agent", "none")).strip()
            if primary_agent not in {
                "academic_strategy_agent",
                "career_strategy_agent",
                "interview_coach_agent",
                "decision_comparison_agent",
                "document_understanding_agent",
                "none",
            }:
                primary_agent = "none"
            response_mode = str(parsed.get("response_mode", "composed")).strip()
            if response_mode not in {"direct", "composed"}:
                response_mode = "composed"
            return {
                "needs_web": bool(parsed.get("needs_web", False)),
                "needs_profile": bool(parsed.get("needs_profile", state.get("needs_profile", True))),
                "needs_documents": bool(parsed.get("needs_documents", state.get("needs_documents", False))),
                "reasoning_depth": depth,
                "primary_agent": primary_agent,
                "response_mode": response_mode,
                "needs_evidence_judge": bool(parsed.get("needs_evidence_judge", True)),
                "needs_conflict_check": bool(parsed.get("needs_conflict_check", True)),
                "needs_missing_info": bool(parsed.get("needs_missing_info", True)),
                "write_memory": bool(parsed.get("write_memory", depth == "light")),
                "must_include": must_include,
                "web_search_hint": str(parsed.get("web_search_hint", "")).strip(),
                "reasoning": str(parsed.get("reasoning", "")).strip(),
            }
    except Exception as exc:
        log.warning("Dynamic planner refinement failed: %s", exc)

    return {
        "needs_web": False,
        "needs_profile": bool(state.get("needs_profile", True)),
        "needs_documents": bool(state.get("needs_documents", False)),
        "reasoning_depth": str(state.get("reasoning_depth", "standard")),
        "primary_agent": "none",
        "response_mode": "composed",
        "needs_evidence_judge": True,
        "needs_conflict_check": True,
        "needs_missing_info": True,
        "write_memory": str(state.get("reasoning_depth", "standard")) == "light",
        "must_include": [],
        "web_search_hint": "",
        "reasoning": "",
    }


def _refine_reasoning_depth(state: PathfinderState, needs_web: bool, dynamic_depth: str) -> str:
    current_depth = str(state.get("reasoning_depth", "standard"))
    query = (state.get("query") or "").lower()
    intent = str(state.get("intent", "general"))
    task_type = str(state.get("task_type", "general"))

    if dynamic_depth in {"light", "standard", "deep"} and dynamic_depth != current_depth:
        current_depth = dynamic_depth

    deep_markers = (
        "from scratch",
        "step by step",
        "roadmap",
        "plan my semester",
        "long-term plan",
        "compare",
        "tradeoff",
    )
    if current_depth == "deep":
        return current_depth
    if any(marker in query for marker in deep_markers):
        return "deep"
    if intent == "academic" and task_type == "plan" and needs_web:
        return "deep"
    return current_depth


def _merge_required_capabilities(path: list[str], required: list[str]) -> list[str]:
    merged = list(path)

    if "web_researcher" in required and "web_researcher" not in merged:
        insert_at = len(merged)
        for idx, name in enumerate(merged):
            if name in {
                "evidence_judge_agent",
                "conflict_resolution_agent",
                "missing_info_agent",
                "academic_strategy_agent",
                "career_strategy_agent",
                "interview_coach_agent",
                "decision_comparison_agent",
                "document_understanding_agent",
                "plan_action_agent",
                "answer_composer_agent",
            }:
                insert_at = idx
                break
        merged.insert(insert_at, "web_researcher")

    if "plan_action_agent" in required and "plan_action_agent" not in merged:
        insert_at = merged.index("answer_composer_agent") if "answer_composer_agent" in merged else len(merged)
        merged.insert(insert_at, "plan_action_agent")

    for capability in required:
        if capability in {"web_researcher", "plan_action_agent"}:
            continue
        if capability not in merged:
            insert_at = len(merged)
            if capability in {
                "academic_strategy_agent",
                "career_strategy_agent",
                "interview_coach_agent",
                "decision_comparison_agent",
                "document_understanding_agent",
            } and "answer_composer_agent" in merged:
                insert_at = merged.index("answer_composer_agent")
            merged.insert(insert_at, capability)
    return merged


def _build_capability_path(state: PathfinderState, dynamic: dict[str, object]) -> tuple[list[str], dict[str, object]]:
    domain = state.get("intent", "general")
    task_type = state.get("task_type", "general")
    query = state.get("interpreted_query", "") or state.get("query", "")
    files = state.get("files", [])
    needs_web = (
        bool(state.get("needs_web"))
        or bool(dynamic.get("needs_web"))
        or _query_requires_web(state.get("query", ""), domain, task_type)
    )
    required_caps = list(dynamic.get("must_include", []))
    if needs_web and _should_suppress_web(state.get("query", ""), domain, task_type):
        needs_web = False
        required_caps = [cap for cap in required_caps if cap != "web_researcher"]
    needs_documents = bool(state.get("needs_documents")) or bool(dynamic.get("needs_documents"))
    needs_profile = bool(dynamic.get("needs_profile", state.get("needs_profile", True))) or domain in {
        "academic",
        "career",
        "interview",
        "profile",
    }
    depth = _refine_reasoning_depth(state, needs_web, str(dynamic.get("reasoning_depth", "")))
    response_mode = str(dynamic.get("response_mode", "composed"))
    primary_agent = str(dynamic.get("primary_agent", "none"))
    needs_evidence_judge = bool(dynamic.get("needs_evidence_judge", True))
    needs_conflict_check = bool(dynamic.get("needs_conflict_check", True))
    needs_missing_info = bool(dynamic.get("needs_missing_info", True))
    write_memory = bool(dynamic.get("write_memory", depth == "light"))

    if domain == "general" and task_type == "clarify" and not needs_profile and not needs_documents and not needs_web:
        return ["answer_composer_agent"], {
            "needs_web": False,
            "needs_documents": False,
            "needs_profile": False,
            "reasoning_depth": "light",
            "response_mode": "direct",
            "web_search_hint": "",
        }

    if domain == "profile" and state.get("task_type") == "update":
        path = []
        if needs_web or "http" in state.get("query", "").lower():
            path.append("web_researcher")
        path.extend(["profile_memory_agent", "answer_composer_agent", "memory_writer_agent"])
        path = _merge_required_capabilities(path, required_caps)
        return [cap for cap in path if cap in _ALLOWED_CAPABILITIES], {
            "needs_web": needs_web,
            "needs_documents": needs_documents,
            "needs_profile": needs_profile,
            "reasoning_depth": depth,
            "response_mode": response_mode,
            "web_search_hint": str(dynamic.get("web_search_hint", "")).strip(),
        }

    if domain == "profile":
        path = [
            "profile_memory_agent",
            "semantic_memory_agent",
            "missing_info_agent",
            "answer_composer_agent",
            "memory_writer_agent",
        ]
        path = _merge_required_capabilities(path, required_caps)
        return [cap for cap in path if cap in _ALLOWED_CAPABILITIES], {
            "needs_web": needs_web,
            "needs_documents": needs_documents,
            "needs_profile": needs_profile,
            "reasoning_depth": depth,
            "response_mode": response_mode,
            "web_search_hint": str(dynamic.get("web_search_hint", "")).strip(),
        }

    path = []
    if files or needs_documents or domain == "document":
        path.append("document_evidence_agent")
    if needs_profile:
        path.extend(["profile_memory_agent", "semantic_memory_agent"])
    if needs_web or domain == "research" or "http" in state.get("query", "").lower():
        path.append("web_researcher")
    if needs_evidence_judge and path:
        path.append("evidence_judge_agent")
    if needs_conflict_check and needs_profile:
        path.append("conflict_resolution_agent")
    if needs_missing_info:
        path.append("missing_info_agent")

    if primary_agent == "none":
        if task_type == "compare":
            primary_agent = "decision_comparison_agent"
        elif domain == "academic":
            primary_agent = "academic_strategy_agent"
        elif domain == "career":
            primary_agent = "career_strategy_agent"
        elif domain == "interview":
            primary_agent = "interview_coach_agent"
        elif domain == "document":
            primary_agent = "document_understanding_agent"
        elif any(cap in path for cap in {"profile_memory_agent", "semantic_memory_agent", "document_evidence_agent", "web_researcher"}):
            primary_agent = "decision_comparison_agent"

    if primary_agent != "none":
        path.append(primary_agent)

    if depth == "deep":
        path.append("plan_action_agent")
        response_mode = "composed"
    path.append("answer_composer_agent")
    if write_memory:
        path.append("memory_writer_agent")

    path = _merge_required_capabilities(path, required_caps)
    return [cap for cap in path if cap in _ALLOWED_CAPABILITIES], {
        "needs_web": needs_web,
        "needs_documents": needs_documents,
        "needs_profile": needs_profile,
        "reasoning_depth": depth,
        "response_mode": response_mode,
        "web_search_hint": str(dynamic.get("web_search_hint", "")).strip(),
    }


async def reasoning_planner(state: PathfinderState) -> PathfinderState:
    """Choose a bounded capability path for this question."""
    dynamic = await _dynamic_planner_refinement(state)
    capabilities, refinements = _build_capability_path(state, dynamic)
    planner_trace = list(state.get("planner_trace", []))
    if refinements.get("needs_web") and not state.get("needs_web"):
        planner_trace.append("planner_refinement:enabled_web")
    if refinements.get("reasoning_depth") != state.get("reasoning_depth"):
        planner_trace.append(f"planner_refinement:depth={refinements['reasoning_depth']}")
    if dynamic.get("must_include"):
        planner_trace.append("planner_refinement:must_include=" + ",".join(dynamic["must_include"]))
    planner_trace.append("planner:" + "->".join(capabilities))

    step_progress = list(state.get("step_progress", []))
    step_progress.append(f"Planner selected {len(capabilities)} capabilities")

    answer_style = "direct_specialist" if refinements.get("response_mode") == "direct" else "composed"
    answer_rationale = list(state.get("answer_rationale", []))
    if dynamic.get("reasoning"):
        answer_rationale.append(f"Planner rationale: {dynamic['reasoning']}")

    return {
        **state,
        "active_capabilities": capabilities,
        "needs_web": bool(refinements.get("needs_web", state.get("needs_web"))),
        "needs_documents": bool(refinements.get("needs_documents", state.get("needs_documents"))),
        "needs_profile": bool(refinements.get("needs_profile", state.get("needs_profile", True))),
        "reasoning_depth": str(refinements.get("reasoning_depth", state.get("reasoning_depth", "standard"))),
        "web_search_hint": str(refinements.get("web_search_hint", state.get("web_search_hint", ""))),
        "answer_style": answer_style,
        "answer_rationale": answer_rationale,
        "planner_trace": planner_trace,
        "step_progress": step_progress,
    }
