"""Pathfinder application settings.

All configuration is loaded from environment variables or .env file.

The .env path is resolved from the repository root (next to ``app/``), not from the
process current working directory, so ``NEO4J_PASSWORD`` and other vars load when
you start the server from any directory.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# app/config/settings.py -> parents[2] == project root (contains app/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
    )

    # ---------- LM Studio (Text + Vision LLM) ----------
    LLM_BASE_URL: str = "http://localhost:1234/v1"
    LLM_MODEL: str = "google/gemma-4-26b-a4b"
    LLM_API_KEY: str = "sk-no-key"
    VISION_MODEL: str = "google/gemma-4-26b-a4b"

    # ---------- Ollama (Embeddings) ----------
    OLLAMA_URL: str = "http://localhost:11434"
    EMBEDDING_MODEL: str = "mxbai-embed-large"
    EMBEDDING_DIMENSIONS: int = 1024

    # ---------- Neo4j ----------
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = ""

    # ---------- SQLite (LangGraph Memory) ----------
    SQLITE_DB_PATH: str = "data/pathfinder.db"
    REPLAY_ARTIFACT_DIR: str = "data/replays"

    TOP_K: int = 6
    CHUNK_SIZE: int = 700
    CHUNK_OVERLAP: int = 120
    
    # ---------- Web Search API Keys ----------
    TAVILY_API_KEY: str = ""
    GOOGLE_CSE_API_KEY: str = ""
    GOOGLE_CSE_ID: str = ""
    BRAVE_API_KEY: str = ""

    # ---------- Guardrails ----------
    TOPIC_GUARD_ENABLED: bool = True

    # ---------- API ----------
    API_V1_PREFIX: str = "/api/v1"
    API_TITLE: str = "Pathfinder API"
    API_VERSION: str = "2.0.0"
    
    # ---------- CORS ----------
    ALLOWED_ORIGINS: list[str] = ["*"]
    
    # ---------- File Upload ----------
    MAX_FILE_SIZE_MB: int = 10
    ALLOWED_FILE_TYPES: list[str] = [".pdf", ".png", ".jpg", ".jpeg", ".heif", ".heic", ".docx"]

    # ---------- LLM Options ----------
    LLM_DEBUG_LOG_ENABLED: bool = False
    LLM_DEBUG_LOG_PATH: str = "data/llm_debug.log"

    # ---------- Server ----------
    HOST: str = "0.0.0.0"
    PORT: int = 8001


settings = Settings()
