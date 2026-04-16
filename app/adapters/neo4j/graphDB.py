import json
import logging
import re
from typing import Any
from app.adapters.neo4j._sanitize import sanitize_neo4j_value
from app.adapters.neo4j.vectorDB import VectorDB
from app.config.settings import settings
from app.utils.ids import generate_field_id

log = logging.getLogger("pathfinder.neo4j.graph")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# TODO(rewrite-plan): New backend phases for the Neo4j rewrite.
# Phase 1: Add the required GraphDB/VectorDB functions for the new schema.
# Phase 2: Expose those functions as MCP tools for the LLM.
# Phase 3: Replace the current document-ingestion path so chunk-grounded graph
# creation happens through the new MCP tools, then tighten the ingestion prompts.

class GraphDB:
    """class for student-centric knowledge graph operations."""

    def __init__(self, driver):
        self.driver = driver

    async def init_schema(self) -> None:
        """Create constraints and indexes if they don't exist."""
        async with self.driver.session() as session:
            constraints = [
                "CREATE CONSTRAINT student_id IF NOT EXISTS FOR (s:Student) REQUIRE s.id IS UNIQUE",
                "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",
                "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE",
                "CREATE CONSTRAINT section_student_key IF NOT EXISTS FOR (s:Section) REQUIRE (s.student_id, s.key) IS UNIQUE",
                "CREATE CONSTRAINT field_id IF NOT EXISTS FOR (f:Field) REQUIRE f.id IS UNIQUE",
            ]
            indexes = [
                "CREATE INDEX chunk_doc IF NOT EXISTS FOR (c:Chunk) ON (c.document_id)",
                "CREATE INDEX document_student IF NOT EXISTS FOR (d:Document) ON (d.student_id)",
                "CREATE INDEX entity_student_section IF NOT EXISTS FOR (e:Entity) ON (e.student_id, e.section_key)",
                "CREATE INDEX field_owner IF NOT EXISTS FOR (f:Field) ON (f.owner_id)",
            ]
            for stmt in constraints + indexes:
                await session.run(stmt)

    async def upsert_student(self, *, student_id: str) -> dict:
        """Create or return the root student node."""
        async with self.driver.session() as session:
            result = await session.run("""
                MERGE (s:Student {id: $student_id})
                ON CREATE SET s.created_at = datetime()
                SET s.updated_at = datetime()
                RETURN s {.*} AS student
            """,
            student_id=student_id,
            )
            record = await result.single()
            if not record:
                raise ValueError(f"Student not found: {student_id}")
            return sanitize_neo4j_value(dict(record["student"]))

    async def create_document(self, *, student_id: str, document_id: str, filename: str, file_type: str = "unknown") -> dict:
        """Create document node. (:Student)-[:UPLOADED]->(:Document)."""
        async with self.driver.session() as session:
            result = await session.run("""
                MERGE (s:Student {id: $student_id})
                MERGE (d:Document {id: $document_id})
                ON CREATE SET d.created_at = datetime()
                SET d.updated_at = datetime(),  
                    d.student_id = $student_id,
                    d.filename = $filename,
                    d.file_type = $file_type
                MERGE (s)-[:UPLOADED]->(d)
                RETURN d {.*} AS document
            """, student_id=student_id, document_id=document_id, filename=filename, file_type=file_type)
            record = await result.single()
            if not record:
                raise ValueError(f"Document not found: {document_id}")
            return sanitize_neo4j_value(dict(record["document"]))

    async def upsert_section(
        self,
        *,
        student_id: str,
        key: str,
        description: str = "",
        parent_key: str = "",
    ) -> dict[str, Any]:
        """Create or update one section and attach it to the student."""
        section_key = str(key or "").strip().lower()
        async with self.driver.session() as session:
            result = await session.run(
                """
                MERGE (s:Student {id: $student_id})
                MERGE (sec:Section {student_id: $student_id, key: $key})
                ON CREATE SET sec.created_at = datetime()
                SET sec.updated_at = datetime(),
                    sec.description = $description,
                    sec.parent_key = $parent_key
                MERGE (s)-[:HAS_SECTION]->(sec)
                RETURN sec {.*} AS section
                """,
                student_id=student_id,
                key=section_key,
                description=str(description or ""),
                parent_key=str(parent_key or "").strip().lower(),
            )
            record = await result.single()
            if not record:
                raise ValueError("section upsert failed")
            return sanitize_neo4j_value(dict(record["section"]))

    async def upsert_graph_node(
        self,
        *,
        student_id: str,
        entity_type: str,
        section_key: str,
        identity: dict[str, str],
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        """Create or update one student-linked entity node."""
        # Example input:
        # student_id="S1", entity_type="Skill", section_key="skills"
        # identity={"name": "python"}
        # properties={"proficiency": "advanced", "years": 3}
        if not student_id:
            raise ValueError("student_id is required")
        node_type = self._safe_identifier(entity_type, "entity_type")
        if not isinstance(identity, dict) or not identity:
            raise ValueError("identity is required")
        if not isinstance(properties, dict):
            raise ValueError("properties must be an object")

        section_key = str(section_key or "").strip().lower()
        if not section_key:
            raise ValueError("section_key is required")

        params: dict[str, Any] = {
            "student_id": student_id,
            "section_key": section_key,
        }
        # `merge_props` builds the identity part of MERGE:
        # ["student_id: $student_id", "name: $id_0"]
        merge_props: list[str] = ["student_id: $student_id"]
        # `set_clauses` builds dynamic SET updates:
        # ["n.updated_at = datetime()", "n.proficiency = $prop_0", "n.years = $prop_1"]
        set_clauses: list[str] = ["n.updated_at = datetime()"]

        for idx, (field, value) in enumerate(identity.items()):
            field_name = self._safe_identifier(field, "identity field")
            param_name = f"id_{idx}"
            merge_props.append(f"{field_name}: ${param_name}")
            params[param_name] = str(value or "").strip()
        # params -> { "student_id": "S1", "id_0": "python" }

        if len(merge_props) == 1:
            raise ValueError("identity must contain at least one usable field")

        for idx, (field, value) in enumerate(properties.items()):
            field_name = self._safe_identifier(field, "property field")
            param_name = f"prop_{idx}"
            set_clauses.append(f"n.{field_name} = ${param_name}")
            params[param_name] = value
        # set_clauses -> ["n.updated_at = datetime()", "n.proficiency = $prop_0", "n.years = $prop_1"]
        # params -> { "student_id": "S1", "id_0": "python", "prop_0": "advanced", "prop_1": 3 }
        merge_props_clause = ", ".join(merge_props)
        # merge_props_clause -> "student_id: $student_id, id_0: python"
        set_clause = ", ".join(set_clauses)
        # set_clause -> "n.updated_at = datetime(), n.prop_0 = advanced, n.prop_1 = 3"
        query = f"""
            MERGE (s:Student {{id: $student_id}})
            MERGE (sec:Section {{student_id: $student_id, key: $section_key}})
            ON CREATE SET sec.created_at = datetime()
            SET sec.updated_at = datetime(),
                sec.description = coalesce(sec.description, ''),
                sec.parent_key = coalesce(sec.parent_key, '')
            MERGE (s)-[:HAS_SECTION]->(sec)
            MERGE (n:Entity:{node_type} {{{merge_props_clause}}})
            ON CREATE SET n.created_at = datetime()
            SET {set_clause},
                n.entity_type = $entity_type,
                n.section_key = $section_key,
                n.student_id = $student_id
            MERGE (sec)-[:HAS_ITEM]->(n)
            RETURN n {{.*}} AS node
            LIMIT 1
        """
        # Resulting MERGE shape (example):
        # MERGE (n:Skill {student_id: $student_id, name: $id_0})

        params["entity_type"] = node_type

        async with self.driver.session() as session:
            result = await session.run(query, params)
            record = await result.single()
            if not record:
                raise ValueError("graph node upsert failed; identity did not match")
            return sanitize_neo4j_value(dict(record["node"]))

    async def upsert_graph_relation(
        self,
        *,
        student_id: str,
        source_entity_type: str,
        source_identity: dict[str, str],
        target_entity_type: str,
        target_identity: dict[str, str],
        relationship_type: str,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create or update one typed relation between two nodes."""
        source_type = self._safe_identifier(source_entity_type, "source_entity_type")
        target_type = self._safe_identifier(target_entity_type, "target_entity_type")
        rel_type = self._safe_identifier(relationship_type, "relationship_type")
        if not student_id:
            raise ValueError("student_id is required")
        if not source_identity or not target_identity:
            raise ValueError("source_identity and target_identity are required")

        src_clauses: list[str] = []
        dst_clauses: list[str] = []
        set_parts: list[str] = []
        params: dict[str, Any] = {"student_id": student_id}

        for idx, (field, value) in enumerate(source_identity.items()):
            safe_field = self._safe_identifier(field, "source identity field")
            param = f"src_{idx}"
            src_clauses.append(f"src.{safe_field} = ${param}")
            params[param] = str(value or "").strip()

        for idx, (field, value) in enumerate(target_identity.items()):
            safe_field = self._safe_identifier(field, "target identity field")
            param = f"dst_{idx}"
            dst_clauses.append(f"dst.{safe_field} = ${param}")
            params[param] = str(value or "").strip()

        for idx, (field, value) in enumerate((properties or {}).items()):
            safe_field = self._safe_identifier(field, "relation property field")
            param = f"rel_{idx}"
            set_parts.append(f"r.{safe_field} = ${param}")
            params[param] = value
        set_parts.append("r.updated_at = datetime()")

        query = f"""
        MATCH (s:Student {{id: $student_id}})
        CALL {{
            WITH s
            MATCH (s)-[:HAS_SECTION]->(:Section)-[:HAS_ITEM]->(src:Entity:{source_type})
            WHERE src.student_id = $student_id
              AND {" AND ".join(src_clauses)}
            RETURN src
            LIMIT 1
        }}
        CALL {{
            WITH s
            MATCH (s)-[:HAS_SECTION]->(:Section)-[:HAS_ITEM]->(dst:Entity:{target_type})
            WHERE dst.student_id = $student_id
              AND {" AND ".join(dst_clauses)}
            RETURN dst
            LIMIT 1
        }}
        MERGE (src)-[r:{rel_type}]->(dst)
        ON CREATE SET r.created_at = datetime()
        SET {", ".join(set_parts)}
        RETURN {{
            relationship_type: type(r),
            source: src {{.*}},
            target: dst {{.*}},
            relationship: properties(r)
        }} AS relation
        LIMIT 1
        """

        async with self.driver.session() as session:
            result = await session.run(query, params)
            record = await result.single()
            if not record:
                raise ValueError("graph relation upsert failed; nodes not found")
            return sanitize_neo4j_value(dict(record["relation"]))

    @staticmethod
    def _safe_identifier(value: str, field_name: str) -> str:
        raw = str(value or "").strip()
        if not raw or not _IDENTIFIER.fullmatch(raw):
            raise ValueError(f"Invalid {field_name}: {value}")
        return raw
    
    async def get_student_sections(self, *, student_id: str) -> list[dict]:
        """Return all sections for a student."""
        async with self.driver.session() as session:
            result = await session.run("""
                MATCH (s:Student {id: $student_id})-[:HAS_SECTION]->(sec:Section)
                RETURN sec {.*} AS section
            """, student_id=student_id)
            rows = [dict(record["section"]) async for record in result]
            return sanitize_neo4j_value(rows)

    async def get_section_entities(self, *, student_id: str, section_key: str) -> list[dict]:
        """Return all entities under one section."""
        async with self.driver.session() as session:
            result = await session.run("""
                MATCH (s:Student {id: $student_id})-[:HAS_SECTION]->(sec:Section {key: $section_key})-[:HAS_ITEM]->(ent:Entity)
                RETURN ent {.*} AS entity
            """, student_id=student_id, section_key=section_key)
            rows = [dict(record["entity"]) async for record in result]
            return sanitize_neo4j_value(rows)
    
    async def get_entity_by_identity(self, *, student_id: str, entity_type: str, identity: dict[str, str]) -> dict:
        """Find an existing entity inside a student by type + identity."""
        safe_entity_type = self._safe_identifier(entity_type, "entity_type")
        if not identity:
            raise ValueError("identity is required")
        where_parts: list[str] = ["ent.student_id = $student_id"]
        params: dict[str, Any] = {"student_id": student_id}
        for idx, (field, value) in enumerate(identity.items()):
            safe_field = self._safe_identifier(field, "identity field")
            param_name = f"id_{idx}"
            where_parts.append(f"ent.{safe_field} = ${param_name}")
            params[param_name] = str(value or "").strip()
        async with self.driver.session() as session:
            result = await session.run(
                f"""
                MATCH (s:Student {{id: $student_id}})-[:HAS_SECTION]->(:Section)-[:HAS_ITEM]->(ent:Entity:{safe_entity_type})
                WHERE {" AND ".join(where_parts)}
                RETURN ent {{.*}} AS entity
                LIMIT 1
                """,
                params,
            )
            record = await result.single()
            if not record:
                raise ValueError("entity not found")
            return sanitize_neo4j_value(dict(record["entity"]))
    
    async def upsert_entity_field(
        self,
        *,
        student_id: str,
        entity_type: str,
        entity_identity: dict[str, str],
        field_name: str,
        field_value: Any,
    ) -> dict:
        """Add/update one complex Field node under an Entity for expandable nested details."""
        safe_entity_type = self._safe_identifier(entity_type, "entity_type")
        safe_field_name = self._safe_identifier(field_name, "field_name")
        if not entity_identity:
            raise ValueError("entity_identity is required")
        owner_key = self._entity_owner_key(student_id, safe_entity_type, entity_identity)
        where_parts: list[str] = ["ent.student_id = $student_id"]
        params: dict[str, Any] = {
            "student_id": student_id,
            "field_name": safe_field_name,
            "field_value": field_value,
            "owner_id": owner_key,
            "field_id": generate_field_id(),
            "field_value_json": json.dumps(field_value, ensure_ascii=True, default=str),
        }
        for idx, (field, value) in enumerate(entity_identity.items()):
            safe_field = self._safe_identifier(field, "identity field")
            param_name = f"id_{idx}"
            where_parts.append(f"ent.{safe_field} = ${param_name}")
            params[param_name] = str(value or "").strip()
        async with self.driver.session() as session:
            result = await session.run(
                f"""
                MATCH (s:Student {{id: $student_id}})-[:HAS_SECTION]->(:Section)-[:HAS_ITEM]->(ent:Entity:{safe_entity_type})
                WHERE {" AND ".join(where_parts)}
                MERGE (ent)-[:HAS_FIELD]->(f:Field {{owner_id: $owner_id, key: $field_name}})
                ON CREATE SET f.id = $field_id, f.created_at = datetime()
                SET f.updated_at = datetime(),
                    f.value = $field_value,
                    f.value_json = $field_value_json
                RETURN f {{.*}} AS field
                LIMIT 1
                """,
                params,
            )
            record = await result.single()
            if not record:
                raise ValueError("entity field upsert failed")
            return sanitize_neo4j_value(dict(record["field"]))

    async def list_entity_fields(
        self,
        *,
        student_id: str,
        entity_type: str,
        entity_identity: dict[str, str],
    ) -> list[dict]:
        """Return Field nodes for one entity so retrieval can show structured details."""
        safe_entity_type = self._safe_identifier(entity_type, "entity_type")
        if not entity_identity:
            raise ValueError("entity_identity is required")
        where_parts: list[str] = ["ent.student_id = $student_id"]
        params: dict[str, Any] = {"student_id": student_id}
        for idx, (field, value) in enumerate(entity_identity.items()):
            safe_field = self._safe_identifier(field, "identity field")
            param_name = f"id_{idx}"
            where_parts.append(f"ent.{safe_field} = ${param_name}")
            params[param_name] = str(value or "").strip()
        async with self.driver.session() as session:
            result = await session.run(
                f"""
                MATCH (s:Student {{id: $student_id}})-[:HAS_SECTION]->(:Section)-[:HAS_ITEM]->(ent:Entity:{safe_entity_type})
                WHERE {" AND ".join(where_parts)}
                MATCH (ent)-[:HAS_FIELD]->(f:Field)
                RETURN f {{.*}} AS field
                ORDER BY f.key
                """,
                params,
            )
            rows = [dict(record["field"]) async for record in result]
            return sanitize_neo4j_value(rows)

    async def upsert_nested_field(
        self,
        *,
        student_id: str,
        parent_field_id: str,
        field_name: str,
        field_value: Any | None = None,
    ) -> dict:
        """Add or update one child Field node under an existing parent Field."""
        safe_field_name = self._safe_identifier(field_name, "field_name")
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (s:Student {id: $student_id})-[:HAS_SECTION]->(:Section)-[:HAS_ITEM]->(:Entity)-[:HAS_FIELD*1..6]->(parent:Field {id: $parent_field_id})
                MERGE (parent)-[:HAS_FIELD]->(child:Field {owner_id: $parent_field_id, key: $field_name})
                ON CREATE SET child.id = $field_id, child.created_at = datetime()
                SET child.updated_at = datetime(),
                    child.value = $field_value,
                    child.value_json = $field_value_json
                RETURN child {.*} AS field
                LIMIT 1
                """,
                student_id=student_id,
                parent_field_id=parent_field_id,
                field_name=safe_field_name,
                field_id=generate_field_id(),
                field_value=field_value,
                field_value_json=json.dumps(field_value, ensure_ascii=True, default=str),
            )
            record = await result.single()
            if not record:
                raise ValueError("nested field upsert failed")
            return sanitize_neo4j_value(dict(record["field"]))
            
    async def link_entity_to_chunk(
        self,
        *,
        student_id: str,
        entity_type: str,
        entity_identity: dict[str, str],
        chunk_id: str,
    ) -> dict:
        """Create the grounding edge (:Entity)-[:MENTIONED_IN]->(Chunk)."""
        safe_entity_type = self._safe_identifier(entity_type, "entity_type")
        if not entity_identity:
            raise ValueError("entity_identity is required")
        where_parts: list[str] = ["ent.student_id = $student_id"]
        params: dict[str, Any] = {"student_id": student_id, "chunk_id": chunk_id}
        for idx, (field, value) in enumerate(entity_identity.items()):
            safe_field = self._safe_identifier(field, "identity field")
            param_name = f"id_{idx}"
            where_parts.append(f"ent.{safe_field} = ${param_name}")
            params[param_name] = str(value or "").strip()
        async with self.driver.session() as session:
            result = await session.run(
                f"""
                MATCH (s:Student {{id: $student_id}})-[:HAS_SECTION]->(:Section)-[:HAS_ITEM]->(ent:Entity:{safe_entity_type})
                WHERE {" AND ".join(where_parts)}
                MATCH (c:Chunk {{id: $chunk_id}})
                MERGE (ent)-[:MENTIONED_IN]->(c)
                RETURN ent {{.*}} AS entity
                LIMIT 1
                """,
                params,
            )
            record = await result.single()
            if not record:
                raise ValueError("entity chunk link failed")
            return sanitize_neo4j_value(dict(record["entity"]))

    async def link_entity_to_document(
        self,
        *,
        student_id: str,
        entity_type: str,
        entity_identity: dict[str, str],
        document_id: str,
    ) -> dict:
        """Create the coarse provenance edge (:Entity)-[:DERIVED_FROM]->(Document)."""
        safe_entity_type = self._safe_identifier(entity_type, "entity_type")
        if not entity_identity:
            raise ValueError("entity_identity is required")
        where_parts: list[str] = ["ent.student_id = $student_id"]
        params: dict[str, Any] = {"student_id": student_id, "document_id": document_id}
        for idx, (field, value) in enumerate(entity_identity.items()):
            safe_field = self._safe_identifier(field, "identity field")
            param_name = f"id_{idx}"
            where_parts.append(f"ent.{safe_field} = ${param_name}")
            params[param_name] = str(value or "").strip()
        async with self.driver.session() as session:
            result = await session.run(
                f"""
                MATCH (s:Student {{id: $student_id}})-[:HAS_SECTION]->(:Section)-[:HAS_ITEM]->(ent:Entity:{safe_entity_type})
                WHERE {" AND ".join(where_parts)}
                MATCH (d:Document {{id: $document_id}})
                MERGE (ent)-[:DERIVED_FROM]->(d)
                RETURN ent {{.*}} AS entity
                LIMIT 1
                """,
                params,
            )
            record = await result.single()
            if not record:
                raise ValueError("entity document link failed")
            return sanitize_neo4j_value(dict(record["entity"]))

    async def get_chunk_entities(self, *, student_id: str, chunk_id: str) -> list[dict]:
        """Return entities connected to one chunk for chunk-centered traversal."""
        async with self.driver.session() as session:
            result = await session.run("""
                MATCH (s:Student {id: $student_id})-[:HAS_SECTION]->(:Section)-[:HAS_ITEM]->(ent:Entity)-[:MENTIONED_IN]->(c:Chunk {id: $chunk_id})
                RETURN ent {.*} AS entity
            """, student_id=student_id, chunk_id=chunk_id)
            rows = [dict(record["entity"]) async for record in result]
            return sanitize_neo4j_value(rows)

    async def bfs_neighbors(self, *, student_id: str, start_node_id: str, max_depth: int = 1) -> list[dict]:
        """Generic traversal helper so the LLM can inspect connected nodes step by step."""
        depth = max(1, min(int(max_depth), 5))
        async with self.driver.session() as session:
            result = await session.run(
                f"""
                MATCH (start {{id: $start_node_id}})
                OPTIONAL MATCH path = (start)-[*1..{depth}]-(nbr)
                WHERE nbr IS NOT NULL
                WITH start, nbr, min(length(path)) AS hop
                ORDER BY hop ASC
                RETURN start {{.*, labels: labels(start)}} AS start_node,
                       collect(DISTINCT {{
                           depth: hop,
                           node: nbr {{.*, labels: labels(nbr)}}
                       }}) AS discovered
                """,
                start_node_id=start_node_id,
            )
            record = await result.single()
            if not record or not record["start_node"]:
                raise ValueError("bfs neighbors not found")
            grouped: dict[int, list[dict[str, Any]]] = {}
            for item in (record["discovered"] or []):
                hop = int(item.get("depth", 0) or 0)
                node = item.get("node")
                if hop <= 0 or not node:
                    continue
                grouped.setdefault(hop, []).append(dict(node))

            return sanitize_neo4j_value({
                "start_node": dict(record["start_node"]),
                "levels": [
                    {
                        "depth": level,
                        "nodes": grouped.get(level, []),
                    }
                    for level in range(1, depth + 1)
                    if grouped.get(level)
                ],
            })

    async def get_full_student(self, *, student_id: str) -> dict:
        """Student-wide read model containing sections, entities, fields, and provenance."""
        async with self.driver.session() as session:
            student_result = await session.run("""
                MATCH (s:Student {id: $student_id})
                RETURN s {.*} AS student
            """, student_id=student_id)
            student_record = await student_result.single()
            if not student_record:
                raise ValueError("full student not found")

            section_result = await session.run("""
                MATCH (:Student {id: $student_id})-[:HAS_SECTION]->(sec:Section)
                RETURN sec {.*} AS section
                ORDER BY sec.key
            """, student_id=student_id)
            sections = [dict(record["section"]) async for record in section_result]

            entity_result = await session.run("""
                MATCH (:Student {id: $student_id})-[:HAS_SECTION]->(sec:Section)-[:HAS_ITEM]->(ent:Entity)
                OPTIONAL MATCH (ent)-[:HAS_FIELD]->(f:Field)
                OPTIONAL MATCH (ent)-[:MENTIONED_IN]->(c:Chunk)
                OPTIONAL MATCH (ent)-[:DERIVED_FROM]->(d:Document)
                RETURN ent {.*} AS entity,
                       sec.key AS section_key,
                       collect(DISTINCT f {.*}) AS fields,
                       collect(DISTINCT c { .id, .document_id, .metadata_json }) AS chunks,
                       collect(DISTINCT d { .id, .filename, .file_type }) AS documents
            """, student_id=student_id)
            entities = []
            async for record in entity_result:
                entity = dict(record["entity"])
                entity["section_key"] = record["section_key"]
                entity["fields"] = [dict(field) for field in (record["fields"] or []) if field]
                entity["chunks"] = [
                    self._chunk_payload(chunk)
                    for chunk in (record["chunks"] or [])
                    if chunk and chunk.get("id")
                ]
                entity["documents"] = [dict(document) for document in (record["documents"] or []) if document and document.get("id")]
                entities.append(entity)

            return sanitize_neo4j_value({
                "student": dict(student_record["student"]),
                "sections": sections,
                "entities": entities,
            })

    async def hybrid_search(
        self,
        *,
        student_id: str,
        query: str,
        k: int = 5,
    ) -> list[dict[str, Any]]:
        """Vector retrieval enriched with explicit graph grounding."""
        if not student_id:
            raise ValueError("student_id is required")
        query = str(query or "").strip()
        if not query:
            return []

        vector_db = VectorDB(
            self.driver,
            index_name="chunk_embeddings",
            dimensions=int(settings.EMBEDDING_DIMENSIONS),
        )
        vector_results = await vector_db.similarity_search(
            query=query,
            student_id=student_id,
            k=k,
        )
        if not vector_results:
            return []

        chunk_refs = [
            {"chunk_id": item["id"], "document_id": item["document_id"]}
            for item in vector_results
            if item.get("id") and item.get("document_id")
        ]
        if not chunk_refs:
            return vector_results

        related_by_chunk: dict[tuple[str, str], dict[str, Any]] = {}
        async with self.driver.session() as session:
            result = await session.run(
                """
                UNWIND $chunk_refs AS ref
                MATCH (s:Student {id: $student_id})-[:UPLOADED]->(d:Document {id: ref.document_id})<-[:FROM_DOCUMENT]-(c:Chunk {id: ref.chunk_id})
                OPTIONAL MATCH (s)-[:HAS_SECTION]->(sec:Section)-[:HAS_ITEM]->(ent:Entity)-[:MENTIONED_IN]->(c)
                WITH s, d, c, ref, collect(DISTINCT {entity: ent, section: sec}) AS direct_pairs
                OPTIONAL MATCH (s)-[:HAS_SECTION]->(doc_sec:Section)-[:HAS_ITEM]->(doc_ent:Entity)-[:DERIVED_FROM]->(d)
                WITH ref, d, c, direct_pairs, collect(DISTINCT {entity: doc_ent, section: doc_sec}) AS document_pairs
                RETURN ref.chunk_id AS chunk_id,
                       ref.document_id AS document_id,
                       d { .id, .filename, .file_type, .student_id } AS document,
                       c { .id, .text, .document_id, .metadata_json } AS chunk,
                       [
                         pair IN direct_pairs
                         WHERE pair.entity IS NOT NULL |
                         {
                           entity: properties(pair.entity),
                           entity_labels: labels(pair.entity),
                           section: properties(pair.section),
                           provenance: 'MENTIONED_IN'
                         }
                       ] AS direct_entities,
                       [
                         pair IN document_pairs
                         WHERE pair.entity IS NOT NULL |
                         {
                           entity: properties(pair.entity),
                           entity_labels: labels(pair.entity),
                           section: properties(pair.section),
                           provenance: 'DERIVED_FROM'
                         }
                       ] AS document_entities
                """,
                student_id=student_id,
                chunk_refs=chunk_refs,
            )
            async for record in result:
                key = (record["chunk_id"], record["document_id"])
                direct_entities = list(record["direct_entities"] or [])
                document_entities = list(record["document_entities"] or [])

                seen_entity_keys: set[str] = set()
                entities: list[dict[str, Any]] = []
                for item in direct_entities + document_entities:
                    entity = dict(item.get("entity") or {})
                    entity["labels"] = list(item.get("entity_labels") or [])
                    entity_key = self._result_entity_key(entity)
                    if not entity_key or entity_key in seen_entity_keys:
                        continue
                    seen_entity_keys.add(entity_key)
                    entities.append(
                        {
                            "entity": dict(entity),
                            "section": dict(item.get("section") or {}),
                            "provenance": item.get("provenance"),
                        }
                    )

                ranked_entities = sorted(
                    entities,
                    key=lambda item: self._hybrid_entity_rank(
                        query=query,
                        chunk_text=str((record["chunk"] or {}).get("text", "") or ""),
                        entity=item.get("entity") or {},
                        section=item.get("section") or {},
                        provenance=str(item.get("provenance", "") or ""),
                    ),
                    reverse=True,
                )[:5]

                related_by_chunk[key] = {
                    "document": dict(record["document"] or {}),
                    "chunk": self._chunk_payload(record["chunk"] or {}),
                    "entities": ranked_entities,
                }

        enriched: list[dict[str, Any]] = []
        for item in vector_results:
            key = (item.get("id"), item.get("document_id"))
            related = related_by_chunk.get(key, {})
            enriched.append(
                {
                    **item,
                    "document": related.get("document", {}),
                    "chunk": related.get("chunk", {}),
                    "related_entities": related.get("entities", []),
                }
            )
        return sanitize_neo4j_value(enriched)

    def _entity_owner_key(self, student_id: str, entity_type: str, identity: dict[str, str]) -> str:
        normalized_identity = json.dumps(identity, sort_keys=True, ensure_ascii=True)
        return f"{student_id}:{entity_type}:{normalized_identity}"

    def _result_entity_key(self, entity: dict[str, Any]) -> str:
        for key in ("id", "name", "code", "title", "value"):
            value = str(entity.get(key, "") or "").strip()
            if value:
                return f"{entity.get('entity_type', '')}:{key}:{value}"
        return ""

    def _chunk_payload(self, chunk: dict[str, Any]) -> dict[str, Any]:
        payload = dict(chunk or {})
        metadata = self._metadata_dict(payload.get("metadata_json"))
        payload["metadata"] = metadata
        payload.pop("metadata_json", None)
        return payload

    def _metadata_dict(self, raw_metadata: Any) -> dict[str, Any]:
        if isinstance(raw_metadata, dict):
            return raw_metadata
        if not raw_metadata:
            return {}
        try:
            parsed = json.loads(str(raw_metadata))
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _hybrid_entity_rank(
        self,
        *,
        query: str,
        chunk_text: str,
        entity: dict[str, Any],
        section: dict[str, Any],
        provenance: str,
    ) -> tuple[int, int, int, int]:
        query_tokens = self._text_tokens(query)
        chunk_tokens = self._text_tokens(chunk_text)
        entity_tokens = self._text_tokens(
            " ".join(
                str(entity.get(key, "") or "")
                for key in ("name", "title", "code", "value", "entity_type")
            )
        )
        section_tokens = self._text_tokens(
            " ".join(
                str(section.get(key, "") or "")
                for key in ("key", "description", "parent_key")
            )
        )

        provenance_score = 2 if provenance == "MENTIONED_IN" else 1
        query_entity_overlap = len(query_tokens & entity_tokens)
        query_section_overlap = len(query_tokens & section_tokens)
        chunk_entity_overlap = len(chunk_tokens & entity_tokens)
        return (
            provenance_score,
            query_entity_overlap,
            query_section_overlap,
            chunk_entity_overlap,
        )

    def _text_tokens(self, value: str) -> set[str]:
        return {
            token.lower()
            for token in re.findall(r"[A-Za-z0-9_]+", str(value or ""))
            if token
        }
