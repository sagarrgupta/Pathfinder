"""Core runtime package.

This folder holds the building blocks that tie Pathfinder together:
- `state.py`: the shared dictionary every node reads/writes per turn.
- `workflow.py`: the LangGraph wiring that orders the nodes into a flow.
- `checkpointer.py`: SQLite storage that remembers chat history across restarts.
- `prompts.py`: the system prompts that shape each agent's behavior.

Other packages (`nodes`, `tools`, `services`, `api`) depend on this folder,
but nothing in here depends back on them — it is the bottom of the stack.
"""
