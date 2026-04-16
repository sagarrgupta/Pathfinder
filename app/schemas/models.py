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
    reasoning: Optional[str] = Field(default=None, max_length=40)


class ProfileTextInput(RequestModel):
    """Free-text input to add to the student profile."""
    text: str = Field(..., min_length=1, max_length=5000)


class StudentUpdate(RequestModel):
    """Update a specific student field."""
    student_id: Optional[str] = Field(default=None, max_length=120)
    field: str = Field(..., min_length=1, max_length=80)
    value: Any


class EntityUpdate(RequestModel):
    """Update properties on a profile entity by any identity key(s)."""
    student_id: Optional[str] = Field(default=None, max_length=120)
    label: str = Field(..., min_length=1, max_length=80)
    name: Optional[str] = Field(default=None, max_length=200)
    match_props: dict[str, Any] = Field(default_factory=dict)
    properties: dict[str, Any] = Field(default_factory=dict)


class StudentCreate(RequestModel):
    """Create a new local student."""
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=120)


class SettingsUpdate(RequestModel):
    """Update application settings."""
    topic_guard_enabled: Optional[bool] = None
    reasoning: Optional[str] = Field(default=None, max_length=40)


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
    entities_extracted: int = Field(default=0, ge=0)
    chunks_stored: int = Field(default=0, ge=0)


class StudentResponse(ResponseModel):
    """Schema-driven student payload."""
    root_properties: dict[str, Any] = Field(default_factory=dict)
    sections: list[dict[str, Any]] = Field(default_factory=list)
    section_items: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    unsectioned_items: list[dict[str, Any]] = Field(default_factory=list)
    support_records: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    completeness_breakdown: dict[str, Any] = Field(default_factory=dict)
    fact_summary: dict[str, Any] = Field(default_factory=dict)
    temporal_profile: dict[str, Any] = Field(default_factory=dict)
    long_context_preview: dict[str, Any] = Field(default_factory=dict)
    student_schema: dict[str, Any] = Field(default_factory=dict)
    # Dynamic: all entity types from the KG keyed by Neo4j label
    all_entities: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    completeness: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class StudentInfo(ResponseModel):
    """Local student summary."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="allow")

    student_id: str = Field(..., min_length=1, max_length=120)
    name: str = Field(default="Student", min_length=1, max_length=120)
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
    services: dict[str, str] = Field(default_factory=dict)
    version: str = "2.0.0"


class SettingsResponse(ResponseModel):
    """Current settings."""
    topic_guard_enabled: bool = True
    reasoning: str = "medium"
    models: dict[str, str] = Field(default_factory=dict)


class ReplayArtifactInfo(ResponseModel):
    """Compact replay artifact summary."""
    id: str = Field(..., min_length=1, max_length=120)
    created_at: Optional[str] = Field(default=None, max_length=80)
    student_id: str = Field(..., min_length=1, max_length=120)
    session_id: str = Field(..., min_length=1, max_length=120)
    query: str = Field(..., min_length=1, max_length=4000)
    selected_specialist: str = Field(default="", max_length=120)
    method: str = Field(default="", max_length=120)
    quality_path: str = Field(default="", max_length=200)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ReplayEvaluationInfo(ResponseModel):
    """Lightweight replay evaluation result."""
    replay_id: str = Field(..., min_length=1, max_length=120)
    query: str = Field(default="", max_length=4000)
    selected_specialist: str = Field(default="", max_length=120)
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
    specialist: str = Field(default="", max_length=120)
    scenario_count: int = Field(default=0, ge=0)
    examples: list[str] = Field(default_factory=list)


class EvalAnalyticsResponse(ResponseModel):
    """Grouped replay analytics and benchmark coverage."""
    summary: dict[str, Any] = Field(default_factory=dict)
    benchmarks: list[EvalBenchmarkInfo] = Field(default_factory=list)
    comparisons: dict[str, Any] = Field(default_factory=dict)
    trend: dict[str, Any] = Field(default_factory=dict)
