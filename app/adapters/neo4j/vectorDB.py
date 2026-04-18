import json
import logging
import re
from typing import Any

from app.adapters.neo4j._sanitize import sanitize_neo4j_value
from app.adapters.embeddings import ollama as ollama_embeddings

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
log = logging.getLogger("pathfinder.neo4j.vector")

class VectorDB:
    """Neo4j vector adapter for chunk embeddings and retrieval."""

    def __init__(self, driver, *, index_name: str, dimensions: int):
        self.driver = driver
        self.index_name = self.validate_identifier(index_name)
        if not isinstance(dimensions, int) or dimensions <= 0:
            raise ValueError("dimensions must be a positive int")
        self.dimensions = dimensions

    async def create_vector_index(self) -> None:
        """Create the Chunk.embedding vector index if missing."""
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
        """Validate one embedding vector and coerce to list[float]."""
        if not isinstance(embedding, list) or not embedding:
            raise ValueError("embedding must be a non-empty list[float]")
        if len(embedding) != self.dimensions:
            raise ValueError(
                f"embedding dimension mismatch: expected {self.dimensions}, got {len(embedding)}"
            )
        return [float(value) for value in embedding]

    async def create_embeddings(self, text: str) -> list[float]:
        """Create and validate one embedding vector for text."""
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
        """Upsert chunk text + metadata without generating an embedding."""
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
        metadata_json = json.dumps(metadata, ensure_ascii=True)

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
        """Upsert chunk metadata, then attach the generated embedding."""
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
        """Upsert many chunks for one document, including embeddings."""
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
        """Vector search over Chunk nodes scoped to one student profile."""
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
        """Delete chunks and related edges for one document."""
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
        """Basic Neo4j and vector-index connectivity check."""
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
        """Allow only safe Cypher identifier characters."""
        if not identifier or not _IDENTIFIER.fullmatch(identifier):
            raise ValueError(f"Invalid identifier: {identifier}")
        return identifier

    @staticmethod
    def _metadata_dict(raw_metadata: Any) -> dict[str, Any]:
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
        payload = dict(chunk or {})
        payload["metadata"] = self._metadata_dict(payload.get("metadata_json"))
        payload.pop("metadata_json", None)
        return payload

    # - get_chunk(...):
    #   Fetch one chunk with its text, metadata, and document linkage.
    async def get_chunk(self, *, chunk_id: str) -> dict[str, Any]:
        """Fetch one chunk with its text, metadata, and document linkage."""
        async with self.driver.session() as session:
            result = await session.run("""
                MATCH (c:Chunk {id: $chunk_id})
                RETURN c {.*} AS chunk
            """, chunk_id=chunk_id)
            record = await result.single()
            if not record:
                raise ValueError("chunk not found")
            return sanitize_neo4j_value(self._chunk_payload(record["chunk"]))


    # - get_chunks_for_document(...):
    #   Return all chunks for a document so ingestion/retrieval can inspect evidence.
    async def get_chunks_for_document(self, *, document_id: str) -> list[dict[str, Any]]:
        """Return all chunks for a document so ingestion/retrieval can inspect evidence."""
        async with self.driver.session() as session:
            result = await session.run("""
                MATCH (c:Chunk {document_id: $document_id})
                RETURN c {.*} AS chunk
            """, document_id=document_id)
            rows = [self._chunk_payload(record["chunk"]) async for record in result]
            return sanitize_neo4j_value(rows)
    
    # - get_chunks_for_student(...):
    #   Return chunks across all documents for student-wide traversal or debugging.
    async def get_chunks_for_student(self, *, student_id: str) -> list[dict[str, Any]]:
        """Return chunks across all documents for student-wide traversal or debugging."""
        async with self.driver.session() as session:
            result = await session.run("""
                MATCH (c:Chunk)-[:FROM_DOCUMENT]->(d:Document)<-[:UPLOADED]-(s:Student {id: $student_id})
                RETURN c {.*} AS chunk
            """, student_id=student_id)
            rows = [self._chunk_payload(record["chunk"]) async for record in result]
            return sanitize_neo4j_value(rows)

    # - delete_chunk(...):
    #   Remove or replace one chunk safely during re-ingestion.
    async def delete_chunk(self, *, chunk_id: str) -> dict[str, Any]:
        """Remove or replace one chunk safely during re-ingestion."""
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
    
    # - get_chunk_neighbors(...):
    #   Convenience read helper that returns document context for one chunk; graph-side
    #   entity expansion should still live in GraphDB.
    async def get_chunk_neighbors(self, *, chunk_id: str) -> dict[str, Any]:
        """Return one chunk plus its document context; graph-side entity expansion stays in GraphDB."""
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
        """Return chunk summaries/candidates for one document during ingestion or review."""
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
