"""Pathfinder application settings.

All configuration is loaded from environment variables or .env file.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # ---------- LM Studio (Text + Vision LLM) ----------
    LLM_BASE_URL: str = "http://localhost:1234/v1"
    LLM_MODEL: str = "openai/gpt-oss-20b"
    LLM_AVAILABLE_MODELS: list[str] = ["openai/gpt-oss-20b", "Qwen3-14B-MLX-8bit"]
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
    NEO4J_PASSWORD: str = ""

    # ---------- SQLite (LangGraph Memory) ----------
    SQLITE_DB_PATH: str = "data/pathfinder.db"

    # ---------- Retrieval ----------
    TOP_K: int = 5
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 100
    DEFAULT_RETRIEVAL_MODE: str = "hybrid"
    DOCUMENT_STORAGE_DIR: str = "data/documents"
    PAGEINDEX_WORKSPACE_DIR: str = "data/pageindex"
    PAGEINDEX_MODEL: str = ""
    PAGEINDEX_RETRIEVE_MODEL: str = ""
    
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
    # gpt-oss-20b is a thinking/reasoning model — it uses tokens for internal
    # chain-of-thought before producing visible output.  With max_tokens=2048
    # the model exhausts the budget on thinking and returns empty content.
    # 16384 gives ample room for both reasoning (~12k) and output (~4k).
    LLM_MAX_TOKENS: int = 16384
    LLM_REQUEST_TIMEOUT: float = 300.0   # Thinking models can take longer
    LLM_FREQUENCY_PENALTY: float = 0.6   # Penalise repeated tokens (prevents repetition loops)
    LLM_PRESENCE_PENALTY: float = 0.3    # Encourage topic diversity

    # ---------- Server ----------
    HOST: str = "0.0.0.0"
    PORT: int = 8001


settings = Settings()
