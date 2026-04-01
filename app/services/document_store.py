"""Local persistence for uploaded source documents."""

from __future__ import annotations

import re
from pathlib import Path

from app.config.settings import settings


_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def persist_uploaded_file(
    document_id: str,
    filename: str,
    content: bytes,
    student_id: str = "default",
) -> str:
    """Persist an uploaded source file to local storage and return its path."""
    base_dir = Path(settings.DOCUMENT_STORAGE_DIR).expanduser() / student_id
    base_dir.mkdir(parents=True, exist_ok=True)

    safe_name = _SAFE_FILENAME_RE.sub("_", filename).strip("._") or "document"
    target = base_dir / f"{document_id}_{safe_name}"
    target.write_bytes(content)
    return str(target.resolve())
