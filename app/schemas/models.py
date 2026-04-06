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
    student_id: Optional[str] = None
    topic_guard_enabled: Optional[bool] = None
    advisor_mode: Optional[str] = None


class ProfileTextInput(BaseModel):
    """Free-text input to add to the student profile."""
    text: str = Field(..., min_length=1, max_length=5000)


class ProfileUpdate(BaseModel):
    """Update a specific profile field."""
    student_id: Optional[str] = None
    field: str
    value: Any


class EntityUpdate(BaseModel):
    """Update properties on a profile entity (Company, Skill, etc.)."""
    student_id: Optional[str] = None
    label: str
    name: str  # current name to identify the entity
    properties: dict[str, Any]  # new property values


class ProfileCreate(BaseModel):
    """Create a new local student profile."""
    name: str = Field(..., min_length=1, max_length=120)
    email: Optional[str] = None
    university: Optional[str] = None
    program: Optional[str] = None


class ConflictChoiceRequest(BaseModel):
    """Resolve a profile conflict choice."""
    student_id: Optional[str] = None
    conflict_id: str
    fact_type: str
    action: str = "choose_value"  # choose_value | unresolved
    selected_value: Optional[str] = None


class SettingsUpdate(BaseModel):
    """Update application settings."""
    topic_guard_enabled: Optional[bool] = None
    advisor_mode: Optional[str] = None


class SavedRecommendationCreate(BaseModel):
    """Create a saved recommendation/plan item."""
    student_id: Optional[str] = None
    title: str
    summary: str
    recommendation_type: str = "plan"
    actions: list[str] = Field(default_factory=list)
    source_session_id: Optional[str] = None
    source_query: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SavedRecommendationOutcomeUpdate(BaseModel):
    """Update outcome/feedback for a saved recommendation."""
    student_id: Optional[str] = None
    outcome_status: str
    outcome_notes: Optional[str] = None
    next_review_at: Optional[str] = None
    follow_up_prompt: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    document_role: str = "general_document"
    role_confidence: float = 0.0
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
    profile_facts: list[dict[str, Any]] = Field(default_factory=list)
    candidate_fact_ledger: list[dict[str, Any]] = Field(default_factory=list)
    completeness_breakdown: dict[str, Any] = Field(default_factory=dict)
    fact_summary: dict[str, Any] = Field(default_factory=dict)
    temporal_profile: dict[str, Any] = Field(default_factory=dict)
    # Dynamic: all entity types from the KG keyed by Neo4j label
    all_entities: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    completeness: float = 0.0
    confidence: float = 0.0
    memory_overview: dict[str, Any] = Field(default_factory=dict)


class ProfileInfo(BaseModel):
    """Local student profile summary."""
    student_id: str
    name: str = "Student"
    email: Optional[str] = None
    university: Optional[str] = None
    program: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completeness: float = 0.0


class GraphDataResponse(BaseModel):
    """Knowledge graph data for visualization."""
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    relationships: list[dict[str, Any]] = Field(default_factory=list)


class SessionInfo(BaseModel):
    """Chat session metadata."""
    session_id: str
    student_id: Optional[str] = None
    title: str = "New Chat"
    last_message: str = ""
    created_at: Optional[datetime] = None
    message_count: int = 0


class SavedRecommendationInfo(BaseModel):
    """Saved recommendation summary."""
    id: str
    student_id: str
    title: str
    summary: str
    recommendation_type: str = "plan"
    actions: list[str] = Field(default_factory=list)
    source_session_id: Optional[str] = None
    source_query: Optional[str] = None
    created_at: Optional[datetime] = None
    status: str = "active"
    next_review_at: Optional[str] = None
    follow_up_prompt: Optional[str] = None
    outcome_status: str = "active"
    outcome_notes: Optional[str] = None
    outcome_updated_at: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    advisor_mode: str = "adaptive"
    models: dict[str, str] = Field(default_factory=dict)


class ReplayArtifactInfo(BaseModel):
    """Compact replay artifact summary."""
    id: str
    created_at: Optional[str] = None
    student_id: str
    session_id: str
    query: str
    workflow: str = ""
    method: str = ""
    quality_path: str = ""
    confidence: float = 0.0


class ReplayEvaluationInfo(BaseModel):
    """Lightweight replay evaluation result."""
    replay_id: str
    query: str = ""
    workflow: str = ""
    method: str = ""
    score: float = 0.0
    status: str = "warn"
    checks: dict[str, bool] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)
    metrics: dict[str, int] = Field(default_factory=dict)
    score_components: dict[str, float] = Field(default_factory=dict)


class ReplayEvaluationBatch(BaseModel):
    """Summary and results for replay regression checks."""
    summary: dict[str, Any] = Field(default_factory=dict)
    evaluations: list[ReplayEvaluationInfo] = Field(default_factory=list)


class EvalBenchmarkInfo(BaseModel):
    """Benchmark-set metadata for continuous evaluation."""
    id: str
    title: str
    description: str = ""
    workflow: str = ""
    scenario_count: int = 0
    examples: list[str] = Field(default_factory=list)


class EvalAnalyticsResponse(BaseModel):
    """Grouped replay analytics and benchmark coverage."""
    summary: dict[str, Any] = Field(default_factory=dict)
    benchmarks: list[EvalBenchmarkInfo] = Field(default_factory=list)
    comparisons: dict[str, Any] = Field(default_factory=dict)
    trend: dict[str, Any] = Field(default_factory=dict)
