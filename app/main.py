"""Pathfinder FastAPI application entry point."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.adapters.neo4j.graph_store import close_driver, init_schema, ensure_student
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

    # Ensure data directory exists
    os.makedirs(os.path.dirname(settings.SQLITE_DB_PATH) or ".", exist_ok=True)

    # Initialize Neo4j schema and vector index
    try:
        await init_schema()
        await ensure_vector_index()
        await ensure_student("default")
        start_background_jobs()
        log.info("Neo4j initialized successfully")
    except Exception as exc:
        log.warning("Neo4j initialization failed (will retry on first use): %s", exc)

    log.info("Pathfinder ready — http://%s:%d", settings.HOST, settings.PORT)
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
