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


class StudentUpdate(RequestModel):
    """Update a specific student field."""
    student_id: Optional[str] = Field(default=None, max_length=120)
    field: str = Field(..., min_length=1, max_length=80)
    value: Any


class StudentCreate(RequestModel):
    """Create a new local student."""
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=120)


class SettingsUpdate(RequestModel):
    """Update application settings."""
    topic_guard_enabled: Optional[bool] = None
    reasoning: Optional[str] = Field(default=None, max_length=40)


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
    long_context: str = ""
    student_schema: dict[str, Any] = Field(default_factory=dict)


class StudentInfo(ResponseModel):
    """Local student summary."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="allow")

    student_id: str = Field(..., min_length=1, max_length=120)
    name: str = Field(default="Student", min_length=1, max_length=120)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class GraphDataResponse(ResponseModel):
    """Knowledge graph data for visualization."""
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    relationships: list[dict[str, Any]] = Field(default_factory=list)


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
