"""Pydantic models for API requests and responses."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Request Models ──────────────────────────────────────────────


class ChatRequest(BaseModel):
    """Chat request body (used for JSON endpoint; SSE uses form-data)."""
    query: str
    session_id: Optional[str] = None
    topic_guard_enabled: Optional[bool] = None


class ProfileTextInput(BaseModel):
    """Free-text input to add to the student profile."""
    text: str = Field(..., min_length=1, max_length=5000)


class ProfileUpdate(BaseModel):
    """Update a specific profile field."""
    field: str
    value: Any


class EntityUpdate(BaseModel):
    """Update properties on a profile entity (Company, Skill, etc.)."""
    label: str
    name: str  # current name to identify the entity
    properties: dict[str, Any]  # new property values


class SettingsUpdate(BaseModel):
    """Update application settings."""
    topic_guard_enabled: Optional[bool] = None


# ── Response Models ─────────────────────────────────────────────


class Citation(BaseModel):
    """Source citation for an answer."""
    source: str  # document name or URL
    content: str = ""  # relevant excerpt
    score: Optional[float] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    """Non-streaming chat response (fallback)."""
    answer: str
    session_id: str
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = 0.0
    method: str = "direct"  # rag, graph, web, conversation_history, direct
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentUploadResponse(BaseModel):
    """Response after uploading a document."""
    document_id: str
    filename: str
    scope: str  # "global" or "session"
    entities_extracted: int = 0
    chunks_stored: int = 0


class ProfileResponse(BaseModel):
    """Student profile data.

    Maintains backward-compatible named fields AND a dynamic ``all_entities``
    dict so the frontend can render any entity type that appears in the KG.
    """
    personal: dict[str, Any] = Field(default_factory=dict)
    academic: dict[str, Any] = Field(default_factory=dict)
    # Named entity collections (backward compat)
    skills: list[dict[str, Any]] = Field(default_factory=list)
    courses: list[dict[str, Any]] = Field(default_factory=list)
    goals: list[dict[str, Any]] = Field(default_factory=list)
    documents: list[dict[str, Any]] = Field(default_factory=list)
    interests: list[dict[str, Any]] = Field(default_factory=list)
    experience: list[dict[str, Any]] = Field(default_factory=list)
    projects: list[dict[str, Any]] = Field(default_factory=list)
    # Dynamic: all entity types from the KG keyed by Neo4j label
    all_entities: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


class GraphDataResponse(BaseModel):
    """Knowledge graph data for visualization."""
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    relationships: list[dict[str, Any]] = Field(default_factory=list)


class SessionInfo(BaseModel):
    """Chat session metadata."""
    session_id: str
    title: str = "New Chat"
    last_message: str = ""
    created_at: Optional[datetime] = None
    message_count: int = 0


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "ok"
    neo4j: str = "unknown"
    lm_studio: str = "unknown"
    ollama: str = "unknown"
    version: str = "2.0.0"


class SettingsResponse(BaseModel):
    """Current settings."""
    topic_guard_enabled: bool = True
    models: dict[str, str] = Field(default_factory=dict)
