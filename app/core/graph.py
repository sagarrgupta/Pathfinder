"""LangGraph assembly for the simplified MCP-first Pathfinder flow."""

from __future__ import annotations

import logging

from langgraph.graph import END, StateGraph

from app.agents.input_guard import input_guard
from app.agents.light_validator import light_validator
from app.agents.orchestrator import orchestrator
from app.agents.responder import responder
from app.agents.specialist_runner import specialist_runner
from app.core.memory import get_checkpointer
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.graph")


def route_after_guard(state: PathfinderState) -> str:
    """After input guard, either stop with responder or continue to orchestration."""
    if state.get("is_blocked"):
        return "responder"
    return "orchestrator"


def route_after_orchestrator(state: PathfinderState) -> str:
    """The orchestrator either dispatches to the specialist or short-circuits."""
    next_node = str(state.get("next_node", "specialist_runner") or "specialist_runner")
    if next_node in {"specialist_runner", "responder"}:
        return next_node
    return "specialist_runner"


def route_after_specialist(state: PathfinderState) -> str:
    """The specialist usually goes through validation before response rendering."""
    next_node = str(state.get("next_node", "light_validator") or "light_validator")
    if next_node in {"light_validator", "responder"}:
        return next_node
    return "light_validator"


def route_after_validator(state: PathfinderState) -> str:
    """The validator can only forward to the responder."""
    return "responder"


def build_graph() -> StateGraph:
    """Build the simplified Pathfinder graph."""
    graph = StateGraph(PathfinderState)

    graph.add_node("input_guard", input_guard)
    graph.add_node("orchestrator", orchestrator)
    graph.add_node("specialist_runner", specialist_runner)
    graph.add_node("light_validator", light_validator)
    graph.add_node("responder", responder)

    graph.set_entry_point("input_guard")

    graph.add_conditional_edges(
        "input_guard",
        route_after_guard,
        {"orchestrator": "orchestrator", "responder": "responder"},
    )
    graph.add_conditional_edges(
        "orchestrator",
        route_after_orchestrator,
        {"specialist_runner": "specialist_runner", "responder": "responder"},
    )
    graph.add_conditional_edges(
        "specialist_runner",
        route_after_specialist,
        {"light_validator": "light_validator", "responder": "responder"},
    )
    graph.add_conditional_edges(
        "light_validator",
        route_after_validator,
        {"responder": "responder"},
    )
    graph.add_edge("responder", END)

    log.info("Pathfinder StateGraph built for MCP-first single-specialist flow")
    return graph


async def get_compiled_graph():
    """Build and compile the graph with the SQLite checkpointer."""
    graph = build_graph()
    checkpointer = await get_checkpointer()
    compiled = graph.compile(checkpointer=checkpointer)
    log.info("Pathfinder graph compiled with SqliteSaver checkpointer")
    return compiled
