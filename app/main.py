"""Pathfinder FastAPI application entry point."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from neo4j.exceptions import Neo4jError, ServiceUnavailable

from app.adapters.neo4j.graph_store import close_driver, init_schema, list_students, create_student
from app.adapters.neo4j.vector_store import ensure_vector_index
from app.config.settings import settings
from app.services.background_jobs import start_background_jobs, stop_background_jobs

# ── Logging ──────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-30s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pathfinder")


# ── Lifespan ─────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown tasks."""
    log.info("Starting Pathfinder v%s", settings.API_VERSION)
    neo4j_ready = False

    # Ensure data directory exists
    os.makedirs(os.path.dirname(settings.SQLITE_DB_PATH) or ".", exist_ok=True)

    # Initialize Neo4j schema and vector index
    try:
        await init_schema()
        await ensure_vector_index()
        if not await list_students():
            await create_student("Student")
        neo4j_ready = True
        log.info("Neo4j initialized successfully")
    except Exception as exc:
        log.warning("Neo4j initialization failed (will retry on first use): %s", exc)

    log.info("Pathfinder ready — http://%s:%d", settings.HOST, settings.PORT)
    if neo4j_ready:
        start_background_jobs()
    else:
        log.info("Background consolidation not started because Neo4j is unavailable")
    yield

    # Shutdown
    await stop_background_jobs()
    await close_driver()
    log.info("Pathfinder stopped")


# ── Application ──────────────────────────────────────────────────

app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    lifespan=lifespan,
)


@app.exception_handler(ServiceUnavailable)
async def neo4j_unavailable_handler(_, exc: ServiceUnavailable):
    """Return a clean 503 when the primary datastore is unavailable."""
    log.warning("Neo4j unavailable during request: %s", exc)
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Pathfinder's student datastore is currently unavailable. "
            "Please make sure Neo4j is running and try again."
        },
    )


@app.exception_handler(Neo4jError)
async def neo4j_error_handler(_, exc: Neo4jError):
    """Avoid raw Neo4j exceptions leaking through the API."""
    log.warning("Neo4j request error: %s", exc)
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Pathfinder could not complete the request because the student datastore is unavailable."
        },
    )

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
from app.api.routes import router  # noqa: E402

app.include_router(router, prefix=settings.API_V1_PREFIX)


# Root
@app.get("/")
async def root():
    return {"name": "Pathfinder", "version": settings.API_VERSION, "status": "running"}
