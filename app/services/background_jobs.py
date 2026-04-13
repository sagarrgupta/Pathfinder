"""Lightweight background jobs for Pathfinder."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Optional

from neo4j.exceptions import AuthError, Neo4jError

from app.adapters.neo4j.graph_store import list_students
from app.services.consolidation import maybe_consolidate_memory

log = logging.getLogger("pathfinder.background")

_CONSOLIDATION_INTERVAL_SECONDS = 900


@dataclass
class BackgroundStatus:
    running: bool = False
    interval_seconds: int = _CONSOLIDATION_INTERVAL_SECONDS
    last_started_at: str | None = None
    last_finished_at: str | None = None
    last_run_profiles: int = 0
    last_error: str | None = None


_task: Optional[asyncio.Task] = None
_status = BackgroundStatus()


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_neo4j_auth_error(exc: Exception) -> bool:
    """Return True when the exception is a Neo4j authentication failure."""
    if isinstance(exc, AuthError):
        return True
    if isinstance(exc, Neo4jError):
        code = str(getattr(exc, "code", "") or "")
        return code.startswith("Neo.ClientError.Security.")
    return False


async def _background_loop() -> None:
    _status.running = True
    _status.last_started_at = _utc_timestamp()
    try:
        while True:
            try:
                students = await list_students()
                count = 0
                for student in students:
                    student_id = student.get("id")
                    if not student_id:
                        continue
                    try:
                        await maybe_consolidate_memory(student_id, "background_loop")
                        count += 1
                    except Exception as exc:
                        log.warning("Background consolidation failed for %s: %s", student_id, exc)
                _status.last_run_profiles = count
                _status.last_finished_at = _utc_timestamp()
                _status.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _status.last_error = str(exc)
                if _is_neo4j_auth_error(exc):
                    log.error(
                        "Background consolidation disabled due to Neo4j authentication failure. "
                        "Fix Neo4j credentials and restart Pathfinder. Error: %s",
                        exc,
                    )
                    break
                log.warning("Background consolidation scan failed: %s", exc)
            await asyncio.sleep(_CONSOLIDATION_INTERVAL_SECONDS)
    finally:
        _status.running = False


def start_background_jobs() -> None:
    """Start periodic background consolidation loop if not running."""
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_background_loop(), name="pathfinder-background-consolidation")
    log.info("Started background consolidation loop")


async def stop_background_jobs() -> None:
    """Stop periodic background loop cleanly."""
    global _task
    if _task is None:
        _status.running = False
        return
    _task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _task
    _task = None
    _status.running = False
    log.info("Stopped background consolidation loop")


def get_background_status() -> dict[str, Any]:
    """Return current background job status for observability."""
    status = asdict(_status)
    status["active_task"] = _task is not None and not _task.done()
    return status


async def consolidation_loop() -> None:
    """Backward-compatible loop entry used by existing startup wiring."""
    await _background_loop()
