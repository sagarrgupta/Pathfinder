"""FastAPI application entry point for Pathfinder.

This file is what `uvicorn app.main:app` actually runs. It stitches
together three process-level concerns:

1. Logging — a single root format so every subsystem's messages line up.
2. Lifespan — on startup, make sure the SQLite data directory exists,
   initialize the Neo4j schema, and create the vector index; on
   shutdown, close the shared Neo4j drivers cleanly. If Neo4j is not
   reachable at startup the app still boots — drivers are lazily
   re-tried on first use so local dev doesn't hard-fail.
3. App wiring — build the `FastAPI` instance, add permissive CORS (the
   allowed origins are configurable in `settings`), and mount the API
   router under `settings.API_V1_PREFIX`.

Business logic lives in `app.nodes` / `app.tools`; this file just owns
the HTTP surface and the process lifecycle around it.
"""

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
    """Run once at process startup and once at shutdown.

    Startup: make sure the SQLite checkpoint directory exists, then
    bring Neo4j up to a usable state (constraints + vector index).
    Shutdown: close shared Neo4j drivers so connections aren't leaked.
    """
    log.info("Starting Pathfinder v%s", settings.API_VERSION)

    os.makedirs(os.path.dirname(settings.SQLITE_DB_PATH) or ".", exist_ok=True)

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

    await close_graph_driver()
    await close_vector_driver()
    log.info("Pathfinder stopped")


# ── Application ──────────────────────────────────────────────────

app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api.routes import router  # noqa: E402

app.include_router(router, prefix=settings.API_V1_PREFIX)


@app.get("/")
async def root():
    """Tiny liveness endpoint — doesn't touch Neo4j or the LLM."""
    return {"name": "Pathfinder", "version": settings.API_VERSION, "status": "running"}
