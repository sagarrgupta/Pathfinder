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
    """Close checkpointer connection and remove persisted chat storage."""
    global _checkpointer
    if _checkpointer is not None:
        try:
            conn = getattr(_checkpointer, "conn", None)
            if conn is not None:
                await conn.close()
        except Exception:
            pass
        _checkpointer = None

    for suffix in ("", "-wal", "-shm"):
        path = f"{settings.SQLITE_DB_PATH}{suffix}"
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
