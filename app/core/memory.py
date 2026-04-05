"""Persistent conversation memory via LangGraph SqliteSaver.

Provides the checkpointer used by LangGraph to persist conversation
history across server restarts.
"""

from __future__ import annotations

import os
from typing import Optional

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.config.settings import settings

_checkpointer: Optional[AsyncSqliteSaver] = None
    
    
async def get_checkpointer() -> AsyncSqliteSaver:
    """Return the singleton SQLite checkpointer."""
    global _checkpointer
    if _checkpointer is None:
        # Ensure the data directory exists
        db_dir = os.path.dirname(settings.SQLITE_DB_PATH)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        conn = await aiosqlite.connect(settings.SQLITE_DB_PATH)
        _checkpointer = AsyncSqliteSaver(conn)
        await _checkpointer.setup()
    return _checkpointer


async def reset_checkpointer_storage() -> None:
    """Close and delete the SQLite checkpointer store.

    Used by the destructive "delete all data" route so persisted LangGraph
    conversation state is removed alongside graph/profile data.
    """
    global _checkpointer

    if _checkpointer is not None:
        try:
            await _checkpointer.conn.close()
        except Exception:
            pass
        _checkpointer = None

    try:
        if settings.SQLITE_DB_PATH and os.path.exists(settings.SQLITE_DB_PATH):
            os.remove(settings.SQLITE_DB_PATH)
    except FileNotFoundError:
        pass

    # Reset the compiled graph so the next request rebuilds it with a fresh
    # checkpointer connection.
    try:
        from app.core import graph as graph_module

        if hasattr(graph_module, "_compiled_graph"):
            graph_module._compiled_graph = None
    except Exception:
        pass
