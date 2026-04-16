"""Pathfinder FastAPI application entry point."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import settings
from app.adapters.neo4j.graphDB import GraphDB
from app.tools.graph_tools import close_driver as close_graph_driver
from app.tools.graph_tools import get_driver as get_graph_driver
from app.tools.vector_tools import close_driver as close_vector_driver
from app.tools.vector_tools import get_driver as get_vector_driver
from app.adapters.neo4j.vectorDB import VectorDB

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
        graph_driver = await get_graph_driver()
        await GraphDB(graph_driver).init_schema()

        vector_driver = await get_vector_driver()
        await VectorDB(
            vector_driver,
            index_name="chunk_embeddings",
            dimensions=int(settings.EMBEDDING_DIMENSIONS),
        ).create_vector_index()
        log.info("Neo4j initialized successfully")
    except Exception as exc:
        log.warning("Neo4j initialization failed (will retry on first use): %s", exc)

    log.info("Pathfinder ready — http://%s:%d", settings.HOST, settings.PORT)
    yield

    # Shutdown
    await close_graph_driver()
    await close_vector_driver()
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
