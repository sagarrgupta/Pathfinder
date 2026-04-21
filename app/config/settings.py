"""Central configuration for Pathfinder.

Pathfinder reads all knobs (LLM endpoints, database URIs, API keys, limits)
from environment variables or the project `.env` file. Every other module
imports the shared `settings` object from here, so changing a value in one
place updates the entire app — no hard-coded URLs or credentials anywhere.

The `.env` path is resolved relative to the repo root (the folder that holds
`app/`), not the shell's current directory. This means you can start the
server from anywhere and it will still pick up the right credentials.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# app/config/settings.py -> parents[2] == project root (contains app/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Typed view over environment variables with safe defaults.

    Pydantic validates each value at import time, so a bad or missing
    setting fails fast with a clear error instead of crashing deep inside
    a database call or LLM request later on.
    """

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
    )

    # ---------- LM Studio (Text + Vision LLM) ----------
    # Local LLM served via LM Studio's OpenAI-compatible API. Used by every
    # reasoning step: routing, ingestion, and the specialist answer loop.
    LLM_BASE_URL: str = "http://localhost:1234/v1"
    LLM_MODEL: str = "google/gemma-4-26b-a4b"
    LLM_REQUIRE_EXACT_MODEL: bool = False
    LLM_API_KEY: str = "sk-no-key"
    VISION_MODEL: str = "google/gemma-4-26b-a4b"

    # ---------- Ollama (Embeddings) ----------
    # Ollama turns chunk/query text into vectors. Dimension must match the
    # Neo4j vector index; mismatched values will break similarity search.
    OLLAMA_URL: str = "http://localhost:11434"
    EMBEDDING_MODEL: str = "mxbai-embed-large"
    EMBEDDING_DIMENSIONS: int = 1024

    # ---------- Neo4j ----------
    # Single graph database holding every student's knowledge graph plus the
    # chunk vector index. Password is required — the app refuses to start
    # without it so credentials are never silently defaulted in production.
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = ""

    # ---------- SQLite (LangGraph Memory) ----------
    # LangGraph checkpointer storage (chat history / turn state) and the
    # folder where we dump replay artifacts for debugging past turns.
    SQLITE_DB_PATH: str = "data/pathfinder.db"
    REPLAY_ARTIFACT_DIR: str = "data/replays"

    # Retrieval defaults: how many chunks to return, chunk window size, and
    # overlap. Used by the document ingestion path in `doc_analyst`.
    TOP_K: int = 6
    CHUNK_SIZE: int = 700
    CHUNK_OVERLAP: int = 120
    
    # ---------- Web Search API Keys ----------
    # Optional providers; the fallback chain in `adapters/web_search` tries
    # them in order and skips any without a key configured.
    TAVILY_API_KEY: str = ""
    GOOGLE_CSE_API_KEY: str = ""
    GOOGLE_CSE_ID: str = ""
    BRAVE_API_KEY: str = ""

    # ---------- Guardrails ----------
    # Master switch for the input guard node's topic/SQLi filtering.
    TOPIC_GUARD_ENABLED: bool = True

    # ---------- API ----------
    API_V1_PREFIX: str = "/api/v1"
    API_TITLE: str = "Pathfinder API"
    API_VERSION: str = "2.0.0"
    
    # ---------- CORS ----------
    ALLOWED_ORIGINS: list[str] = ["*"]
    
    # ---------- File Upload ----------
    # Guardrails the API layer uses to reject oversized or unexpected files
    # before they reach the ingestion pipeline.
    MAX_FILE_SIZE_MB: int = 10
    ALLOWED_FILE_TYPES: list[str] = [".pdf", ".png", ".jpg", ".jpeg", ".heif", ".heic", ".docx"]

    # ---------- LLM Options ----------
    # Verbose request/response logging for local debugging; off by default
    # because the log grows quickly and contains full prompts.
    LLM_DEBUG_LOG_ENABLED: bool = False
    LLM_DEBUG_LOG_PATH: str = "data/llm_debug.log"

    # ---------- Server ----------
    HOST: str = "0.0.0.0"
    PORT: int = 8001


# Single shared settings instance — import this everywhere instead of
# instantiating Settings again.
settings = Settings()
