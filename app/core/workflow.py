"""Workflow assembly for the simplified Pathfinder chat flow."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langgraph.graph import END, StateGraph

from app.nodes.input_guard import input_guard
from app.nodes.response_validator import response_validator
from app.nodes.orchestrator import orchestrator
from app.nodes.query_ingestor import query_ingestor
from app.nodes.responder import responder
from app.nodes.specialist_runner import specialist_runner
from app.nodes.context_persister import context_persister
from app.core.checkpointer import get_checkpointer
from app.core.state import PathfinderState

log = logging.getLogger("pathfinder.workflow")

_compiled_workflow: Any | None = None
_compiled_workflow_checkpointer_id: int | None = None
_compiled_workflow_lock = asyncio.Lock()


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
        ("query_ingestor", query_ingestor),
    ):
        workflow.add_node(name, node)

    workflow.set_entry_point("input_guard")

    workflow.add_conditional_edges(
        "input_guard",
        lambda state: "responder" if state.get("is_blocked") else "orchestrator",
        {"orchestrator": "orchestrator", "responder": "responder"},
    )
    workflow.add_edge("orchestrator", "query_ingestor")
    workflow.add_edge("query_ingestor", "specialist_runner")
    workflow.add_edge("specialist_runner", "response_validator")
    workflow.add_edge("response_validator", "context_persister")
    workflow.add_edge("context_persister", "responder")
    workflow.add_edge("responder", END)

    log.info("Pathfinder workflow built for MCP-first single-specialist flow")
    return workflow


async def get_compiled_workflow():
    """Build and compile the workflow with the SQLite checkpointer."""
    checkpointer = await get_checkpointer()
    checkpointer_id = id(checkpointer)

    global _compiled_workflow, _compiled_workflow_checkpointer_id
    if (
        _compiled_workflow is not None
        and _compiled_workflow_checkpointer_id == checkpointer_id
    ):
        return _compiled_workflow

    async with _compiled_workflow_lock:
        checkpointer = await get_checkpointer()
        checkpointer_id = id(checkpointer)
        if (
            _compiled_workflow is None
            or _compiled_workflow_checkpointer_id != checkpointer_id
        ):
            workflow = build_workflow()
            _compiled_workflow = workflow.compile(checkpointer=checkpointer)
            _compiled_workflow_checkpointer_id = checkpointer_id
            log.info("Pathfinder workflow compiled with SqliteSaver checkpointer")

    return _compiled_workflow
