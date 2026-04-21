"""Structured (non-vector) operations against the Neo4j graph.

This module is the single owner of the Cypher that shapes the student
knowledge graph. Its mental model:

    (:Student {id}) -[:HAS_SECTION]->  (:Section {key})
                     -[:HAS_ENTITY]->  (:Entity {type, identity})
                                        -[:HAS_FIELD]-> (:Field ...)
                                        -[:MENTIONED_IN]-> (:Chunk)
                                        -[:DERIVED_FROM]-> (:Document)
                     -[:HAS_DOCUMENT]-> (:Document) -> (:Chunk)

- `Student` is the root per-user node; everything belongs to exactly one
  student.
- `Section` groups related entities under a stable key (e.g. "education").
- `Entity` is any typed concept (Course, Employer, Award, ...) with a
  small identity dict that dedupes it and a properties dict that carries
  its scalar attributes.
- `Field` is an optional child of an entity for deeper / nested detail.
- `Document` + `Chunk` come from file ingestion; entities can be grounded
  in them so we can cite sources.

`GraphDB` is instantiated with an async Neo4j driver and exposes one
method per operation the tool layer (`app.tools.graph_tools`) wants to
expose to the LLM. Every return value is piped through
`sanitize_neo4j_value` so callers see clean dicts / lists / scalars
instead of Neo4j driver types.

Vector / embedding work lives in the sibling `vectorDB.py`; this file
only reaches over there when a graph write also needs to refresh chunk
embeddings (e.g. cascade deletes).
"""

import json
import logging
import re
import hashlib
from typing import Any
from app.adapters.neo4j._sanitize import sanitize_neo4j_value
from app.adapters.neo4j.vectorDB import VectorDB
from app.config.settings import settings
from app.utils.ids import generate_field_id

log = logging.getLogger("pathfinder.neo4j.graph")

# Relation / property names must be valid Neo4j identifiers — we never
# inline user input into Cypher so this regex is the last-line guard.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_GRAPH_METADATA_KEYS = {
    "created_at",
    "updated_at",
    "student_id",
    "section_key",
    "identity_keys",
    "fields",
    "chunks",
    "documents",
    "labels",
}
_SCHEMA_METADATA_KEYS = _GRAPH_METADATA_KEYS | {"value_json", "metadata_json"}
_SCHEMA_SAMPLE_LIMIT = 3

class GraphDB:
    """All structured reads and writes for one Neo4j driver.

    Instances are cheap — they just wrap the shared async driver — so
    callers build one per request/tool invocation. Methods come in two
    flavors: "read" (profile, sections, entities, relations, documents,
    schema) and "write" (upsert / delete / cascade). The write methods
    do their own validation so the LLM tool layer can pass-through
    user-provided strings safely.
    """

    def __init__(self, driver):
        self.driver = driver

    async def init_schema(self) -> None:
        """Create constraints + indexes at process startup.

        Idempotent: uses `IF NOT EXISTS` so it's safe to run on every
        boot. `app.main.lifespan` calls this once; nothing else should.
        """
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

    async def get_student(self, *, student_id: str) -> dict[str, Any] | None:
        """Return the root Student node as a plain dict, or `None` if unknown.

        Thin read — callers that need the full profile use
        `get_full_student` instead.
        """
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (s:Student {id: $student_id})
                RETURN s {.*} AS student
                LIMIT 1
                """,
                student_id=student_id,
            )
            record = await result.single()
            if not record:
                return None
            return sanitize_neo4j_value(dict(record["student"]))

    async def update_student(self, *, student_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Upsert the Student node and patch any scalar properties in one round trip.

        Also doubles as "make sure this student exists" — called with an
        empty `updates` dict from the API layer so a fresh client can
        start using the app without a separate create step.
        """
        # `updated_at` is always refreshed so we can sort students by
        # recency even when only a handful of fields actually changed.
        assignments: list[str] = ["s.updated_at = datetime()"]
        params: dict[str, Any] = {"student_id": student_id}
        for idx, (key, value) in enumerate(updates.items()):
            if value is None:
                continue
            field = self._safe_identifier(str(key or "").strip(), "student field")
            param = f"value_{idx}"
            assignments.append(f"s.{field} = ${param}")
            params[param] = value
        async with self.driver.session() as session:
            await session.run(
                f"""
                MERGE (s:Student {{id: $student_id}})
                ON CREATE SET s.created_at = datetime()
                SET {", ".join(assignments)}
                """,
                params,
            )
        return await self.get_student(student_id=student_id) or {"id": student_id}

    async def create_document(self, *, student_id: str, document_id: str, filename: str, file_type: str = "unknown") -> dict:
        """Register a new uploaded document and wire it to its owner student.

        The doc_analyst node calls this before it pushes any chunks so
        the chunks have something to be `(:Chunk)-[:FROM_DOCUMENT]->`.
        """
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

    async def find_document_by_filename(self, *, student_id: str, filename: str) -> dict[str, Any] | None:
        """Look up a student's existing document by its filename, if any.

        Powers the "Replace existing?" prompt in the UI and the
        `replace=true` upload path — both want to know whether a new
        upload with the same name already exists.
        """
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (:Student {id: $student_id})-[:UPLOADED]->(d:Document {filename: $filename})
                RETURN d {.*} AS document
                LIMIT 1
                """,
                student_id=student_id,
                filename=filename,
            )
            record = await result.single()
            if not record:
                return None
            return sanitize_neo4j_value(dict(record["document"]))

    async def delete_document_cascade(self, *, document_id: str) -> dict[str, Any]:
        """Wipe a document *and* every chunk attached to it in one query.

        Used when the user replaces or deletes a document. Leaves the
        rest of the student graph intact — only the doc + its chunks
        disappear. (Entities grounded to those chunks keep their other
        links if they have any.)
        """
        async with self.driver.session() as session:
            await session.run(
                """
                MATCH (d:Document {id: $document_id})
                OPTIONAL MATCH (c:Chunk)-[:FROM_DOCUMENT]->(d)
                DETACH DELETE c, d
                """,
                document_id=document_id,
            )
        return sanitize_neo4j_value({"status": "success", "document_id": document_id})

    async def upsert_section(
        self,
        *,
        student_id: str,
        key: str,
        description: str = "",
        parent_key: str = "",
    ) -> dict[str, Any]:
        """Create/update a Section (grouping of related entities) under a student.

        Sections are the top-level organizational layer below the student
        — e.g. "education", "work_experience". `parent_key` allows simple
        nesting (a "projects" section living under "work_experience").
        """
        section_key = str(key or "").strip().lower()
        async with self.driver.session() as session:
            result = await session.run(
                """
                MERGE (s:Student {id: $student_id})
                MERGE (sec:Section {student_id: $student_id, key: $key})
                ON CREATE SET sec.created_at = datetime()
                SET sec.updated_at = datetime(),
                    sec.description = $description,
                    sec.parent_key = $parent_key,
                    sec.display_name = $display_name
                MERGE (s)-[:HAS_SECTION]->(sec)
                RETURN sec {.*} AS section
                """,
                student_id=student_id,
                key=section_key,
                description=str(description or ""),
                parent_key=str(parent_key or "").strip().lower(),
                display_name=self._display_name("Section", key=section_key),
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
        """Create/update one typed entity under a section on the student graph.

        `identity` is the "what makes this thing unique" dict (e.g.
        `{"name": "python"}` for a skill) — we MERGE on it so the same
        logical entity updates instead of duplicating.
        `properties` are the freeform scalar attributes the ingester
        learned about it.

        Example:
            entity_type="Skill", section_key="skills"
            identity={"name": "python"}
            properties={"proficiency": "advanced", "years": 3}
        """
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

        # `merge_props` becomes the identity clause of the MERGE — these
        # are the fields that must ALL match for Neo4j to treat two
        # writes as the same entity. Everything else is just properties
        # on an already-matched node.
        merge_props: list[str] = ["student_id: $student_id"]
        # `set_clauses` are everything we want written to the node on
        # both create and update.
        set_clauses: list[str] = ["n.updated_at = datetime()"]

        for idx, (field, value) in enumerate(identity.items()):
            field_name = self._safe_identifier(field, "identity field")
            param_name = f"id_{idx}"
            merge_props.append(f"{field_name}: ${param_name}")
            params[param_name] = str(value or "").strip()

        if len(merge_props) == 1:
            raise ValueError("identity must contain at least one usable field")

        # Stored on the node so reads can tell which fields participate in
        # its identity (the rest are freely editable properties).
        params["identity_keys"] = [
            self._safe_identifier(field, "identity field")
            for field in identity.keys()
            if str(field or "").strip()
        ]

        for idx, (field, value) in enumerate(properties.items()):
            field_name = self._safe_identifier(field, "property field")
            param_name = f"prop_{idx}"
            set_clauses.append(f"n.{field_name} = ${param_name}")
            params[param_name] = value
        merge_props_clause = ", ".join(merge_props)
        set_clause = ", ".join(set_clauses)

        # Single query does three things at once:
        #   1. ensure the Student and Section nodes exist,
        #   2. MERGE the typed Entity on its identity,
        #   3. attach it to the Section via `HAS_ITEM`.
        query = f"""
            MERGE (s:Student {{id: $student_id}})
            MERGE (sec:Section {{student_id: $student_id, key: $section_key}})
            ON CREATE SET sec.created_at = datetime()
            SET sec.updated_at = datetime(),
                sec.description = coalesce(sec.description, ''),
                sec.parent_key = coalesce(sec.parent_key, ''),
                sec.display_name = $section_display_name
            MERGE (s)-[:HAS_SECTION]->(sec)
            MERGE (n:Entity:{node_type} {{{merge_props_clause}}})
            ON CREATE SET n.created_at = datetime()
            SET {set_clause},
                n.entity_type = $entity_type,
                n.section_key = $section_key,
                n.student_id = $student_id,
                n.identity_keys = $identity_keys,
                n.display_name = $display_name
            MERGE (sec)-[:HAS_ITEM]->(n)
            RETURN n {{.*}} AS node
            LIMIT 1
        """

        params["entity_type"] = node_type
        params["section_display_name"] = self._display_name("Section", key=section_key)
        # Precomputed display names keep Neo4j Browser and the UI from
        # having to format raw keys every time a node is rendered.
        params["display_name"] = self._display_name(
            "Entity", entity_type=node_type, identity=identity, properties=properties
        )

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
        """Connect two existing entities with a typed relationship.

        Both endpoints must already exist on the student's graph —
        missing nodes fail the query rather than creating placeholders.
        `relationship_type` becomes a real Neo4j relationship label so
        we can do typed traversals (e.g. `[:WORKED_AT]`).
        """
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
        # Single params map keyed with distinct prefixes (src_, dst_,
        # rel_) so identity fields from the two endpoints plus the
        # relation's own properties can't collide.
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
        CALL (s) {{
            MATCH (s)-[:HAS_SECTION]->(:Section)-[:HAS_ITEM]->(src:Entity:{source_type})
            WHERE src.student_id = $student_id
              AND {" AND ".join(src_clauses)}
            RETURN src
            LIMIT 1
        }}
        CALL (s) {{
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
    def _display_name(label: str, *, key: str = "", entity_type: str = "",
                      identity: dict[str, Any] | None = None,
                      properties: dict[str, Any] | None = None) -> str:
        """Pick a human-friendly caption for a node.

        Stored as `display_name` on every write so Neo4j Browser, the
        graph visualization, and debug views all show something
        readable (e.g. "Python" instead of a hashed identity dict).
        """
        if label == "Section":
            return str(key or "").replace("_", " ").strip().title() or "Section"
        if label == "Field":
            return str(key or "").replace("_", " ").strip().title() or "Field"
        if label == "Entity":
            identity = identity or {}
            properties = properties or {}
            for k in ("name", "title", "code"):
                value = str(properties.get(k) or identity.get(k) or "").strip()
                if value:
                    return value
            for value in identity.values():
                value = str(value or "").strip()
                if value:
                    return value
            return str(entity_type or "").strip() or "Entity"
        return ""

    @staticmethod
    def _safe_identifier(value: str, field_name: str) -> str:
        """Reject anything that isn't a valid Neo4j identifier.

        Identifiers (entity types, relationship types, property keys)
        get templated into Cypher strings, so this is the hard gate
        against injection. Real "display values" for a field should
        go into `properties`, not into the identifier slot.
        """
        raw = str(value or "").strip()
        if not raw or not _IDENTIFIER.fullmatch(raw):
            raise ValueError(f"Invalid {field_name}: {value}")
        return raw

    @staticmethod
    def _safe_field_key(value: str, field_name: str = "field_name") -> str:
        """Looser check for field names — they're parameterized, not templated.

        Used where a non-empty, trimmed string is enough because the
        value flows through a bound parameter rather than directly
        into Cypher.
        """
        raw = str(value or "").strip()
        if not raw:
            raise ValueError(f"Invalid {field_name}: {value}")
        return raw

    async def get_student_sections(self, *, student_id: str) -> list[dict]:
        """Every Section node owned by this student."""
        async with self.driver.session() as session:
            result = await session.run("""
                MATCH (s:Student {id: $student_id})-[:HAS_SECTION]->(sec:Section)
                RETURN sec {.*} AS section
            """, student_id=student_id)
            rows = [dict(record["section"]) async for record in result]
            return sanitize_neo4j_value(rows)

    async def get_section_entities(self, *, student_id: str, section_key: str) -> list[dict]:
        """All entities grouped under one section (e.g. every Skill in "skills")."""
        async with self.driver.session() as session:
            result = await session.run("""
                MATCH (s:Student {id: $student_id})-[:HAS_SECTION]->(sec:Section {key: $section_key})-[:HAS_ITEM]->(ent:Entity)
                RETURN ent {.*} AS entity
            """, student_id=student_id, section_key=section_key)
            rows = [dict(record["entity"]) async for record in result]
            return sanitize_neo4j_value(rows)
    
    async def get_entity_by_identity(
        self, *, student_id: str, entity_type: str, identity: dict[str, str]
    ) -> dict[str, Any] | None:
        """Exact-match lookup by (type, identity) — returns `None` if missing.

        Ingestion uses this to decide between "update the existing
        entity" vs "create a new one" when new evidence lands.
        """
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
                return None
            return sanitize_neo4j_value(dict(record["entity"]))

    async def get_student_schema(self, *, student_id: str) -> dict[str, Any]:
        """Compact "what does this student's graph look like?" manifest.

        Bundles:
        - student root properties (keys + sampled values),
        - every section,
        - an `entity_manifest` listing entity types, their property
          keys, and a few example values,
        - a `relationship_manifest` showing source → rel → target
          patterns that actually exist,
        - high-level counts (sections / entities / documents / chunks).

        The ingestion prompt reads this so the LLM reuses existing
        labels instead of minting near-duplicates.
        """
        sections = await self.get_student_sections(student_id=student_id)

        async with self.driver.session() as session:
            student_result = await session.run(
                """
                MATCH (s:Student {id: $student_id})
                RETURN s {.*} AS student
                """,
                student_id=student_id,
            )
            student_record = await student_result.single()
            student_props = dict(student_record["student"]) if student_record and student_record.get("student") else {}

            entity_result = await session.run(
                """
                MATCH (:Student {id: $student_id})-[:HAS_SECTION]->(:Section)-[:HAS_ITEM]->(ent:Entity)
                RETURN ent {.*} AS entity
                ORDER BY coalesce(ent.entity_type, 'Entity'), coalesce(ent.updated_at, ent.created_at)
                """,
                student_id=student_id,
            )
            entities = [dict(record["entity"]) async for record in entity_result if record and record.get("entity")]

            relationship_result = await session.run(
                """
                MATCH (:Student {id: $student_id})-[:HAS_SECTION]->(:Section)-[:HAS_ITEM]->(src:Entity)-[r]->(dst:Entity)
                WHERE src.student_id = $student_id AND dst.student_id = $student_id
                RETURN
                    type(r) AS relationship_type,
                    coalesce(src.entity_type, 'Entity') AS source_entity_type,
                    coalesce(dst.entity_type, 'Entity') AS target_entity_type,
                    count(r) AS relationship_count
                ORDER BY relationship_type, source_entity_type, target_entity_type
                """,
                student_id=student_id,
            )
            relationship_rows = [dict(record) async for record in relationship_result if record]

            count_result = await session.run(
                """
                MATCH (s:Student {id: $student_id})
                OPTIONAL MATCH (s)-[:HAS_SECTION]->(sec:Section)
                OPTIONAL MATCH (sec)-[:HAS_ITEM]->(ent:Entity)
                OPTIONAL MATCH (s)-[:UPLOADED]->(d:Document)
                OPTIONAL MATCH (d)<-[:FROM_DOCUMENT]-(c:Chunk)
                RETURN count(DISTINCT sec) AS section_count,
                       count(DISTINCT ent) AS entity_count,
                       count(DISTINCT d) AS document_count,
                       count(DISTINCT c) AS chunk_count
                """,
                student_id=student_id,
            )
            counts_record = await count_result.single()

        entity_manifest = self._build_entity_manifest(entities)
        relationship_manifest = self._build_relationship_manifest(relationship_rows)
        student_manifest = self._build_student_manifest(student_props)
        schema = {
            "student": student_manifest,
            "sections": [
                {
                    "key": str(section.get("key") or "").strip(),
                    "description": str(section.get("description") or "").strip(),
                    "parent_key": str(section.get("parent_key") or "").strip(),
                }
                for section in sections
                if isinstance(section, dict) and str(section.get("key") or "").strip()
            ],
            "entity_manifest": entity_manifest,
            "relationship_manifest": relationship_manifest,
            "graph_counts": {
                "sections": int((counts_record or {}).get("section_count", 0) or 0),
                "entities": int((counts_record or {}).get("entity_count", 0) or 0),
                "documents": int((counts_record or {}).get("document_count", 0) or 0),
                "chunks": int((counts_record or {}).get("chunk_count", 0) or 0),
            },
        }
        return sanitize_neo4j_value(schema)

    async def list_entity_types(self, *, student_id: str) -> dict[str, Any]:
        """Which entity types exist in this student's graph, with per-type counts."""
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (:Student {id: $student_id})-[:HAS_SECTION]->(:Section)-[:HAS_ITEM]->(ent:Entity)
                RETURN ent.entity_type AS entity_type, count(ent) AS entity_count
                ORDER BY entity_type
                """,
                student_id=student_id,
            )
            entity_counts: dict[str, int] = {}
            async for record in result:
                entity_type = str(record.get("entity_type") or "Entity").strip()
                if not entity_type:
                    continue
                entity_counts[entity_type] = int(record.get("entity_count", 0) or 0)
        return sanitize_neo4j_value({
            "entity_types": sorted(entity_counts.keys()),
            "entity_counts": entity_counts,
        })

    async def list_relationship_types(self, *, student_id: str) -> dict[str, Any]:
        """Which relationships exist + for each, the (src → dst) type patterns.

        Useful for the LLM when planning multi-hop traversals: it can
        check "do any `WORKED_AT` edges go from `Person` to `Company`
        on this graph?" before attempting one.
        """
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (:Student {id: $student_id})-[:HAS_SECTION]->(:Section)-[:HAS_ITEM]->(src:Entity)-[r]->(dst:Entity)
                WHERE src.student_id = $student_id AND dst.student_id = $student_id
                RETURN
                    type(r) AS relationship_type,
                    coalesce(src.entity_type, 'Entity') AS source_entity_type,
                    coalesce(dst.entity_type, 'Entity') AS target_entity_type,
                    count(r) AS relationship_count
                ORDER BY relationship_type, source_entity_type, target_entity_type
                """,
                student_id=student_id,
            )
            relationship_counts: dict[str, int] = {}
            patterns: list[dict[str, Any]] = []
            async for record in result:
                relationship_type = str(record.get("relationship_type") or "").strip()
                if not relationship_type:
                    continue
                source_entity_type = str(record.get("source_entity_type") or "Entity").strip() or "Entity"
                target_entity_type = str(record.get("target_entity_type") or "Entity").strip() or "Entity"
                relationship_count = int(record.get("relationship_count", 0) or 0)
                relationship_counts[relationship_type] = relationship_counts.get(relationship_type, 0) + relationship_count
                patterns.append(
                    {
                        "relationship_type": relationship_type,
                        "source_entity_type": source_entity_type,
                        "target_entity_type": target_entity_type,
                        "relationship_count": relationship_count,
                    }
                )
        return sanitize_neo4j_value(
            {
                "relationship_types": sorted(relationship_counts.keys()),
                "relationship_counts": relationship_counts,
                "patterns": patterns,
            }
        )

    async def typed_node_lookup(
        self,
        *,
        student_id: str,
        entity_type: str,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List entities of a given type, with optional exact-match filters.

        Think of it as "SELECT * FROM Skill WHERE name='python'" but
        over the graph. `limit` is capped at 50 server-side so the
        LLM can't accidentally pull the whole graph.
        """
        safe_entity_type = self._safe_identifier(entity_type, "entity_type")
        filters = filters or {}
        where_parts: list[str] = ["ent.student_id = $student_id"]
        params: dict[str, Any] = {"student_id": student_id, "limit": max(1, min(int(limit or 20), 50))}
        for idx, (field, value) in enumerate(filters.items()):
            safe_field = self._safe_identifier(field, "filter field")
            param_name = f"filter_{idx}"
            where_parts.append(f"toString(ent.{safe_field}) = ${param_name}")
            params[param_name] = str(value or "")

        query = f"""
            MATCH (:Student {{id: $student_id}})-[:HAS_SECTION]->(sec:Section)-[:HAS_ITEM]->(ent:Entity:{safe_entity_type})
            WHERE {" AND ".join(where_parts)}
            RETURN ent {{.*, section_key: sec.key}} AS node
            ORDER BY coalesce(ent.updated_at, ent.created_at) DESC
            LIMIT $limit
        """
        async with self.driver.session() as session:
            result = await session.run(query, params)
            rows = [dict(record["node"]) async for record in result if record and record.get("node")]
        return sanitize_neo4j_value(rows)

    async def typed_relation_lookup(
        self,
        *,
        student_id: str,
        relationship_type: str,
        target_entity_type: str,
        target_filters: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Find all (src)-[rel]->(dst) edges where rel + dst type are pinned.

        Used when the LLM already knows the shape it wants (e.g. "all
        `WORKED_AT` edges pointing at `Company` nodes") and wants the
        matching endpoints back with their section context.
        """
        rel_type = self._safe_identifier(relationship_type, "relationship_type")
        target_type = self._safe_identifier(target_entity_type, "target_entity_type")
        target_filters = target_filters or {}

        where_parts: list[str] = ["dst.student_id = $student_id"]
        params: dict[str, Any] = {"student_id": student_id, "limit": max(1, min(int(limit or 20), 50))}
        for idx, (field, value) in enumerate(target_filters.items()):
            safe_field = self._safe_identifier(field, "target field")
            param_name = f"target_{idx}"
            where_parts.append(f"toString(dst.{safe_field}) = ${param_name}")
            params[param_name] = str(value or "")

        query = f"""
            MATCH (:Student {{id: $student_id}})-[:HAS_SECTION]->(src_sec:Section)-[:HAS_ITEM]->(src:Entity)-[r:{rel_type}]->(dst:Entity:{target_type})
            OPTIONAL MATCH (:Student {{id: $student_id}})-[:HAS_SECTION]->(dst_sec:Section)-[:HAS_ITEM]->(dst)
            WHERE {" AND ".join(where_parts)}
            RETURN {{
                relationship_type: type(r),
                source: src {{.*}},
                source_section_key: src_sec.key,
                target: dst {{.*}},
                target_section_key: dst_sec.key,
                relationship: properties(r)
            }} AS relation
            LIMIT $limit
        """
        async with self.driver.session() as session:
            result = await session.run(query, params)
            rows = [dict(record["relation"]) async for record in result if record and record.get("relation")]
        return sanitize_neo4j_value(rows)

    async def fetch_node_by_id(
        self,
        *,
        student_id: str,
        entity_type: str,
        node_id: str,
    ) -> dict[str, Any]:
        """Find one entity by "whatever uniquely names it" (id / name / code / title).

        Gives the LLM a forgiving handle — it can pass whichever field
        reads best in natural language and we'll try them all.
        """
        safe_entity_type = self._safe_identifier(entity_type, "entity_type")
        lookup_value = str(node_id or "").strip()
        if not lookup_value:
            raise ValueError("node_id is required")

        async with self.driver.session() as session:
            result = await session.run(
                f"""
                MATCH (:Student {{id: $student_id}})-[:HAS_SECTION]->(sec:Section)-[:HAS_ITEM]->(n:Entity:{safe_entity_type})
                WHERE n.student_id = $student_id
                  AND (
                    toString(n.id) = $node_id OR
                    toString(n.name) = $node_id OR
                    toString(n.code) = $node_id OR
                    toString(n.key) = $node_id OR
                    toString(n.title) = $node_id
                  )
                RETURN n {{.*, section_key: sec.key}} AS node
                LIMIT 1
                """,
                student_id=student_id,
                node_id=lookup_value,
            )
            record = await result.single()
            if not record:
                raise ValueError("node not found")
            return sanitize_neo4j_value(dict(record["node"]))

    async def fetch_relation_detail(
        self,
        *,
        student_id: str,
        relationship_type: str,
        target_entity_type: str,
        target_field: str = "id",
        target_value: str,
    ) -> dict[str, Any]:
        """Drill into a single relation pinned by rel type + target field.

        Returns both endpoints plus the relation's own properties — the
        most detail we can give the LLM about one edge in the graph.
        """
        rel_type = self._safe_identifier(relationship_type, "relationship_type")
        target_type = self._safe_identifier(target_entity_type, "target_entity_type")
        safe_target_field = self._safe_identifier(target_field, "target_field")
        lookup_value = str(target_value or "").strip()
        if not lookup_value:
            raise ValueError("target_value is required")

        query = f"""
            MATCH (:Student {{id: $student_id}})-[:HAS_SECTION]->(src_sec:Section)-[:HAS_ITEM]->(src:Entity)-[r:{rel_type}]->(dst:Entity:{target_type})
            OPTIONAL MATCH (:Student {{id: $student_id}})-[:HAS_SECTION]->(dst_sec:Section)-[:HAS_ITEM]->(dst)
            WHERE dst.student_id = $student_id
              AND toString(dst.{safe_target_field}) = $target_value
            RETURN {{
                relationship_type: type(r),
                source: src {{.*}},
                source_section_key: src_sec.key,
                target: dst {{.*}},
                target_section_key: dst_sec.key,
                relationship: properties(r)
            }} AS relation
            LIMIT 1
        """
        async with self.driver.session() as session:
            result = await session.run(
                query,
                student_id=student_id,
                target_value=lookup_value,
            )
            record = await result.single()
            if not record:
                raise ValueError("relation not found")
            return sanitize_neo4j_value(dict(record["relation"]))
    
    async def upsert_entity_field(
        self,
        *,
        student_id: str,
        entity_type: str,
        identity: dict[str, str],
        field_name: str,
        field_value: Any,
    ) -> dict:
        """Attach a richer "Field" record to an entity for nested / structured detail.

        Use this when a property is too complex to be a flat scalar on
        the entity — e.g. a Course entity's "grading scheme" that itself
        has subfields. Fields can be further nested via
        `upsert_nested_field`.
        """
        safe_entity_type = self._safe_identifier(entity_type, "entity_type")
        safe_field_name = self._safe_field_key(field_name, "field_name")
        if not identity:
            raise ValueError("identity is required")
        owner_key = self._entity_owner_key(student_id, safe_entity_type, identity)
        where_parts: list[str] = ["ent.student_id = $student_id"]
        params: dict[str, Any] = {
            "student_id": student_id,
            "field_name": safe_field_name,
            "field_value": field_value,
            "owner_id": owner_key,
            "field_id": generate_field_id(),
            "field_value_json": json.dumps(field_value, ensure_ascii=True, default=str),
            "field_display_name": self._display_name("Field", key=safe_field_name),
        }
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
                MERGE (ent)-[:HAS_FIELD]->(f:Field {{owner_id: $owner_id, key: $field_name}})
                ON CREATE SET f.id = $field_id, f.created_at = datetime()
                SET f.updated_at = datetime(),
                    f.value = $field_value,
                    f.value_json = $field_value_json,
                    f.display_name = $field_display_name
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
        identity: dict[str, str],
    ) -> list[dict]:
        """Every `Field` hanging directly off one entity (one level deep)."""
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
        """Attach a child field under an existing field (up to 6 levels deep).

        Supports structured nested data like "awards -> specific award
        -> criteria -> sub-criteria" without exploding the entity
        property map.
        """
        safe_field_name = self._safe_field_key(field_name, "field_name")
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (s:Student {id: $student_id})-[:HAS_SECTION]->(:Section)-[:HAS_ITEM]->(:Entity)-[:HAS_FIELD*1..6]->(parent:Field {id: $parent_field_id})
                MERGE (parent)-[:HAS_FIELD]->(child:Field {owner_id: $parent_field_id, key: $field_name})
                ON CREATE SET child.id = $field_id, child.created_at = datetime()
                SET child.updated_at = datetime(),
                    child.value = $field_value,
                    child.value_json = $field_value_json,
                    child.display_name = $field_display_name
                RETURN child {.*} AS field
                LIMIT 1
                """,
                student_id=student_id,
                parent_field_id=parent_field_id,
                field_name=safe_field_name,
                field_id=generate_field_id(),
                field_value=field_value,
                field_value_json=json.dumps(field_value, ensure_ascii=True, default=str),
                field_display_name=self._display_name("Field", key=safe_field_name),
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
        identity: dict[str, str],
        chunk_id: str,
    ) -> dict:
        """Ground an entity in a specific chunk of source text.

        This is the bridge between "structured knowledge" (the entity)
        and "raw evidence" (the chunk). When the specialist later
        answers a question, response_validator walks these edges to
        produce citations that point back to the actual paragraph.
        """
        safe_entity_type = self._safe_identifier(entity_type, "entity_type")
        if not identity:
            raise ValueError("identity is required")
        where_parts: list[str] = ["ent.student_id = $student_id"]
        params: dict[str, Any] = {"student_id": student_id, "chunk_id": chunk_id}
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
        identity: dict[str, str],
        document_id: str,
    ) -> dict:
        """Ground an entity in a whole document (coarser than chunk-level linking).

        Use this when we know the document the entity came from but
        don't have a specific chunk to point at — e.g. the whole resume
        counts as the source of the employment history.
        """
        safe_entity_type = self._safe_identifier(entity_type, "entity_type")
        if not identity:
            raise ValueError("identity is required")
        where_parts: list[str] = ["ent.student_id = $student_id"]
        params: dict[str, Any] = {"student_id": student_id, "document_id": document_id}
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
        """Inverse of `link_entity_to_chunk` — every entity grounded in this chunk.

        Used when the specialist has a relevant chunk (usually from
        vector search) and wants to pivot to the structured entities
        that piece of text supports.
        """
        async with self.driver.session() as session:
            result = await session.run("""
                MATCH (s:Student {id: $student_id})-[:HAS_SECTION]->(:Section)-[:HAS_ITEM]->(ent:Entity)-[:MENTIONED_IN]->(c:Chunk {id: $chunk_id})
                RETURN ent {.*} AS entity
            """, student_id=student_id, chunk_id=chunk_id)
            rows = [dict(record["entity"]) async for record in result]
            return sanitize_neo4j_value(rows)

    async def bfs_neighbors(self, *, student_id: str, start_node_id: str, max_depth: int = 1) -> list[dict]:
        """Breadth-first walk from a starting node, grouped by hop distance.

        Capped at depth 5 so the model can't trip into a whole-graph
        traversal. Results are returned as "level 1 = ..., level 2 =
        ..." which is easier for the LLM to reason about than a flat
        edge list.
        """
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
        """One-shot "give me everything" export of a student's graph.

        Pulls the root node, all sections, and every entity along with
        its fields, grounding chunks, and source documents. Powers the
        profile page and the replay viewer. Expensive — don't call it
        from the tool-calling loop.
        """
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

    async def get_graph_data(self, *, student_id: str) -> dict[str, Any]:
        """Flatten the student graph into a `nodes` + `relationships` payload.

        This is the shape the frontend graph visualization expects —
        one list of nodes with stable ids and one list of typed edges.
        Everything is derived from `get_full_student` plus one extra
        query to pick up entity→entity relationships.
        """
        student_graph = await self.get_full_student(student_id=student_id)
        student = student_graph.get("student", {})
        sections = student_graph.get("sections", [])
        entities = student_graph.get("entities", [])
        nodes: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []
        entity_node_ids: dict[tuple[str, str], str] = {}
        document_nodes: dict[str, dict[str, Any]] = {}
        chunk_nodes: dict[str, dict[str, Any]] = {}
        seen_relationships: set[tuple[str, str, str]] = set()
        root_student_id = str(student.get("id") or student_id or "")

        # Student root is always node 0 — everything hangs off it.
        if isinstance(student, dict) and student:
            nodes.append({"id": root_student_id, "labels": ["Student"], **student})
        # Sections get synthetic ids so the frontend can draw edges
        # without Neo4j internal ids leaking.
        for section in sections:
            if not isinstance(section, dict):
                continue
            section_owner_id = str(section.get("student_id") or student.get("id") or student_id)
            section_key = str(section.get("key") or "")
            if not section_key:
                continue
            section_id = f"section:{section_owner_id}:{section_key}"
            nodes.append({"id": section_id, "labels": ["Section"], **section})
            if root_student_id:
                relationships.append({"source": root_student_id, "target": section_id, "type": "HAS_SECTION"})
        # Emit one node per entity plus its HAS_ITEM/DERIVED_FROM/
        # MENTIONED_IN edges; documents/chunks are deduped via dicts
        # so an entity mentioned in multiple chunks doesn't create
        # phantom duplicate document nodes.
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            entity_id = self._graph_entity_id(entity)
            entity_key = self._result_entity_key(entity) or entity_id
            entity_node_ids[(str(entity.get("entity_type") or "Entity"), entity_key)] = entity_id
            nodes.append({"id": entity_id, "labels": ["Entity", str(entity.get("entity_type") or "Entity")], **entity})
            entity_section_key = str(entity.get("section_key") or "")
            if entity_section_key:
                section_id = f"section:{root_student_id or student_id}:{entity_section_key}"
                relationships.append({"source": section_id, "target": entity_id, "type": "HAS_ITEM"})
            for document in entity.get("documents", []) if isinstance(entity.get("documents"), list) else []:
                if not isinstance(document, dict) or not document.get("id"):
                    continue
                document_id = f"document:{document['id']}"
                document_nodes[document_id] = {**document, "id": document_id, "labels": ["Document"]}
                rel_key = (entity_id, document_id, "DERIVED_FROM")
                if rel_key not in seen_relationships:
                    relationships.append({"source": entity_id, "target": document_id, "type": "DERIVED_FROM"})
                    seen_relationships.add(rel_key)
            for chunk in entity.get("chunks", []) if isinstance(entity.get("chunks"), list) else []:
                if not isinstance(chunk, dict) or not chunk.get("id"):
                    continue
                chunk_id = f"chunk:{chunk['id']}"
                chunk_nodes[chunk_id] = {**chunk, "id": chunk_id, "labels": ["Chunk"]}
                rel_key = (entity_id, chunk_id, "MENTIONED_IN")
                if rel_key not in seen_relationships:
                    relationships.append({"source": entity_id, "target": chunk_id, "type": "MENTIONED_IN"})
                    seen_relationships.add(rel_key)

        nodes.extend(document_nodes.values())
        nodes.extend(chunk_nodes.values())

        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (:Student {id: $student_id})-[:HAS_SECTION]->(:Section)-[:HAS_ITEM]->(src:Entity)-[r]->(dst:Entity)
                WHERE src.student_id = $student_id AND dst.student_id = $student_id
                RETURN
                    properties(src) AS source,
                    properties(dst) AS target,
                    type(r) AS relationship_type,
                    properties(r) AS relationship
                ORDER BY relationship_type
                """,
                student_id=student_id,
            )
            async for record in result:
                source = dict(record["source"] or {})
                target = dict(record["target"] or {})
                source_id = entity_node_ids.get(
                    (str(source.get("entity_type") or "Entity"), self._result_entity_key(source) or self._graph_entity_id(source))
                )
                target_id = entity_node_ids.get(
                    (str(target.get("entity_type") or "Entity"), self._result_entity_key(target) or self._graph_entity_id(target))
                )
                relationship_type = str(record["relationship_type"] or "").strip()
                if not source_id or not target_id or not relationship_type:
                    continue
                rel_key = (source_id, target_id, relationship_type)
                if rel_key in seen_relationships:
                    continue
                relationships.append(
                    {
                        "source": source_id,
                        "target": target_id,
                        "type": relationship_type,
                        "properties": dict(record["relationship"] or {}),
                    }
                )
                seen_relationships.add(rel_key)
        return sanitize_neo4j_value({"nodes": nodes, "relationships": relationships})

    async def hybrid_search(
        self,
        *,
        student_id: str,
        query: str,
        k: int = 5,
    ) -> list[dict[str, Any]]:
        """Vector search + graph grounding — the main retrieval tool.

        Pipeline:
        1. Vector search against this student's chunks to find the
           text most similar to `query`.
        2. For each hit, pull the parent Document + any entities
           grounded in it (directly via MENTIONED_IN, or via the
           document via DERIVED_FROM).
        3. Rank the grounded entities with `_hybrid_entity_rank` so
           only the most relevant few make it into the response (keeps
           the LLM transcript small).
        """
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
        # Map (chunk_id, document_id) -> grounded context so we can
        # merge it back onto each vector hit in one pass at the end.
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
                # Direct entities were grounded at the chunk level and
                # carry the most specific signal; document-level
                # entities are a weaker fallback.
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
                # Keep only the 5 best entities per chunk so the
                # combined LLM transcript stays manageable.
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

    async def reset_student_data(self, *, student_id: str) -> dict[str, Any]:
        """Nuke one student and everything within 3 hops of them.

        Backs the "Reset my data" admin action on the profile page.
        Three hops is enough to remove sections → entities → fields /
        documents / chunks without accidentally wandering into a
        shared node (we don't actually share nodes, but the bound
        keeps a buggy graph from cascading too far).
        """
        async with self.driver.session() as session:
            await session.run(
                """
                MATCH (s:Student {id: $student_id})
                OPTIONAL MATCH (s)-[*0..3]-(n)
                DETACH DELETE s, n
                """,
                student_id=student_id,
            )
        return sanitize_neo4j_value({"status": "success", "student_id": student_id})

    async def reset_all_data(self) -> dict[str, Any]:
        """Destroy the entire graph — admin / dev reset only.

        Wired to the `DELETE /students` endpoint behind a confirmation.
        Does NOT touch the SQLite checkpointer or on-disk replay
        artifacts; callers clear those separately.
        """
        async with self.driver.session() as session:
            await session.run("MATCH (n) DETACH DELETE n")
        return sanitize_neo4j_value({"status": "success"})

    def _entity_owner_key(self, student_id: str, entity_type: str, identity: dict[str, str]) -> str:
        """Stable string used as `Field.owner_id` so fields know their parent entity.

        Combines student + entity type + a sorted JSON of the identity
        dict so the same logical entity always produces the same key
        regardless of dict insertion order.
        """
        normalized_identity = json.dumps(identity, sort_keys=True, ensure_ascii=True)
        return f"{student_id}:{entity_type}:{normalized_identity}"

    def _build_student_manifest(self, student_props: dict[str, Any]) -> dict[str, Any]:
        """Compact manifest of the root Student node's scalar properties.

        Exposes current property keys and their values (truncated) so the
        ingestion agent can reuse the same keys across documents instead of
        inventing parallel near-duplicate property names.
        """
        if not isinstance(student_props, dict):
            return {"property_keys": [], "properties": {}}
        exposed: dict[str, Any] = {}
        for key, value in student_props.items():
            key_str = str(key or "").strip()
            if not key_str or key_str in _SCHEMA_METADATA_KEYS or key_str == "id":
                continue
            if isinstance(value, (dict, list)):
                continue
            if value is None or value == "":
                continue
            value_str = str(value)
            if len(value_str) > 160:
                value_str = value_str[:157] + "..."
            exposed[key_str] = value_str
        return {
            "property_keys": sorted(exposed.keys()),
            "properties": exposed,
        }

    def _build_entity_manifest(self, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Roll up a list of entities into a per-type summary.

        The ingestion prompt uses this to answer "what entity types
        already exist and what property names do they use?" without
        dumping every node into the LLM context. Each bucket carries
        a count, the identity/property keys seen, and up to a handful
        of sample identities so the model can match formatting.
        """
        grouped: dict[str, dict[str, Any]] = {}
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            entity_type = str(entity.get("entity_type") or "Entity").strip() or "Entity"
            bucket = grouped.setdefault(
                entity_type,
                {
                    "entity_type": entity_type,
                    "count": 0,
                    "identity_keys": set(),
                    "property_keys": set(),
                    "sample_identities": [],
                    "sample_identity_keys": set(),
                },
            )
            bucket["count"] += 1
            identity = self._schema_identity_payload(entity)
            property_keys = self._schema_property_keys(entity)
            if identity:
                bucket["identity_keys"].update(identity.keys())
                identity_signature = json.dumps(identity, sort_keys=True, ensure_ascii=True, default=str)
                if (
                    len(bucket["sample_identities"]) < _SCHEMA_SAMPLE_LIMIT
                    and identity_signature not in bucket["sample_identity_keys"]
                ):
                    bucket["sample_identities"].append(identity)
                    bucket["sample_identity_keys"].add(identity_signature)
            bucket["property_keys"].update(property_keys)

        manifest: list[dict[str, Any]] = []
        for entity_type in sorted(grouped.keys()):
            bucket = grouped[entity_type]
            manifest.append(
                {
                    "entity_type": entity_type,
                    "count": int(bucket["count"]),
                    "identity_keys": sorted(bucket["identity_keys"]),
                    "sample_identities": list(bucket["sample_identities"]),
                    "property_keys": sorted(bucket["property_keys"]),
                }
            )
        return manifest

    def _build_relationship_manifest(self, relationship_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Group raw (rel, src_type, dst_type, count) rows into per-type buckets.

        Complements `_build_entity_manifest` — tells the LLM which
        connections already exist in the graph so it can reuse them
        instead of inventing near-synonyms (WORKED_AT vs EMPLOYED_BY).
        """
        grouped: dict[str, dict[str, Any]] = {}
        for row in relationship_rows:
            relationship_type = str(row.get("relationship_type") or "").strip()
            if not relationship_type:
                continue
            bucket = grouped.setdefault(
                relationship_type,
                {
                    "relationship_type": relationship_type,
                    "count": 0,
                    "patterns": [],
                    "seen_patterns": set(),
                },
            )
            relationship_count = int(row.get("relationship_count", 0) or 0)
            bucket["count"] += relationship_count
            pattern = {
                "source_entity_type": str(row.get("source_entity_type") or "Entity").strip() or "Entity",
                "target_entity_type": str(row.get("target_entity_type") or "Entity").strip() or "Entity",
            }
            pattern_signature = json.dumps(pattern, sort_keys=True, ensure_ascii=True)
            if pattern_signature not in bucket["seen_patterns"]:
                bucket["patterns"].append(pattern)
                bucket["seen_patterns"].add(pattern_signature)

        manifest: list[dict[str, Any]] = []
        for relationship_type in sorted(grouped.keys()):
            bucket = grouped[relationship_type]
            manifest.append(
                {
                    "relationship_type": relationship_type,
                    "count": int(bucket["count"]),
                    "patterns": list(bucket["patterns"]),
                }
            )
        return manifest

    def _schema_identity_payload(self, entity: dict[str, Any]) -> dict[str, Any]:
        """Pull only the scalar identity-field values off an entity.

        The entity node carries a mix of identity fields, property
        fields, and internal metadata — this extracts just the
        "what makes this entity unique" scalar subset for the schema
        manifest.
        """
        payload: dict[str, Any] = {}
        raw_identity_keys = entity.get("identity_keys")
        if isinstance(raw_identity_keys, (list, tuple, set)):
            identity_keys = [
                str(key or "").strip()
                for key in raw_identity_keys
                if str(key or "").strip()
            ]
        elif raw_identity_keys not in (None, "", [], {}):
            identity_keys = [str(raw_identity_keys).strip()]
        else:
            identity_keys = []
        for key in identity_keys:
            if key in _SCHEMA_METADATA_KEYS or key == "entity_type":
                continue
            value = entity.get(key)
            if value in (None, "", [], {}):
                continue
            if isinstance(value, (str, int, float, bool)):
                payload[key] = value
        return payload

    def _schema_property_keys(self, entity: dict[str, Any]) -> list[str]:
        """Names of scalar / simple-list properties an entity actually uses.

        Internal fields (timestamps, student_id, identity_keys, ...)
        are filtered out so the manifest only advertises user-facing
        property names.
        """
        keys: list[str] = []
        for key in sorted(entity.keys()):
            if key in _SCHEMA_METADATA_KEYS or key == "entity_type":
                continue
            value = entity.get(key)
            if value in (None, "", [], {}):
                continue
            if isinstance(value, (str, int, float, bool)):
                keys.append(key)
                continue
            if isinstance(value, list) and all(isinstance(item, (str, int, float, bool)) for item in value):
                keys.append(key)
        return keys

    def _result_entity_key(self, entity: dict[str, Any]) -> str:
        """Deterministic key used to dedupe entities across hybrid-search rows.

        Same (type + identity) always maps to the same string so the
        enrichment loop doesn't double-count a single entity that
        shows up grounded in multiple chunks.
        """
        identity_payload = self._schema_identity_payload(entity)
        if identity_payload:
            identity_json = json.dumps(identity_payload, sort_keys=True, ensure_ascii=True, default=str)
            return f"{str(entity.get('entity_type') or 'Entity')}:{identity_json}"
        for key in ("id", "name", "code", "title", "value"):
            value = str(entity.get(key, "") or "").strip()
            if value:
                return f"{entity.get('entity_type', '')}:{key}:{value}"
        return ""

    def _graph_entity_id(self, entity: dict[str, Any]) -> str:
        """Stable frontend node id for the graph visualization.

        Prefers an explicit `id` field when present; otherwise builds
        one from the type plus a short hash of the identity payload
        so the UI always has a deterministic node id to work with.
        """
        entity_type = str(entity.get("entity_type") or "Entity").strip() or "Entity"
        explicit_id = str(entity.get("id", "") or "").strip()
        if explicit_id:
            return f"entity:{entity_type}:id:{explicit_id}"

        identity_payload = self._graph_identity_payload(entity)
        identity_json = json.dumps(identity_payload, sort_keys=True, ensure_ascii=True, default=str)
        identity_hash = hashlib.sha1(identity_json.encode("utf-8")).hexdigest()[:12]
        if identity_payload:
            preview = ",".join(list(identity_payload.keys())[:2])
            return f"entity:{entity_type}:{preview}:{identity_hash}"
        return f"entity:{entity_type}:{identity_hash}"

    def _graph_identity_payload(self, entity: dict[str, Any]) -> dict[str, Any]:
        """Scalar properties that go into the synthetic graph id hash.

        Looser than the schema identity payload — it includes any
        stable scalar property, not just declared identity fields —
        because the visualization just needs a consistent id, not
        a domain-meaningful one.
        """
        payload: dict[str, Any] = {}
        for key in sorted(entity.keys()):
            if key in _GRAPH_METADATA_KEYS or key == "entity_type":
                continue
            value = entity.get(key)
            if value in (None, "", [], {}):
                continue
            if isinstance(value, (str, int, float, bool)):
                payload[key] = value
                continue
            if isinstance(value, list) and all(isinstance(item, (str, int, float, bool)) for item in value):
                payload[key] = value
        return payload

    def _chunk_payload(self, chunk: dict[str, Any]) -> dict[str, Any]:
        """Expand a raw Chunk record's `metadata_json` into a usable `metadata` dict.

        Mirrors `VectorDB._chunk_payload` so both classes emit the
        same chunk shape — callers never have to know which adapter
        produced the row.
        """
        payload = dict(chunk or {})
        metadata = self._metadata_dict(payload.get("metadata_json"))
        payload["metadata"] = metadata
        payload.pop("metadata_json", None)
        return payload

    def _metadata_dict(self, raw_metadata: Any) -> dict[str, Any]:
        """Forgiving JSON-string → dict parser for chunk metadata.

        Malformed JSON degrades to `{}` rather than breaking a read.
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

    def _hybrid_entity_rank(
        self,
        *,
        query: str,
        chunk_text: str,
        entity: dict[str, Any],
        section: dict[str, Any],
        provenance: str,
    ) -> tuple[int, int, int, int]:
        """Cheap heuristic score for "is this entity relevant to the query?".

        Uses token overlap between the query, the chunk, the entity's
        human-readable fields, and its section — plus a bonus for
        chunk-level grounding (MENTIONED_IN > DERIVED_FROM). Returns
        a tuple so Python's lexicographic sort gives us stable
        multi-key ranking without floating-point fiddling.
        """
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
        # Weight chunk-level grounding above document-level grounding
        # so direct evidence outranks transitive evidence.
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
        """Lowercased word-token set used by the ranking heuristic.

        Punctuation / whitespace only — no stemming, no stopwords.
        The comparison is already fuzzy since we're just measuring
        overlap, and keeping it simple keeps it fast.
        """
        return {
            token.lower()
            for token in re.findall(r"[A-Za-z0-9_]+", str(value or ""))
            if token
        }
