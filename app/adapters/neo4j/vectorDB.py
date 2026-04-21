"""Vector / embedding operations against Neo4j's vector index.

`Chunk` nodes carry both the raw text of an uploaded document slice and
its embedding vector. Neo4j's vector index makes "find chunks most
similar to this query" fast — that's what powers `vector_search` and
the chunk half of `hybrid_search` in `app.tools`.

This adapter is deliberately small and split from `graphDB.py` so the
embedding concerns stay in one place:
- `create_vector_index` at startup (idempotent),
- `create_embeddings` to call into Ollama and validate the vector,
- `upsert_chunk` / `batch_upsert_chunks` to write chunks + vectors,
- `vector_search` / `get_chunk*` helpers for retrieval.

All vectors are validated against `self.dimensions` before any write so
a mismatched embedding model fails loudly instead of corrupting the
index.
"""

import json
import logging
import re
from typing import Any

from app.adapters.neo4j._sanitize import sanitize_neo4j_value
from app.adapters.embeddings import ollama as ollama_embeddings

# Index name is templated into Cypher directly (unavoidable), so it must
# be a safe identifier. Validated once at construction time.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
log = logging.getLogger("pathfinder.neo4j.vector")


class VectorDB:
    """Vector-index + chunk CRUD bound to one Neo4j driver.

    Pair one `VectorDB` with one `GraphDB` against the same driver; the
    two classes share nodes (chunks are written here, grounded into the
    graph there). `index_name` and `dimensions` must match what the
    index was created with — changing either requires rebuilding the
    index.
    """

    def __init__(self, driver, *, index_name: str, dimensions: int):
        self.driver = driver
        self.index_name = self.validate_identifier(index_name)
        if not isinstance(dimensions, int) or dimensions <= 0:
            raise ValueError("dimensions must be a positive int")
        self.dimensions = dimensions

    async def create_vector_index(self) -> None:
        """Ensure the vector index on `Chunk.embedding` exists.

        Called from `app.main.lifespan` at startup. Cosine similarity
        is hard-coded — the embedding model must be trained for cosine.
        """
        safe_index_name = self.validate_identifier(self.index_name)
        async with self.driver.session() as session:
            await session.run(
                f"""
                CREATE VECTOR INDEX `{safe_index_name}` IF NOT EXISTS
                FOR (c:Chunk) ON (c.embedding)
                OPTIONS {{
                    indexConfig: {{
                        `vector.dimensions`: {self.dimensions},
                        `vector.similarity_function`: 'cosine'
                    }}
                }}
                """
            )
        log.info("Vector index ensured: %s", safe_index_name)

    def validate_embedding(self, embedding: list[float]) -> list[float]:
        """Guard that an embedding is well-formed and matches `self.dimensions`.

        Neo4j will accept any list of floats into a vector field, but a
        wrong dimension silently breaks similarity search — we'd rather
        fail loudly at write time.
        """
        if not isinstance(embedding, list) or not embedding:
            raise ValueError("embedding must be a non-empty list[float]")
        if len(embedding) != self.dimensions:
            raise ValueError(
                f"embedding dimension mismatch: expected {self.dimensions}, got {len(embedding)}"
            )
        return [float(value) for value in embedding]

    async def create_embeddings(self, text: str) -> list[float]:
        """Embed one string via Ollama and validate the resulting vector."""
        embedding = await ollama_embeddings.aembed_query(text)
        return self.validate_embedding(embedding)

    async def upsert_chunk_metadata(
        self,
        *,
        chunk_id: str,
        document_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Write a chunk's text + metadata to Neo4j without touching its vector.

        Useful for the two-step path where `upsert_chunk` first lands
        the textual part so a failure mid-embedding still leaves the
        chunk in a valid-but-unindexed state. Blank text is skipped
        (not an error) so batch callers don't have to pre-filter.
        """
        if not chunk_id or not document_id:
            raise ValueError("chunk_id and document_id are required")
        text = (text or "").strip()
        if not text:
            return {
                "status": "skipped",
                "reason": "empty_text",
                "chunk_id": chunk_id,
                "document_id": document_id,
            }
        metadata = metadata or {}
        metadata_json = json.dumps(metadata, ensure_ascii=True, default=str)

        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (d:Document {id: $document_id})
                MERGE (c:Chunk {id: $chunk_id})
                ON CREATE SET c.created_at = datetime()
                SET c.updated_at = datetime(),
                    c.text = $text,
                    c.document_id = $document_id,
                    c.metadata_json = $metadata_json
                MERGE (c)-[:FROM_DOCUMENT]->(d)
                RETURN c.id AS chunk_id, d.id AS document_id
                """,
                chunk_id=chunk_id,
                document_id=document_id,
                text=text,
                metadata_json=metadata_json,
            )
            record = await result.single()
            if not record:
                raise ValueError(
                    f"Document not found for chunk upsert. document_id={document_id}"
                )

        return sanitize_neo4j_value({
            "status": "success",
            "chunk_id": record["chunk_id"],
            "document_id": record["document_id"],
        })

    async def upsert_chunk(
        self,
        *,
        chunk_id: str,
        document_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Full single-chunk upsert: text, metadata, and embedding in one call.

        This is the straightforward path used by the one-off `upsert_chunk`
        tool. For ingesting a document's worth of chunks, prefer
        `batch_upsert_chunks` — it embeds all chunks in a single Ollama
        call which is dramatically faster.
        """
        base = await self.upsert_chunk_metadata(
            chunk_id=chunk_id,
            document_id=document_id,
            text=text,
            metadata=metadata,
        )
        if base.get("status") != "success":
            return base

        text = (text or "").strip()
        embedding = await self.create_embeddings(text)

        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (d:Document {id: $document_id})
                MERGE (c:Chunk {id: $chunk_id})
                SET c.embedding = $embedding,
                    c.updated_at = datetime()
                MERGE (c)-[:FROM_DOCUMENT]->(d)
                RETURN c.id AS chunk_id, d.id AS document_id
                """,
                chunk_id=chunk_id,
                document_id=document_id,
                embedding=embedding,
            )
            record = await result.single()
            if not record:
                raise ValueError(
                    f"Document not found for chunk upsert. document_id={document_id}"
                )

        return sanitize_neo4j_value({
            "status": "success",
            "chunk_id": record["chunk_id"],
            "document_id": record["document_id"],
        })

    async def batch_upsert_chunks(
        self,
        *,
        document_id: str,
        chunks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Embed and write a whole document's worth of chunks in one shot.

        This is the hot path for document ingestion. It:
        1. normalizes each chunk (folding top-level `page_number`,
           `chunk_index`, offsets, and `provenance` into `metadata` so
           the stored shape is consistent),
        2. sends every text to Ollama in a single `aembed_documents`
           call — much cheaper than embedding one-by-one,
        3. runs a single Cypher `UNWIND` that upserts every chunk and
           wires it to its parent document.

        Empty/invalid chunks are silently dropped so the ingester can
        hand in whatever it has without pre-filtering.
        """
        if not document_id:
            raise ValueError("document_id is required")
        if not chunks:
            return {"status": "success", "document_id": document_id, "stored_chunks": 0}

        prepared: list[dict[str, Any]] = []
        texts: list[str] = []
        for idx, chunk in enumerate(chunks):
            chunk_id = str(chunk.get("chunk_id") or chunk.get("id") or "").strip()
            text = str(chunk.get("text") or "").strip()
            if not chunk_id or not text:
                continue
            metadata = dict(chunk.get("metadata") or {})
            if "page_number" in chunk and "page_number" not in metadata:
                metadata["page_number"] = chunk.get("page_number")
            if "chunk_index" in chunk and "chunk_index" not in metadata:
                metadata["chunk_index"] = chunk.get("chunk_index")
            if "start_offset" in chunk and "start_offset" not in metadata:
                metadata["start_offset"] = chunk.get("start_offset")
            if "end_offset" in chunk and "end_offset" not in metadata:
                metadata["end_offset"] = chunk.get("end_offset")
            if "provenance" in chunk and "provenance" not in metadata:
                metadata["provenance"] = chunk.get("provenance")
            prepared.append(
                {
                    "chunk_id": chunk_id,
                    "text": text,
                    "metadata": metadata,
                }
            )
            texts.append(text)

        if not prepared:
            return {"status": "success", "document_id": document_id, "stored_chunks": 0}

        embeddings = [self.validate_embedding(embedding) for embedding in await ollama_embeddings.aembed_documents(texts)]
        rows = []
        for chunk, embedding in zip(prepared, embeddings):
            metadata = chunk["metadata"]
            rows.append(
                {
                    "chunk_id": chunk["chunk_id"],
                    "text": chunk["text"],
                    "document_id": document_id,
                    "metadata_json": json.dumps(metadata, ensure_ascii=True),
                    "embedding": embedding,
                }
            )

        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (d:Document {id: $document_id})
                UNWIND $rows AS row
                MERGE (c:Chunk {id: row.chunk_id})
                ON CREATE SET c.created_at = datetime()
                SET c.updated_at = datetime(),
                    c.text = row.text,
                    c.document_id = row.document_id,
                    c.metadata_json = row.metadata_json,
                    c.embedding = row.embedding
                MERGE (c)-[:FROM_DOCUMENT]->(d)
                RETURN count(c) AS stored
                """,
                document_id=document_id,
                rows=rows,
            )
            record = await result.single()

        return sanitize_neo4j_value({
            "status": "success",
            "document_id": document_id,
            "stored_chunks": int(record["stored"]) if record and record["stored"] is not None else 0,
        })

    async def similarity_search(
        self,
        *,
        query: str,
        student_id: str,
        k: int = 5,
    ) -> list[dict[str, Any]]:
        """Run a cosine similarity search over this student's chunks.

        Embeds `query`, uses Neo4j's vector index to find the top-`k`
        matching chunks, and restricts the result to documents owned by
        `student_id` — one student never sees another's data. Returns
        each hit with its text, metadata, source document, and score.
        """
        query = (query or "").strip()
        if not query:
            return []
        if not student_id:
            raise ValueError("student_id is required")

        k = max(1, min(int(k), 50))
        query_embedding = await self.create_embeddings(query)

        async with self.driver.session() as session:
            result = await session.run(
                """
                CALL db.index.vector.queryNodes($index_name, $k, $embedding)
                YIELD node AS chunk, score
                MATCH (chunk)-[:FROM_DOCUMENT]->(d:Document)<-[:UPLOADED]-(s:Student {id: $student_id})
                WHERE chunk.embedding IS NOT NULL
                RETURN chunk.id AS id,
                       chunk.text AS text,
                       chunk.metadata_json AS metadata_json,
                       d.id AS document_id,
                       d.filename AS filename,
                       score
                ORDER BY score DESC
                LIMIT $k
                """,
                index_name=self.index_name,
                k=k,
                embedding=query_embedding,
                student_id=student_id,
            )
            rows: list[dict[str, Any]] = []
            async for record in result:
                metadata = self._metadata_dict(record["metadata_json"])
                rows.append(
                    {
                        "id": record["id"],
                        "text": record["text"],
                        "metadata": metadata,
                        "document_id": record["document_id"],
                        "filename": record["filename"],
                        "score": record["score"],
                    }
                )
        return sanitize_neo4j_value(rows)

    async def delete_document_chunks(self, *, document_id: str) -> dict[str, Any]:
        """Remove every chunk for a document (and all edges attached to them).

        Called by `GraphDB.delete_document_cascade` when a user re-uploads
        or explicitly deletes a document — we never want orphan chunks
        hanging around in the vector index.
        """
        if not document_id:
            raise ValueError("document_id is required")
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (c:Chunk {document_id: $document_id})
                WITH collect(c) AS chunks
                FOREACH (n IN chunks | DETACH DELETE n)
                RETURN size(chunks) AS deleted
                """,
                document_id=document_id,
            )
            record = await result.single()
        deleted = int(record["deleted"]) if record and record["deleted"] is not None else 0
        return sanitize_neo4j_value({"status": "success", "deleted_chunks": deleted, "document_id": document_id})

    async def health_check(self) -> dict[str, Any]:
        """Quick `RETURN 1` + index metadata probe used by `/health`."""
        async with self.driver.session() as session:
            ping = await session.run("RETURN 1 AS ok")
            record = await ping.single()
        ok = bool(record and record.get("ok") == 1)
        return sanitize_neo4j_value({
            "ok": ok,
            "index_name": self.index_name,
            "dimensions": self.dimensions,
        })

    @staticmethod
    def validate_identifier(identifier: str) -> str:
        """Reject anything that isn't a safe Cypher identifier.

        The vector index name ends up templated directly into Cypher
        (the driver can't parameterize index names), so this is the one
        spot user-controlled strings touch raw Cypher. Tight regex.
        """
        if not identifier or not _IDENTIFIER.fullmatch(identifier):
            raise ValueError(f"Invalid identifier: {identifier}")
        return identifier

    @staticmethod
    def _metadata_dict(raw_metadata: Any) -> dict[str, Any]:
        """Always return a dict for a chunk's metadata, even if stored as JSON string.

        We persist metadata as `metadata_json` (a JSON string) to keep
        the schema simple, but callers expect a real dict. Malformed
        JSON degrades to an empty dict rather than blowing up a read.
        """
        if isinstance(raw_metadata, dict):
            return raw_metadata
        if not raw_metadata:
            return {}
        try:
            parsed = json.loads(str(raw_metadata))
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _chunk_payload(self, chunk: dict[str, Any]) -> dict[str, Any]:
        """Normalize a raw Neo4j `Chunk` record for return to callers.

        Unpacks `metadata_json` into a real `metadata` dict and drops
        the raw JSON string so callers never have to parse it themselves.
        """
        payload = dict(chunk or {})
        payload["metadata"] = self._metadata_dict(payload.get("metadata_json"))
        payload.pop("metadata_json", None)
        return payload

    async def get_chunk(self, *, chunk_id: str) -> dict[str, Any]:
        """Fetch a single chunk by id — used by the `get_chunk` LLM tool."""
        async with self.driver.session() as session:
            result = await session.run("""
                MATCH (c:Chunk {id: $chunk_id})
                RETURN c {.*} AS chunk
            """, chunk_id=chunk_id)
            record = await result.single()
            if not record:
                raise ValueError("chunk not found")
            return sanitize_neo4j_value(self._chunk_payload(record["chunk"]))


    async def get_chunks_for_document(self, *, document_id: str) -> list[dict[str, Any]]:
        """Every chunk that came from one document.

        The ingester uses this during re-ingest to diff what's stored
        against what's about to be written; the replay viewer uses it
        to show the source text backing a citation.
        """
        async with self.driver.session() as session:
            result = await session.run("""
                MATCH (c:Chunk {document_id: $document_id})
                RETURN c {.*} AS chunk
            """, document_id=document_id)
            rows = [self._chunk_payload(record["chunk"]) async for record in result]
            return sanitize_neo4j_value(rows)
    
    async def get_chunks_for_student(self, *, student_id: str) -> list[dict[str, Any]]:
        """Every chunk for every document this student has uploaded.

        Debug / export use — routine retrieval should go through
        `similarity_search` instead so we benefit from the vector index.
        """
        async with self.driver.session() as session:
            result = await session.run("""
                MATCH (c:Chunk)-[:FROM_DOCUMENT]->(d:Document)<-[:UPLOADED]-(s:Student {id: $student_id})
                RETURN c {.*} AS chunk
            """, student_id=student_id)
            rows = [self._chunk_payload(record["chunk"]) async for record in result]
            return sanitize_neo4j_value(rows)

    async def delete_chunk(self, *, chunk_id: str) -> dict[str, Any]:
        """Detach-delete a single chunk. Used by the chunk-level tool."""
        async with self.driver.session() as session:
            result = await session.run("""
                MATCH (c:Chunk {id: $chunk_id})
                WITH c, c.id AS chunk_id
                DETACH DELETE c
                RETURN chunk_id
            """, chunk_id=chunk_id)
            record = await result.single()
            if not record:
                raise ValueError("chunk not found")
            return sanitize_neo4j_value({"status": "success", "chunk_id": record["chunk_id"]})
    
    async def get_chunk_neighbors(self, *, chunk_id: str) -> dict[str, Any]:
        """Chunk + its parent `Document` in one hop.

        Deliberately does not expand to linked entities — that's a
        graph-side concern and lives in `GraphDB.get_chunk_entities`.
        Keeping the split means the LLM tool layer can decide how much
        context it actually wants.
        """
        async with self.driver.session() as session:
            result = await session.run("""
                MATCH (c:Chunk {id: $chunk_id})-[:FROM_DOCUMENT]->(d:Document)
                RETURN c {.*} AS chunk, d {.*} AS document
            """, chunk_id=chunk_id)
            record = await result.single()
            if not record:
                raise ValueError("chunk not found")
            return sanitize_neo4j_value({
                "chunk": self._chunk_payload(record["chunk"]),
                "document": dict(record["document"]),
            })
    
    async def get_document_search_context(self, *, document_id: str) -> list[dict[str, Any]]:
        """A compact (id / text / metadata) chunk list for ingestion review.

        Similar to `get_chunks_for_document`, but drops the Neo4j
        internal fields so the shape is already LLM-ready.
        """
        async with self.driver.session() as session:
            result = await session.run("""
                MATCH (c:Chunk)-[:FROM_DOCUMENT]->(d:Document {id: $document_id})
                RETURN c {.*} AS chunk
            """, document_id=document_id)
            rows: list[dict[str, Any]] = []
            async for record in result:
                chunk = dict(record["chunk"])
                metadata = self._metadata_dict(chunk.get("metadata_json"))
                rows.append(
                    {
                        "id": chunk.get("id"),
                        "text": chunk.get("text"),
                        "document_id": chunk.get("document_id"),
                        "metadata": metadata,
                    }
                )
        return sanitize_neo4j_value(rows)
