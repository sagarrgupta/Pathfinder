"""LLM chat + tool-calling backends.

Only LM Studio is wired up today (`lmstudio.py`). The adapter exposes a
small async surface the nodes call — send messages + tool schemas,
get back the LLM's next message (which may be a tool call).
"""
