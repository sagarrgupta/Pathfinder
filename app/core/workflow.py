"""Wires the Pathfinder nodes into a LangGraph flow.

Every chat turn walks this graph from `input_guard` down to `responder`.
Each node is a small async function in `app/nodes/` that reads the shared
`PathfinderState` and returns an updated copy. The edges below define the
fixed order; the only branch is the guard deciding whether to short-circuit
straight to the responder (for blocked input) or proceed through the full
pipeline.

High-level flow:
    input_guard -> orchestrator -> query_ingestor -> specialist_runner
                -> response_validator -> context_persister -> responder -> END

The compiled graph is cached behind an async lock so the API server can
build it once and reuse it for every request.
"""

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
    """Register every node and connect them in the fixed turn order.

    We register nodes first, then declare edges. The only conditional edge
    is right after the input guard: blocked turns skip everything and jump
    straight to the responder so we can return the block reason quickly.
    """
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

    # Guard fans out to either the responder (blocked) or the normal path.
    workflow.add_conditional_edges(
        "input_guard",
        lambda state: "responder" if state.get("is_blocked") else "orchestrator",
        {"orchestrator": "orchestrator", "responder": "responder"},
    )
    # Normal path: classify -> harvest facts from query -> answer ->
    # validate/cite -> save context -> render final answer.
    workflow.add_edge("orchestrator", "query_ingestor")
    workflow.add_edge("query_ingestor", "specialist_runner")
    workflow.add_edge("specialist_runner", "response_validator")
    workflow.add_edge("response_validator", "context_persister")
    workflow.add_edge("context_persister", "responder")
    workflow.add_edge("responder", END)

    log.info("Pathfinder workflow built for MCP-first single-specialist flow")
    return workflow


async def get_compiled_workflow():
    """Return the cached compiled graph, building it once per checkpointer.

    Compilation is expensive-ish and only needs to happen once. We key the
    cache by the checkpointer's id() so that if tests swap in a fresh
    checkpointer (e.g., after a reset), the workflow is rebuilt to bind to
    the new storage instead of holding onto the old connection.
    """
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
