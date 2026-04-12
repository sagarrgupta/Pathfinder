"""Pydantic models for API requests and responses."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class RequestModel(BaseModel):
    """Base model for API request payloads."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResponseModel(BaseModel):
    """Base model for API response payloads."""

    model_config = ConfigDict(str_strip_whitespace=True)


# ── Request Models ──────────────────────────────────────────────


class ChatRequest(RequestModel):
    """Chat request body (used for JSON endpoint; SSE uses form-data)."""
    query: str = Field(..., min_length=1, max_length=4000)
    session_id: Optional[str] = Field(default=None, max_length=120)
    student_id: Optional[str] = Field(default=None, max_length=120)
    topic_guard_enabled: Optional[bool] = None
    advisor_mode: Optional[str] = Field(default=None, max_length=40)


class ProfileTextInput(RequestModel):
    """Free-text input to add to the student profile."""
    text: str = Field(..., min_length=1, max_length=5000)


class ProfileUpdate(RequestModel):
    """Update a specific profile field."""
    student_id: Optional[str] = Field(default=None, max_length=120)
    field: str = Field(..., min_length=1, max_length=80)
    value: Any


class EntityUpdate(RequestModel):
    """Update properties on a profile entity (Company, Skill, etc.)."""
    student_id: Optional[str] = Field(default=None, max_length=120)
    label: str = Field(..., min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=200)  # current name to identify the entity
    properties: dict[str, Any] = Field(default_factory=dict)  # new property values


class ProfileCreate(RequestModel):
    """Create a new local student profile."""
    name: str = Field(..., min_length=1, max_length=120)
    email: Optional[str] = Field(default=None, max_length=200)
    university: Optional[str] = Field(default=None, max_length=200)
    program: Optional[str] = Field(default=None, max_length=200)


class ConflictChoiceRequest(RequestModel):
    """Resolve a profile conflict choice."""
    student_id: Optional[str] = Field(default=None, max_length=120)
    conflict_id: str = Field(..., min_length=1, max_length=120)
    fact_type: str = Field(..., min_length=1, max_length=80)
    action: str = Field(default="choose_value", min_length=1, max_length=40)  # choose_value | unresolved
    selected_value: Optional[str] = Field(default=None, max_length=300)


class SettingsUpdate(RequestModel):
    """Update application settings."""
    topic_guard_enabled: Optional[bool] = None
    advisor_mode: Optional[str] = Field(default=None, max_length=40)


class SavedRecommendationCreate(RequestModel):
    """Create a saved recommendation/plan item."""
    student_id: Optional[str] = Field(default=None, max_length=120)
    title: str = Field(..., min_length=1, max_length=200)
    summary: str = Field(..., min_length=1, max_length=4000)
    recommendation_type: str = Field(default="plan", min_length=1, max_length=80)
    actions: list[str] = Field(default_factory=list)
    source_session_id: Optional[str] = Field(default=None, max_length=120)
    source_query: Optional[str] = Field(default=None, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SavedRecommendationOutcomeUpdate(RequestModel):
    """Update outcome/feedback for a saved recommendation."""
    student_id: Optional[str] = Field(default=None, max_length=120)
    outcome_status: str = Field(..., min_length=1, max_length=80)
    outcome_notes: Optional[str] = Field(default=None, max_length=4000)
    next_review_at: Optional[str] = Field(default=None, max_length=80)
    follow_up_prompt: Optional[str] = Field(default=None, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Response Models ─────────────────────────────────────────────


class Citation(ResponseModel):
    """Source citation for an answer."""
    source: str = Field(..., min_length=1, max_length=1000)  # document name or URL
    content: str = Field(default="", max_length=4000)  # relevant excerpt
    score: Optional[float] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(ResponseModel):
    """Non-streaming chat response (fallback)."""
    answer: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1, max_length=120)
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    method: str = Field(default="direct", min_length=1, max_length=80)  # rag, graph, web, conversation_history, direct
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentUploadResponse(ResponseModel):
    """Response after uploading a document."""
    document_id: str = Field(..., min_length=1, max_length=120)
    filename: str = Field(..., min_length=1, max_length=260)
    scope: str = Field(..., min_length=1, max_length=40)  # "global" or "session"
    document_role: str = Field(default="general_document", min_length=1, max_length=80)
    role_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    entities_extracted: int = Field(default=0, ge=0)
    chunks_stored: int = Field(default=0, ge=0)


class ProfileResponse(ResponseModel):
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
    profile_facts: list[dict[str, Any]] = Field(default_factory=list)
    candidate_fact_ledger: list[dict[str, Any]] = Field(default_factory=list)
    completeness_breakdown: dict[str, Any] = Field(default_factory=dict)
    fact_summary: dict[str, Any] = Field(default_factory=dict)
    temporal_profile: dict[str, Any] = Field(default_factory=dict)
    # Dynamic: all entity types from the KG keyed by Neo4j label
    all_entities: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    completeness: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    memory_overview: dict[str, Any] = Field(default_factory=dict)


class ProfileInfo(ResponseModel):
    """Local student profile summary."""
    student_id: str = Field(..., min_length=1, max_length=120)
    name: str = Field(default="Student", min_length=1, max_length=120)
    email: Optional[str] = Field(default=None, max_length=200)
    university: Optional[str] = Field(default=None, max_length=200)
    program: Optional[str] = Field(default=None, max_length=200)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completeness: float = Field(default=0.0, ge=0.0, le=1.0)


class GraphDataResponse(ResponseModel):
    """Knowledge graph data for visualization."""
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    relationships: list[dict[str, Any]] = Field(default_factory=list)


class SessionInfo(ResponseModel):
    """Chat session metadata."""
    session_id: str = Field(..., min_length=1, max_length=120)
    student_id: Optional[str] = Field(default=None, max_length=120)
    title: str = Field(default="New Chat", min_length=1, max_length=200)
    last_message: str = Field(default="", max_length=1000)
    created_at: Optional[datetime] = None
    message_count: int = Field(default=0, ge=0)


class SavedRecommendationInfo(ResponseModel):
    """Saved recommendation summary."""
    id: str = Field(..., min_length=1, max_length=120)
    student_id: str = Field(..., min_length=1, max_length=120)
    title: str = Field(..., min_length=1, max_length=200)
    summary: str = Field(..., min_length=1, max_length=4000)
    recommendation_type: str = Field(default="plan", min_length=1, max_length=80)
    actions: list[str] = Field(default_factory=list)
    source_session_id: Optional[str] = Field(default=None, max_length=120)
    source_query: Optional[str] = Field(default=None, max_length=1000)
    created_at: Optional[datetime] = None
    status: str = Field(default="active", min_length=1, max_length=80)
    next_review_at: Optional[str] = Field(default=None, max_length=80)
    follow_up_prompt: Optional[str] = Field(default=None, max_length=1000)
    outcome_status: str = Field(default="active", min_length=1, max_length=80)
    outcome_notes: Optional[str] = Field(default=None, max_length=4000)
    outcome_updated_at: Optional[str] = Field(default=None, max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(ResponseModel):
    """Health check response."""
    status: str = "ok"
    neo4j: str = "unknown"
    lm_studio: str = "unknown"
    ollama: str = "unknown"
    version: str = "2.0.0"


class SettingsResponse(ResponseModel):
    """Current settings."""
    topic_guard_enabled: bool = True
    advisor_mode: str = "adaptive"
    models: dict[str, str] = Field(default_factory=dict)


class ReplayArtifactInfo(ResponseModel):
    """Compact replay artifact summary."""
    id: str = Field(..., min_length=1, max_length=120)
    created_at: Optional[str] = Field(default=None, max_length=80)
    student_id: str = Field(..., min_length=1, max_length=120)
    session_id: str = Field(..., min_length=1, max_length=120)
    query: str = Field(..., min_length=1, max_length=4000)
    workflow: str = Field(default="", max_length=120)
    method: str = Field(default="", max_length=120)
    quality_path: str = Field(default="", max_length=200)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ReplayEvaluationInfo(ResponseModel):
    """Lightweight replay evaluation result."""
    replay_id: str = Field(..., min_length=1, max_length=120)
    query: str = Field(default="", max_length=4000)
    workflow: str = Field(default="", max_length=120)
    method: str = Field(default="", max_length=120)
    score: float = Field(default=0.0)
    status: str = Field(default="warn", min_length=1, max_length=40)
    checks: dict[str, bool] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)
    metrics: dict[str, int] = Field(default_factory=dict)
    score_components: dict[str, float] = Field(default_factory=dict)


class ReplayEvaluationBatch(ResponseModel):
    """Summary and results for replay regression checks."""
    summary: dict[str, Any] = Field(default_factory=dict)
    evaluations: list[ReplayEvaluationInfo] = Field(default_factory=list)


class EvalBenchmarkInfo(ResponseModel):
    """Benchmark-set metadata for continuous evaluation."""
    id: str = Field(..., min_length=1, max_length=120)
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    workflow: str = Field(default="", max_length=120)
    scenario_count: int = Field(default=0, ge=0)
    examples: list[str] = Field(default_factory=list)


class EvalAnalyticsResponse(ResponseModel):
    """Grouped replay analytics and benchmark coverage."""
    summary: dict[str, Any] = Field(default_factory=dict)
    benchmarks: list[EvalBenchmarkInfo] = Field(default_factory=list)
    comparisons: dict[str, Any] = Field(default_factory=dict)
    trend: dict[str, Any] = Field(default_factory=dict)
