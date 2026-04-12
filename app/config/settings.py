"""Pathfinder application settings.

All configuration is loaded from environment variables or .env file.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # ---------- LM Studio (Text + Vision LLM) ----------
    LLM_BASE_URL: str = "http://localhost:1234/v1"
    LLM_MODEL: str = "qwen/qwen3-14b"
    LLM_API_KEY: str = "sk-no-key"
    VISION_MODEL: str = "qwen/qwen3-vl-8b"
    LLM_TEMPERATURE: float = 0.2

    # ---------- Ollama (Embeddings) ----------
    OLLAMA_URL: str = "http://localhost:11434"
    EMBEDDING_MODEL: str = "mxbai-embed-large"
    EMBEDDING_DIMENSIONS: int = 1024

    # ---------- Neo4j ----------
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    # Matches the repo's local docker-compose Neo4j setup. Real env vars still override this.
    NEO4J_PASSWORD: str = "pathfinder123"

    # ---------- SQLite (LangGraph Memory) ----------
    SQLITE_DB_PATH: str = "data/pathfinder.db"
    REPLAY_ARTIFACT_DIR: str = "data/replays"

    # ---------- Retrieval ----------
    TOP_K: int = 5
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 100
    
    # ---------- Web Search API Keys ----------
    TAVILY_API_KEY: str = ""
    GOOGLE_CSE_API_KEY: str = ""
    GOOGLE_CSE_ID: str = ""
    BRAVE_API_KEY: str = ""

    # ---------- Guardrails ----------
    TOPIC_GUARD_ENABLED: bool = True

    # ---------- Session ----------
    SESSION_TTL_MINUTES: int = 60
    MAX_CONVERSATION_HISTORY_MESSAGES: int = 20
    
    # ---------- Rate Limiting ----------
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_MINUTE: int = 60
    
    # ---------- API ----------
    API_V1_PREFIX: str = "/api/v1"
    API_TITLE: str = "Pathfinder API"
    API_VERSION: str = "2.0.0"
    
    # ---------- CORS ----------
    ALLOWED_ORIGINS: list[str] = ["*"]
    
    # ---------- File Upload ----------
    MAX_FILE_SIZE_MB: int = 10
    ALLOWED_FILE_TYPES: list[str] = [".pdf", ".png", ".jpg", ".jpeg", ".heif", ".heic", ".docx"]

    # ---------- LLM Limits ----------
    # Keep a generous token budget for local reasoning models to avoid
    # empty responses on longer multi-step tasks.
    LLM_MAX_TOKENS: int = 16384
    LLM_REQUEST_TIMEOUT: float = 300.0   # Thinking models can take longer
    LLM_FREQUENCY_PENALTY: float = 0.6   # Penalise repeated tokens (prevents repetition loops)
    LLM_PRESENCE_PENALTY: float = 0.3    # Encourage topic diversity
    LLM_JSON_RESPONSE_FORMAT: bool = True # Enforce JSON outputs for structured tasks
    TOOL_CALL_TIMEOUT_SECONDS: float = 20.0
    TOOL_CALL_LOG_MAX_ENTRIES: int = 80

    # ---------- Server ----------
    HOST: str = "0.0.0.0"
    PORT: int = 8001


settings = Settings()
