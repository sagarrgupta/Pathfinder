"""Pydantic models that define every API request and response shape.

The two base classes at the top (`RequestModel` and `ResponseModel`) set
common policy:
- Request bodies reject unknown fields (`extra="forbid"`) so typos in
  client payloads don't silently succeed.
- All string fields are whitespace-stripped so " jane " and "jane" are
  treated as the same value.

Each concrete model below is the wire contract for one endpoint group in
`app.api.routes` — students, documents, graph visualization, settings,
health checks, and replay artifacts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class RequestModel(BaseModel):
    """Strict base for anything coming in from a client.

    `extra="forbid"` means unknown fields raise a validation error
    instead of being silently accepted — this catches client typos early.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResponseModel(BaseModel):
    """Lenient base for anything we send back.

    We intentionally don't forbid extras here so handlers can attach
    optional debug fields (timings, tool-call counts, ...) without
    updating the schema for every small change.
    """

    model_config = ConfigDict(str_strip_whitespace=True)


class StudentUpdate(RequestModel):
    """Body for `PATCH` requests that edit one field on a student.

    `field` is the property key (e.g. "major", "gpa"); `value` is the
    new value. Keeping it this granular lets the UI save-on-blur each
    field without needing the full student payload.
    """
    student_id: Optional[str] = Field(default=None, max_length=120)
    field: str = Field(..., min_length=1, max_length=80)
    value: Any


class StudentCreate(RequestModel):
    """Body for creating a brand-new local student profile.

    `extra="allow"` because the UI may prefill extra attributes (email,
    major, ...) during signup — they get passed straight through to
    `update_student` on the graph side.
    """
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=120)


class SettingsUpdate(RequestModel):
    """Body for updating app-level toggles from the UI.

    Only the fields the user actually changed need to be included; the
    rest stay at their current value.
    """
    topic_guard_enabled: Optional[bool] = None
    reasoning: Optional[str] = Field(default=None, max_length=40)
    llm_provider: Optional[Literal["lmstudio", "nvidia"]] = None


class DocumentUploadResponse(ResponseModel):
    """What the upload endpoint returns after a file has been ingested.

    Reports how many entities ended up in the graph and how many chunks
    made it into the vector store — the UI uses these numbers to show a
    quick "ingestion summary" to the user.
    """
    document_id: str = Field(..., min_length=1, max_length=120)
    filename: str = Field(..., min_length=1, max_length=260)
    entities_extracted: int = Field(default=0, ge=0)
    chunks_stored: int = Field(default=0, ge=0)


class StudentResponse(ResponseModel):
    """Full student profile payload for the profile page.

    Broken into the root-level scalar fields, the sections (groups of
    entities), the entities themselves keyed by section, any long-form
    context the AI has saved, and the live schema manifest so the UI
    can render section/field labels correctly.
    """
    root_properties: dict[str, Any] = Field(default_factory=dict)
    sections: list[dict[str, Any]] = Field(default_factory=list)
    section_items: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    long_context: str = ""
    student_schema: dict[str, Any] = Field(default_factory=dict)


class StudentInfo(ResponseModel):
    """Small summary of a student used in lists/pickers.

    `extra="allow"` so we can surface any extra scalar fields Neo4j
    returns (email, headline, ...) without having to extend the model
    every time a new property is added.
    """
    model_config = ConfigDict(str_strip_whitespace=True, extra="allow")

    student_id: str = Field(..., min_length=1, max_length=120)
    name: str = Field(default="Student", min_length=1, max_length=120)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class GraphDataResponse(ResponseModel):
    """Shape consumed by the graph visualization view — nodes + edges."""
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    relationships: list[dict[str, Any]] = Field(default_factory=list)


class HealthResponse(ResponseModel):
    """`/health` payload — used by deployment probes and the UI banner."""
    status: str = "ok"
    services: dict[str, str] = Field(default_factory=dict)
    version: str = "2.0.0"


class SettingsResponse(ResponseModel):
    """Snapshot of current app settings + which models are configured."""
    topic_guard_enabled: bool = True
    reasoning: str = "medium"
    llm_provider: Literal["lmstudio", "nvidia"] = "lmstudio"
    nvidia_configured: bool = False
    models: dict[str, str] = Field(default_factory=dict)


class ReplayArtifactInfo(ResponseModel):
    """Lightweight row used when listing saved replay artifacts.

    Full replay contents live on disk (see `app.services.replay_store`);
    this shape only carries what the UI needs to render the list view.
    """
    id: str = Field(..., min_length=1, max_length=120)
    created_at: Optional[str] = Field(default=None, max_length=80)
    student_id: str = Field(..., min_length=1, max_length=120)
    session_id: str = Field(..., min_length=1, max_length=120)
    query: str = Field(..., min_length=1, max_length=4000)
    selected_specialist: str = Field(default="", max_length=120)
    method: str = Field(default="", max_length=120)
