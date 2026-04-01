"""LangGraph StateGraph assembly.

Builds the Pathfinder multi-agent graph with conditional routing.
This is the heart of the system — all 10+1 nodes connected by
conditional edges that the Orchestrator controls.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, StateGraph

from app.agents.input_guard import input_guard
from app.agents.orchestrator import orchestrator
from app.agents.clarifier import clarifier
from app.agents.doc_analyst import doc_analyst
from app.agents.profile_manager import profile_manager
from app.agents.web_researcher import web_researcher
from app.agents.fact_extractor import fact_extractor
from app.agents.course_planner import course_planner
from app.agents.program_advisor import program_advisor
from app.agents.career_matcher import career_matcher
from app.agents.eligibility_reasoner import eligibility_reasoner
from app.agents.academic_advisor import academic_advisor
from app.agents.career_planner import career_planner
from app.agents.interview_prep import interview_prep
from app.agents.evaluator import evaluator
from app.agents.responder import responder
from app.core.memory import get_checkpointer
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.graph")


# ── Conditional Routing Functions ────────────────────────────────


def route_after_guard(state: PathfinderState) -> str:
    """After Input Guard: if blocked, go to responder; else orchestrator."""
    if state.get("is_blocked"):
        return "responder"
    return "orchestrator"


def route_after_orchestrator(state: PathfinderState) -> str:
    """After Orchestrator: route to the first node in the plan."""
    next_node = state.get("next_node", "responder")
    # Map valid node names
    valid_nodes = {
        "clarifier", "doc_analyst", "profile_manager", "web_researcher",
        "fact_extractor", "course_planner", "program_advisor", "career_matcher",
        "eligibility_reasoner",
        "academic_advisor", "career_planner", "interview_prep",
        "evaluator", "responder",
    }
    if next_node in valid_nodes:
        return next_node
    return "responder"


def route_after_agent(state: PathfinderState) -> str:
    """Generic routing: follow the next_node set by the previous agent."""
    next_node = state.get("next_node", "evaluator")
    valid_nodes = {
        "profile_manager", "web_researcher", "academic_advisor",
        "fact_extractor", "course_planner", "program_advisor", "career_matcher", "eligibility_reasoner",
        "career_planner", "interview_prep", "evaluator", "responder",
    }
    if next_node in valid_nodes:
        return next_node
    return "evaluator"


# ── Graph Builder ────────────────────────────────────────────────


def build_graph() -> StateGraph:
    """Build and return the Pathfinder StateGraph (uncompiled)."""
    graph = StateGraph(PathfinderState)

    # Register all nodes
    graph.add_node("input_guard", input_guard)
    graph.add_node("orchestrator", orchestrator)
    graph.add_node("clarifier", clarifier)
    graph.add_node("doc_analyst", doc_analyst)
    graph.add_node("profile_manager", profile_manager)
    graph.add_node("web_researcher", web_researcher)
    graph.add_node("fact_extractor", fact_extractor)
    graph.add_node("course_planner", course_planner)
    graph.add_node("program_advisor", program_advisor)
    graph.add_node("career_matcher", career_matcher)
    graph.add_node("eligibility_reasoner", eligibility_reasoner)
    graph.add_node("academic_advisor", academic_advisor)
    graph.add_node("career_planner", career_planner)
    graph.add_node("interview_prep", interview_prep)
    graph.add_node("evaluator", evaluator)
    graph.add_node("responder", responder)

    # Entry point
    graph.set_entry_point("input_guard")

    # Input Guard → Orchestrator or Responder (if blocked)
    graph.add_conditional_edges(
        "input_guard",
        route_after_guard,
        {"orchestrator": "orchestrator", "responder": "responder"},
    )

    # Orchestrator → any agent node
    graph.add_conditional_edges(
        "orchestrator",
        route_after_orchestrator,
        {
            "clarifier": "clarifier",
            "doc_analyst": "doc_analyst",
            "profile_manager": "profile_manager",
            "web_researcher": "web_researcher",
            "fact_extractor": "fact_extractor",
            "course_planner": "course_planner",
            "program_advisor": "program_advisor",
            "career_matcher": "career_matcher",
            "eligibility_reasoner": "eligibility_reasoner",
            "academic_advisor": "academic_advisor",
            "career_planner": "career_planner",
            "interview_prep": "interview_prep",
            "evaluator": "evaluator",
            "responder": "responder",
        },
    )

    # Clarifier → Responder (always — it asks the user for info)
    graph.add_edge("clarifier", "responder")

    # Doc Analyst → next in plan
    graph.add_conditional_edges("doc_analyst", route_after_agent, {
        "profile_manager": "profile_manager",
        "web_researcher": "web_researcher",
        "fact_extractor": "fact_extractor",
        "course_planner": "course_planner",
        "program_advisor": "program_advisor",
        "career_matcher": "career_matcher",
        "eligibility_reasoner": "eligibility_reasoner",
        "academic_advisor": "academic_advisor",
        "career_planner": "career_planner",
        "interview_prep": "interview_prep",
        "evaluator": "evaluator",
        "responder": "responder",
    })

    # Profile Manager → next in plan
    graph.add_conditional_edges("profile_manager", route_after_agent, {
        "web_researcher": "web_researcher",
        "fact_extractor": "fact_extractor",
        "course_planner": "course_planner",
        "program_advisor": "program_advisor",
        "career_matcher": "career_matcher",
        "eligibility_reasoner": "eligibility_reasoner",
        "academic_advisor": "academic_advisor",
        "career_planner": "career_planner",
        "interview_prep": "interview_prep",
        "evaluator": "evaluator",
        "responder": "responder",
    })

    # Web Researcher → next in plan
    graph.add_conditional_edges("web_researcher", route_after_agent, {
        "fact_extractor": "fact_extractor",
        "course_planner": "course_planner",
        "program_advisor": "program_advisor",
        "career_matcher": "career_matcher",
        "eligibility_reasoner": "eligibility_reasoner",
        "academic_advisor": "academic_advisor",
        "career_planner": "career_planner",
        "interview_prep": "interview_prep",
        "evaluator": "evaluator",
        "responder": "responder",
    })

    # Fact Extractor → next in plan
    graph.add_conditional_edges("fact_extractor", route_after_agent, {
        "course_planner": "course_planner",
        "program_advisor": "program_advisor",
        "career_matcher": "career_matcher",
        "academic_advisor": "academic_advisor",
        "career_planner": "career_planner",
        "interview_prep": "interview_prep",
        "evaluator": "evaluator",
        "responder": "responder",
    })

    # Advisory/Career/Interview nodes → Evaluator
    graph.add_edge("course_planner", "evaluator")
    graph.add_edge("program_advisor", "evaluator")
    graph.add_edge("career_matcher", "evaluator")
    graph.add_edge("eligibility_reasoner", "evaluator")
    graph.add_edge("academic_advisor", "evaluator")
    graph.add_edge("career_planner", "evaluator")
    graph.add_edge("interview_prep", "evaluator")

    # Evaluator → Responder
    graph.add_edge("evaluator", "responder")

    # Responder → END
    graph.add_edge("responder", END)

    log.info("Pathfinder StateGraph built with extended quality nodes")
    return graph


async def get_compiled_graph():
    """Build and compile the graph with the SQLite checkpointer."""
    graph = build_graph()
    checkpointer = await get_checkpointer()
    compiled = graph.compile(checkpointer=checkpointer)
    log.info("Pathfinder graph compiled with SqliteSaver checkpointer")
    return compiled
