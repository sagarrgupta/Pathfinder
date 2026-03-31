"""Background job loop for periodic consolidation."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Optional

from app.adapters.neo4j.graph_store import list_students
from app.config.settings import settings
from app.services.consolidation import maybe_consolidate_memory

log = logging.getLogger("pathfinder.background")


@dataclass
class BackgroundStatus:
    running: bool = False
    interval_seconds: int = 0
    last_started_at: str | None = None
    last_finished_at: str | None = None
    last_run_profiles: int = 0
    last_error: str | None = None


_task: Optional[asyncio.Task] = None
_status = BackgroundStatus(interval_seconds=settings.CONSOLIDATION_INTERVAL_SECONDS)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def _background_loop() -> None:
    _status.running = True
    _status.last_started_at = _utc_timestamp()
    while True:
        try:
            students = await list_students()
            count = 0
            for student in students:
                await maybe_consolidate_memory(student["id"], "periodic")
                count += 1
            _status.last_run_profiles = count
            _status.last_finished_at = _utc_timestamp()
            _status.last_error = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _status.last_error = str(exc)
            log.warning("Periodic consolidation failed: %s", exc)
        await asyncio.sleep(max(60, settings.CONSOLIDATION_INTERVAL_SECONDS))


def start_background_jobs() -> None:
    """Start periodic background jobs if enabled."""
    global _task
    if not settings.CONSOLIDATION_ENABLED or _task is not None:
        return
    _task = asyncio.create_task(_background_loop(), name="pathfinder-background-consolidation")
    log.info("Started background consolidation loop")


async def stop_background_jobs() -> None:
    """Stop periodic background jobs cleanly."""
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
    """Return background job health/status."""
    status = asdict(_status)
    status["enabled"] = settings.CONSOLIDATION_ENABLED
    status["active_task"] = _task is not None and not _task.done()
    return status
