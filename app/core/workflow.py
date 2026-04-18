"""Workflow assembly for the simplified Pathfinder chat flow."""

from __future__ import annotations

import logging

from langgraph.graph import END, StateGraph

from app.nodes.input_guard import input_guard
from app.nodes.response_validator import response_validator
from app.nodes.orchestrator import orchestrator
from app.nodes.responder import responder
from app.nodes.specialist_runner import specialist_runner
from app.nodes.context_persister import context_persister
from app.core.checkpointer import get_checkpointer
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.workflow")


def route_after_guard(state: PathfinderState) -> str:
    """After input guard, either stop or continue."""
    return "responder" if state.get("is_blocked") else "orchestrator"


def build_workflow() -> StateGraph:
    """Build the simplified Pathfinder workflow."""
    workflow = StateGraph(PathfinderState)

    for name, node in (
        ("input_guard", input_guard),
        ("orchestrator", orchestrator),
        ("specialist_runner", specialist_runner),
        ("response_validator", response_validator),
        ("context_persister", context_persister),
        ("responder", responder),
    ):
        workflow.add_node(name, node)

    workflow.set_entry_point("input_guard")

    workflow.add_conditional_edges(
        "input_guard",
        route_after_guard,
        {"orchestrator": "orchestrator", "responder": "responder"},
    )
    workflow.add_edge("orchestrator", "specialist_runner")
    workflow.add_edge("specialist_runner", "response_validator")
    workflow.add_edge("response_validator", "context_persister")
    workflow.add_edge("context_persister", "responder")
    workflow.add_edge("responder", END)

    log.info("Pathfinder workflow built for MCP-first single-specialist flow")
    return workflow


async def get_compiled_workflow():
    """Build and compile the workflow with the SQLite checkpointer."""
    workflow = build_workflow()
    checkpointer = await get_checkpointer()
    compiled = workflow.compile(checkpointer=checkpointer)
    log.info("Pathfinder workflow compiled with SqliteSaver checkpointer")
    return compiled
