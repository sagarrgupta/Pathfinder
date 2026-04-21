"""SQLite-backed memory for LangGraph so chat sessions survive restarts.

LangGraph checkpoints the full `PathfinderState` after every node runs.
Without a checkpointer, restarting the server would wipe all chat history
and mid-turn progress. We use a single SQLite file on disk for simplicity
— good enough for single-node deployments; swap for Postgres/Redis later
if we need to scale horizontally.
"""

import aiosqlite
import os
from typing import Optional

from app.config.settings import settings
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


_checkpointer: Optional[AsyncSqliteSaver] = None


async def get_checkpointer() -> AsyncSqliteSaver:
    """Lazy-init and return the one shared SQLite checkpointer.

    The file path comes from `settings.SQLITE_DB_PATH`. We create the parent
    folder if missing and call `.setup()` once so LangGraph creates its
    tables on a fresh database. All callers share the same instance, which
    is how LangGraph correlates checkpoints with the compiled workflow.
    """
    global _checkpointer
    if _checkpointer is None:
        db_dir = os.path.dirname(settings.SQLITE_DB_PATH)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        conn = await aiosqlite.connect(settings.SQLITE_DB_PATH)
        _checkpointer = AsyncSqliteSaver(conn)
        await _checkpointer.setup()
    return _checkpointer


async def reset_checkpointer_storage() -> None:
    """Wipe all stored chat history (used by the admin reset endpoint).

    Closes the active connection, then deletes the main DB file plus the
    `-wal`/`-shm` sidecars SQLite creates in write-ahead-log mode. The next
    `get_checkpointer()` call will rebuild an empty database.
    """
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
