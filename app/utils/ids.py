"""Generators for every kind of id Pathfinder stamps on its data.

Every id follows the same shape: a short type prefix followed by the
first 12 hex characters of a UUID4. The prefix makes ids self-describing
in logs ("doc_…", "chunk_…") so we never have to guess what a string
refers to, and the 12-hex tail is more than enough entropy for a
local, single-user deployment.

Chunk ids are the one exception — they're built from `document_id + "_chunk_" + index`
so chunks belonging to the same document sort together and are
trivially re-derivable during re-ingestion.
"""

import uuid


def generate_student_id() -> str:
    """New id for a profile/student root node. One per user."""
    return f"student_{uuid.uuid4().hex[:12]}"


def generate_session_id() -> str:
    """New id for a chat session (conversation thread).

    Used as the LangGraph checkpoint thread id so resuming a session
    pulls back its full message history from SQLite.
    """
    return f"session_{uuid.uuid4().hex[:12]}"


def generate_document_id() -> str:
    """New id for an uploaded document. Stamped at upload time.

    The chunks extracted from the file all embed this id in their own
    ids via `generate_chunk_id`, which is how we cascade-delete a
    document's chunks cleanly.
    """
    return f"doc_{uuid.uuid4().hex[:12]}"


def generate_chunk_id(document_id: str, index: int) -> str:
    """Deterministic chunk id — `{document_id}_chunk_{index}`.

    Unlike the other ids, this is *not* random: re-ingesting the same
    document with the same chunking produces the same chunk ids, which
    lets `batch_upsert_chunks` MERGE over old content instead of
    leaving orphans.
    """
    return f"{document_id}_chunk_{index}"


def generate_field_id() -> str:
    """New id for a nested `Field` node under an entity."""
    return f"field_{uuid.uuid4().hex[:12]}"


def generate_replay_id() -> str:
    """New id for a replay artifact (one JSON file per chat turn).

    Used by `app.services.replay_store` to name files on disk and to
    key them in the `/replays` API listings.
    """
    return f"replay_{uuid.uuid4().hex[:12]}"
