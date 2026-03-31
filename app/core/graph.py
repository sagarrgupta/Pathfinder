"""Controlled dynamic LangGraph runtime for Pathfinder."""

from __future__ import annotations

import logging

from langgraph.graph import END, StateGraph

from app.agents.academic_strategy_agent import academic_strategy_agent
from app.agents.answer_composer_agent import answer_composer_agent
from app.agents.career_strategy_agent import career_strategy_agent
from app.agents.conflict_resolution_agent import conflict_resolution_agent
from app.agents.decision_comparison_agent import decision_comparison_agent
from app.agents.document_evidence_agent import document_evidence_agent
from app.agents.document_understanding_agent import document_understanding_agent
from app.agents.evidence_judge_agent import evidence_judge_agent
from app.agents.guardrail_agent import guardrail_agent
from app.agents.interview_coach_agent import interview_coach_agent
from app.agents.memory_consolidation_agent import memory_consolidation_agent
from app.agents.memory_writer_agent import memory_writer_agent
from app.agents.missing_info_agent import missing_info_agent
from app.agents.profile_memory_agent import profile_memory_agent
from app.agents.question_triage import question_triage
from app.agents.query_interpreter_agent import query_interpreter_agent
from app.agents.reasoning_planner import reasoning_planner
from app.agents.semantic_memory_agent import semantic_memory_agent
from app.agents.plan_action_agent import plan_action_agent
from app.agents.web_researcher import web_researcher
from app.core.memory import get_checkpointer
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.graph")

_CAPABILITY_NODES = {
    "profile_memory_agent": profile_memory_agent,
    "semantic_memory_agent": semantic_memory_agent,
    "document_evidence_agent": document_evidence_agent,
    "web_researcher": web_researcher,
    "evidence_judge_agent": evidence_judge_agent,
    "conflict_resolution_agent": conflict_resolution_agent,
    "missing_info_agent": missing_info_agent,
    "academic_strategy_agent": academic_strategy_agent,
    "career_strategy_agent": career_strategy_agent,
    "interview_coach_agent": interview_coach_agent,
    "decision_comparison_agent": decision_comparison_agent,
    "document_understanding_agent": document_understanding_agent,
    "plan_action_agent": plan_action_agent,
    "answer_composer_agent": answer_composer_agent,
    "memory_writer_agent": memory_writer_agent,
    "memory_consolidation_agent": memory_consolidation_agent,
}


def _next_capability(current: str, state: PathfinderState) -> str:
    capabilities = state.get("active_capabilities", [])
    if not capabilities:
        return END
    try:
        idx = capabilities.index(current)
    except ValueError:
        return capabilities[0]
    if idx + 1 < len(capabilities):
        return capabilities[idx + 1]
    return END


def _route_after_guard(state: PathfinderState) -> str:
    return "answer_composer_agent" if state.get("is_blocked") else "query_interpreter_agent"


def _route_after_interpreter(_state: PathfinderState) -> str:
    return "question_triage"


def _route_after_triage(state: PathfinderState) -> str:
    return "answer_composer_agent" if state.get("intent") == "greeting" else "reasoning_planner"


def _route_after_planner(state: PathfinderState) -> str:
    capabilities = state.get("active_capabilities", [])
    return capabilities[0] if capabilities else "answer_composer_agent"


def build_graph() -> StateGraph:
    """Build the controlled dynamic runtime graph."""
    graph = StateGraph(PathfinderState)
    graph.add_node("guardrail_agent", guardrail_agent)
    graph.add_node("query_interpreter_agent", query_interpreter_agent)
    graph.add_node("question_triage", question_triage)
    graph.add_node("reasoning_planner", reasoning_planner)

    for name, node in _CAPABILITY_NODES.items():
        graph.add_node(name, node)

    graph.set_entry_point("guardrail_agent")
    graph.add_conditional_edges(
        "guardrail_agent",
        _route_after_guard,
        {"query_interpreter_agent": "query_interpreter_agent", "answer_composer_agent": "answer_composer_agent"},
    )
    graph.add_conditional_edges(
        "query_interpreter_agent",
        _route_after_interpreter,
        {"question_triage": "question_triage"},
    )
    graph.add_conditional_edges(
        "question_triage",
        _route_after_triage,
        {"reasoning_planner": "reasoning_planner", "answer_composer_agent": "answer_composer_agent"},
    )
    graph.add_conditional_edges(
        "reasoning_planner",
        _route_after_planner,
        {name: name for name in _CAPABILITY_NODES},
    )

    for name in _CAPABILITY_NODES:
        graph.add_conditional_edges(
            name,
            lambda state, current=name: _next_capability(current, state),
            {**{node_name: node_name for node_name in _CAPABILITY_NODES}, END: END},
        )

    log.info("Pathfinder dynamic graph built with %d capability nodes", len(_CAPABILITY_NODES))
    return graph


_compiled_graph = None


async def get_compiled_graph():
    """Compile the graph once and reuse it across requests."""
    global _compiled_graph
    if _compiled_graph is None:
        graph = build_graph()
        checkpointer = await get_checkpointer()
        _compiled_graph = graph.compile(checkpointer=checkpointer)
        log.info("Pathfinder graph compiled with SqliteSaver checkpointer")
    return _compiled_graph
