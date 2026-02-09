"""ID generation utilities."""

import uuid


def generate_session_id() -> str:
    """Generate a unique session ID."""
    return f"session_{uuid.uuid4().hex[:12]}"


def generate_document_id() -> str:
    """Generate a unique document ID."""
    return f"doc_{uuid.uuid4().hex[:12]}"


def generate_chunk_id(document_id: str, index: int) -> str:
    """Generate a unique chunk ID for a document."""
    return f"{document_id}_chunk_{index}"