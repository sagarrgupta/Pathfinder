"""Graph MCP tools """

from __future__ import annotations
from typing import Any
from typing import Optional
from app.adapters.neo4j.graphDB import GraphDB
from app.tools.tools import ToolContext, ToolSpec
from app.config.settings import settings
from neo4j import AsyncGraphDatabase, AsyncDriver
import logging
log = logging.getLogger("pathfinder.neo4j.graph")

_driver: Optional[AsyncDriver] = None

JSON_VALUE_SCHEMA: dict[str, Any] = {
    "anyOf": [
        {"type": "string"},
        {"type": "number"},
        {"type": "integer"},
        {"type": "boolean"},
        {"type": "object"},
        {"type": "array"},
        {"type": "null"},
    ]
}

IDENTITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Stable identity fields that uniquely identify an entity inside a student graph, such as {'key': 'value'}.",
    "additionalProperties": {"type": "string"},
}

PROPERTIES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Flexible JSON properties to store on the entity or relationship. Use this for summary attributes, not for nested field trees.",
    "additionalProperties": JSON_VALUE_SCHEMA,
}

async def get_driver() -> AsyncDriver:
    """Return (or create) the singleton Neo4j async driver."""
    global _driver
    if _driver is None:
        if not str(settings.NEO4J_PASSWORD or "").strip():
            raise RuntimeError(
                "NEO4J_PASSWORD is not configured. Set Neo4j credentials before starting Pathfinder."
            )
        _driver = AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )
        log.info("Neo4j driver created: %s", settings.NEO4J_URI)
    return _driver


async def close_driver() -> None:
    """Close the Neo4j driver on shutdown."""
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None
        log.info("Neo4j driver closed")


async def _graph_db(context: ToolContext) -> GraphDB:
    driver = getattr(context, "driver", None) or await get_driver()
    return GraphDB(driver)


def _student_id(context: ToolContext) -> str:
    return str(context.student_id or "").strip()


async def _upsert_section(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    graph_db = await _graph_db(context)
    section = await graph_db.upsert_section(
        student_id=_student_id(context),
        key=str(arguments.get("key", "") or "").strip(),
        description=str(arguments.get("description", "") or "").strip(),
        parent_key=str(arguments.get("parent_key", "") or "").strip(),
    )
    return {"section": section}


async def _update_student(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    graph_db = await _graph_db(context)
    student = await graph_db.update_student(
        student_id=_student_id(context),
        updates=dict(arguments.get("updates") or {}),
    )
    return {"student": student}


async def _upsert_graph_node(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    graph_db = await _graph_db(context)
    node = await graph_db.upsert_graph_node(
        student_id=_student_id(context),
        entity_type=str(arguments.get("entity_type", "") or "").strip(),
        section_key=str(arguments.get("section_key", "") or "").strip(),
        identity=dict(arguments.get("identity") or {}),
        properties=dict(arguments.get("properties") or {}),
    )
    return {"node": node}


async def _upsert_graph_relation(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    graph_db = await _graph_db(context)
    relation = await graph_db.upsert_graph_relation(
        student_id=_student_id(context),
        source_entity_type=str(arguments.get("source_entity_type", "") or "").strip(),
        source_identity=dict(arguments.get("source_identity") or {}),
        target_entity_type=str(arguments.get("target_entity_type", "") or "").strip(),
        target_identity=dict(arguments.get("target_identity") or {}),
        relationship_type=str(arguments.get("relationship_type", "") or "").strip(),
        properties=dict(arguments.get("properties") or {}),
    )
    return {"relation": relation}


async def _get_student_sections(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    graph_db = await _graph_db(context)
    sections = await graph_db.get_student_sections(student_id=_student_id(context))
    return {"sections": sections}


async def _get_section_entities(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    graph_db = await _graph_db(context)
    entities = await graph_db.get_section_entities(
        student_id=_student_id(context),
        section_key=str(arguments.get("section_key", "") or "").strip(),
    )
    return {"entities": entities}


async def _get_entity_by_identity(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    graph_db = await _graph_db(context)
    entity = await graph_db.get_entity_by_identity(
        student_id=_student_id(context),
        entity_type=str(arguments.get("entity_type", "") or "").strip(),
        identity=dict(arguments.get("identity") or {}),
    )
    return {"entity": entity}


async def _upsert_entity_field(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    graph_db = await _graph_db(context)
    field = await graph_db.upsert_entity_field(
        student_id=_student_id(context),
        entity_type=str(arguments.get("entity_type", "") or "").strip(),
        identity=dict(arguments.get("identity") or {}),
        field_name=str(arguments.get("field_name", "") or "").strip(),
        field_value=arguments.get("field_value"),
    )
    return {"field": field}


async def _list_entity_fields(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    graph_db = await _graph_db(context)
    fields = await graph_db.list_entity_fields(
        student_id=_student_id(context),
        entity_type=str(arguments.get("entity_type", "") or "").strip(),
        identity=dict(arguments.get("identity") or {}),
    )
    return {"fields": fields}


async def _upsert_nested_field(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    graph_db = await _graph_db(context)
    field = await graph_db.upsert_nested_field(
        student_id=_student_id(context),
        parent_field_id=str(arguments.get("parent_field_id", "") or "").strip(),
        field_name=str(arguments.get("field_name", "") or "").strip(),
        field_value=arguments.get("field_value"),
    )
    return {"field": field}


async def _link_entity_to_chunk(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    graph_db = await _graph_db(context)
    entity = await graph_db.link_entity_to_chunk(
        student_id=_student_id(context),
        entity_type=str(arguments.get("entity_type", "") or "").strip(),
        identity=dict(arguments.get("identity") or {}),
        chunk_id=str(arguments.get("chunk_id", "") or "").strip(),
    )
    return {"entity": entity}


async def _link_entity_to_document(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    graph_db = await _graph_db(context)
    entity = await graph_db.link_entity_to_document(
        student_id=_student_id(context),
        entity_type=str(arguments.get("entity_type", "") or "").strip(),
        identity=dict(arguments.get("identity") or {}),
        document_id=str(arguments.get("document_id", "") or "").strip(),
    )
    return {"entity": entity}


async def _get_chunk_entities(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    graph_db = await _graph_db(context)
    entities = await graph_db.get_chunk_entities(
        student_id=_student_id(context),
        chunk_id=str(arguments.get("chunk_id", "") or "").strip(),
    )
    return {"entities": entities}


async def _bfs_neighbors(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    graph_db = await _graph_db(context)
    traversal = await graph_db.bfs_neighbors(
        student_id=_student_id(context),
        start_node_id=str(arguments.get("start_node_id", "") or "").strip(),
        max_depth=int(arguments.get("max_depth", 1) or 1),
    )
    return {"traversal": traversal}


async def _get_full_student(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    graph_db = await _graph_db(context)
    student_graph = await graph_db.get_full_student(student_id=_student_id(context))
    return {"student_graph": student_graph}


async def _get_graph_data(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    graph_db = await _graph_db(context)
    graph_data = await graph_db.get_graph_data(student_id=_student_id(context))
    return {"graph_data": graph_data}


async def _get_student_summary(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    graph_db = await _graph_db(context)
    summary = await graph_db.get_student_summary(student_id=_student_id(context))
    return {"student_summary": summary}


async def _get_student_schema(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    graph_db = await _graph_db(context)
    schema = await graph_db.get_student_schema(student_id=_student_id(context))
    return {"student_schema": schema}


async def _list_entity_types(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    graph_db = await _graph_db(context)
    entity_types = await graph_db.list_entity_types(student_id=_student_id(context))
    return entity_types


async def _list_relationship_types(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    graph_db = await _graph_db(context)
    relationship_types = await graph_db.list_relationship_types(student_id=_student_id(context))
    return relationship_types


async def _typed_node_lookup(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    graph_db = await _graph_db(context)
    results = await graph_db.typed_node_lookup(
        student_id=_student_id(context),
        entity_type=str(arguments.get("entity_type", "") or "").strip(),
        filters=dict(arguments.get("filters") or {}),
        limit=int(arguments.get("limit", 20) or 20),
    )
    return {"results": results}


async def _typed_relation_lookup(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    graph_db = await _graph_db(context)
    results = await graph_db.typed_relation_lookup(
        student_id=_student_id(context),
        relationship_type=str(arguments.get("relationship_type", "") or "").strip(),
        target_entity_type=str(arguments.get("target_entity_type", "") or "").strip(),
        target_filters=dict(arguments.get("target_filters") or {}),
        limit=int(arguments.get("limit", 20) or 20),
    )
    return {"results": results}


async def _fetch_node_by_id(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    graph_db = await _graph_db(context)
    node = await graph_db.fetch_node_by_id(
        student_id=_student_id(context),
        entity_type=str(arguments.get("entity_type", "") or "").strip(),
        node_id=str(arguments.get("node_id", "") or "").strip(),
    )
    return {"node": node}


async def _fetch_relation_detail(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    graph_db = await _graph_db(context)
    relation = await graph_db.fetch_relation_detail(
        student_id=_student_id(context),
        relationship_type=str(arguments.get("relationship_type", "") or "").strip(),
        target_entity_type=str(arguments.get("target_entity_type", "") or "").strip(),
        target_field=str(arguments.get("target_field", "id") or "id").strip(),
        target_value=str(arguments.get("target_value", "") or "").strip(),
    )
    return {"relation": relation}


async def _hybrid_search(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    graph_db = await _graph_db(context)
    results = await graph_db.hybrid_search(
        student_id=_student_id(context),
        query=str(arguments.get("query", "") or "").strip(),
        k=int(arguments.get("k", 5) or 5),
    )
    return {"results": results}


def get_graph_tool_specs() -> list[ToolSpec]:
    """Graph tool definitions exposed to the ingestion/runtime LLM."""
    return [
        ToolSpec(
            name="update_student",
            description="Create the root student node if needed and update scalar student properties in one step. Use this for student-level attributes such as name, summaries, preferences, or other root properties that belong directly on the student node rather than in a section entity.",
            input_schema={
                "type": "object",
                "properties": {
                    "updates": {
                        "type": "object",
                        "description": "Scalar student properties to create or update on the root student node.",
                        "additionalProperties": JSON_VALUE_SCHEMA,
                    },
                },
                "required": ["updates"],
                "additionalProperties": False,
            },
            handler=_update_student,
        ),
        ToolSpec(
            name="upsert_section",
            description="Create or update one student-owned section that groups related entities. Use this to organize graph content under a stable section key and to reuse an existing section when new evidence belongs to the same part of the student graph.",
            input_schema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Stable section key that identifies the grouping this entity set belongs to.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional plain-language description of the section's purpose or the kind of information it groups.",
                    },
                    "parent_key": {
                        "type": "string",
                        "description": "Optional parent section key if this section should be nested under another existing section.",
                    },
                },
                "required": ["key"],
                "additionalProperties": False,
            },
            handler=_upsert_section,
        ),
        ToolSpec(
            name="upsert_graph_node",
            description="Create or update one dynamic entity under a student-owned section. Use this to store the main concept as `(:Entity:<DynamicType>)`, keep stable identity fields on the entity itself, and attach the entity to the section that should own it.",
            input_schema={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "description": "Dynamic entity label that describes the kind of concept being stored.",
                    },
                    "section_key": {
                        "type": "string",
                        "description": "Section key that should own this entity.",
                    },
                    "identity": IDENTITY_SCHEMA,
                    "properties": PROPERTIES_SCHEMA,
                },
                "required": ["entity_type", "section_key", "identity", "properties"],
                "additionalProperties": False,
            },
            handler=_upsert_graph_node,
        ),
        ToolSpec(
            name="upsert_graph_relation",
            description="Create or update a typed relationship between two existing entities owned by the same student. Use this after both entities already exist and you need to connect them with an explicit semantic edge.",
            input_schema={
                "type": "object",
                "properties": {
                    "source_entity_type": {
                        "type": "string",
                        "description": "Dynamic entity type for the source entity.",
                    },
                    "source_identity": IDENTITY_SCHEMA,
                    "target_entity_type": {
                        "type": "string",
                        "description": "Dynamic entity type for the target entity.",
                    },
                    "target_identity": IDENTITY_SCHEMA,
                    "relationship_type": {
                        "type": "string",
                        "description": "Relationship type to create between the source and target entities.",
                    },
                    "properties": PROPERTIES_SCHEMA,
                },
                "required": [
                    "source_entity_type",
                    "source_identity",
                    "target_entity_type",
                    "target_identity",
                    "relationship_type",
                ],
                "additionalProperties": False,
            },
            handler=_upsert_graph_relation,
        ),
        ToolSpec(
            name="get_student_sections",
            description="Return all sections currently attached to the active student. Use this before creating a section so the model can reuse an existing section instead of duplicating graph structure.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            handler=_get_student_sections,
        ),
        ToolSpec(
            name="get_section_entities",
            description="Return every entity that currently belongs to one student section. Use this to inspect what already exists inside a section before deciding whether to update an existing entity or create a new one.",
            input_schema={
                "type": "object",
                "properties": {
                    "section_key": {
                        "type": "string",
                        "description": "Section key to inspect.",
                    },
                },
                "required": ["section_key"],
                "additionalProperties": False,
            },
            handler=_get_section_entities,
        ),
        ToolSpec(
            name="get_entity_by_identity",
            description="Look up one entity by its type and stable identity fields. Use this when new evidence appears and you need to decide whether the graph already contains the same concept.",
            input_schema={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "description": "Dynamic entity type to search for.",
                    },
                    "identity": IDENTITY_SCHEMA,
                },
                "required": ["entity_type", "identity"],
                "additionalProperties": False,
            },
            handler=_get_entity_by_identity,
        ),
        ToolSpec(
            name="upsert_entity_field",
            description="Create or update one first-level Field node under an existing entity. Use this for structured detail that should live outside the entity core, especially when the field may later expand into a deeper field tree.",
            input_schema={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "description": "Dynamic entity type that owns the field.",
                    },
                    "identity": IDENTITY_SCHEMA,
                    "field_name": {
                        "type": "string",
                        "description": "Field key to create or update under the entity. This can be a human-readable label from the document, such as a course title or section heading.",
                    },
                    "field_value": {
                        **JSON_VALUE_SCHEMA,
                        "description": "Optional field value. Leave it null when the field will act mainly as a container for child fields.",
                    },
                },
                "required": ["entity_type", "identity", "field_name"],
                "additionalProperties": False,
            },
            handler=_upsert_entity_field,
        ),
        ToolSpec(
            name="list_entity_fields",
            description="Return the first-level Field nodes currently attached to an entity. Use this before updating structured detail so the model can reuse an existing field or attach deeper nested fields under the right parent.",
            input_schema={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "description": "Dynamic entity type that owns the fields.",
                    },
                    "identity": IDENTITY_SCHEMA,
                },
                "required": ["entity_type", "identity"],
                "additionalProperties": False,
            },
            handler=_list_entity_fields,
        ),
        ToolSpec(
            name="upsert_nested_field",
            description="Create or update one child Field under an existing parent Field. Use this when a field needs deeper structure and should be expanded into nested field nodes instead of being flattened into one value.",
            input_schema={
                "type": "object",
                "properties": {
                    "parent_field_id": {
                        "type": "string",
                        "description": "Id of the existing parent Field node that should own the child field.",
                    },
                    "field_name": {
                        "type": "string",
                        "description": "Child field key to create below the parent field. This can be a human-readable label from the document, such as a course title or subsection heading.",
                    },
                    "field_value": {
                        **JSON_VALUE_SCHEMA,
                        "description": "Optional child field value. Leave null when the child field is also acting as a container.",
                    },
                },
                "required": ["parent_field_id", "field_name"],
                "additionalProperties": False,
            },
            handler=_upsert_nested_field,
        ),
        ToolSpec(
            name="link_entity_to_chunk",
            description="Ground one entity in a specific chunk of evidence by creating `(:Entity)-[:MENTIONED_IN]->(:Chunk)`. Use this whenever a chunk directly supports, states, or mentions the entity so hybrid retrieval can reconnect text evidence back to the graph.",
            input_schema={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "description": "Dynamic entity type to link.",
                    },
                    "identity": IDENTITY_SCHEMA,
                    "chunk_id": {
                        "type": "string",
                        "description": "Chunk id that directly mentions or supports the entity.",
                    },
                },
                "required": ["entity_type", "identity", "chunk_id"],
                "additionalProperties": False,
            },
            handler=_link_entity_to_chunk,
        ),
        ToolSpec(
            name="link_entity_to_document",
            description="Ground one entity at the document level by creating `(:Entity)-[:DERIVED_FROM]->(:Document)`. Use this for broader provenance when the entity is derived from the document as a whole rather than from one specific chunk.",
            input_schema={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "description": "Dynamic entity type to link.",
                    },
                    "identity": IDENTITY_SCHEMA,
                    "document_id": {
                        "type": "string",
                        "description": "Document id that the entity was derived from.",
                    },
                },
                "required": ["entity_type", "identity", "document_id"],
                "additionalProperties": False,
            },
            handler=_link_entity_to_document,
        ),
        ToolSpec(
            name="get_chunk_entities",
            description="Return entities explicitly connected to one chunk through `MENTIONED_IN`. Use this to inspect which graph concepts are already grounded in a specific chunk before adding more links or creating duplicate entities.",
            input_schema={
                "type": "object",
                "properties": {
                    "chunk_id": {
                        "type": "string",
                        "description": "Chunk id whose linked entities should be returned.",
                    },
                },
                "required": ["chunk_id"],
                "additionalProperties": False,
            },
            handler=_get_chunk_entities,
        ),
        ToolSpec(
            name="bfs_neighbors",
            description="Traverse outward from a starting graph node by depth and return level-by-level neighbors. Use this when the model needs local graph context around an existing node before deciding whether to reuse, update, or extend nearby structure.",
            input_schema={
                "type": "object",
                "properties": {
                    "start_node_id": {
                        "type": "string",
                        "description": "Graph node id to start traversal from.",
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum traversal depth to explore. Keep this small, usually between 1 and 3.",
                    },
                },
                "required": ["start_node_id"],
                "additionalProperties": False,
            },
            handler=_bfs_neighbors,
        ),
        ToolSpec(
            name="get_student_summary",
            description="Return a compact student graph summary for planning. Use this when the model needs a lightweight overview of the current student node, section keys, entity types, and graph counts before choosing more specific read or write tools.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            handler=_get_student_summary,
        ),
        ToolSpec(
            name="get_student_schema",
            description="Return the current student section schema as a lightweight structured object. Use this when the model only needs the section layout and should avoid fetching the entire student graph.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            handler=_get_student_schema,
        ),
        ToolSpec(
            name="list_entity_types",
            description="Return the entity types currently present in the student graph along with counts for each type. Use this when the model needs to know what kinds of graph entities already exist before deciding which type to read or update.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            handler=_list_entity_types,
        ),
        ToolSpec(
            name="get_full_student",
            description="Return the full student graph snapshot, including the root student node, all sections, all entities, field trees attached to those entities, and provenance links attached to each entity. Use this when a broad read of the current graph state is needed before making graph updates.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            handler=_get_full_student,
        ),
        ToolSpec(
            name="list_relationship_types",
            description="Return the relationship types currently present in the active student graph, along with counts and simple source-to-target entity patterns. Use this before `typed_relation_lookup` or `fetch_relation_detail` whenever you do not already know the exact relationship type names.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            handler=_list_relationship_types,
        ),
        ToolSpec(
            name="get_graph_data",
            description="Return a lightweight node-and-relationship graph view for visualization or structural inspection. Use this when the model needs the student graph as simple `nodes` and `relationships` arrays instead of the richer full student snapshot.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            handler=_get_graph_data,
        ),
        ToolSpec(
            name="typed_node_lookup",
            description="Return matching student-owned entities of one dynamic entity type using exact-match property filters. Use this when the model needs a list search within one entity type instead of one exact identity match.",
            input_schema={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "description": "Dynamic entity type to search within.",
                    },
                    "filters": {
                        "type": "object",
                        "description": "Optional exact-match filters to apply on entity properties.",
                        "additionalProperties": JSON_VALUE_SCHEMA,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of matching nodes to return.",
                    },
                },
                "required": ["entity_type"],
                "additionalProperties": False,
            },
            handler=_typed_node_lookup,
        ),
        ToolSpec(
            name="typed_relation_lookup",
            description="Return student-owned graph relationships of one specific type whose target matches one dynamic entity type. Use this when the model needs to inspect existing semantic edges before creating duplicate relationships or when it wants entities that are already connected in a particular way. If the exact relationship type is unknown, call `list_relationship_types` first instead of guessing.",
            input_schema={
                "type": "object",
                "properties": {
                    "relationship_type": {
                        "type": "string",
                        "description": "Relationship type to inspect.",
                    },
                    "target_entity_type": {
                        "type": "string",
                        "description": "Dynamic entity type expected on the target side of the relationship.",
                    },
                    "target_filters": {
                        "type": "object",
                        "description": "Optional exact-match filters to apply on target entity properties.",
                        "additionalProperties": JSON_VALUE_SCHEMA,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of matching relations to return.",
                    },
                },
                "required": ["relationship_type", "target_entity_type"],
                "additionalProperties": False,
            },
            handler=_typed_relation_lookup,
        ),
        ToolSpec(
            name="fetch_node_by_id",
            description="Fetch one existing entity by a stable id-like value within a specific entity type. Use this when the model already has one exact identifier-like string and wants the matching entity record without scanning an entire section.",
            input_schema={
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "description": "Dynamic entity type to search within.",
                    },
                    "node_id": {
                        "type": "string",
                        "description": "Stable id-like value to match against common identifier properties such as id, name, code, key, or title.",
                    },
                },
                "required": ["entity_type", "node_id"],
                "additionalProperties": False,
            },
            handler=_fetch_node_by_id,
        ),
        ToolSpec(
            name="fetch_relation_detail",
            description="Fetch one specific relationship detail using an exact target-entity field match. Use this when the model needs one precise relation record, including source entity, target entity, section keys, and relationship properties, instead of a broader list search. If the exact relationship type is unknown, call `list_relationship_types` first instead of guessing.",
            input_schema={
                "type": "object",
                "properties": {
                    "relationship_type": {
                        "type": "string",
                        "description": "Relationship type to match.",
                    },
                    "target_entity_type": {
                        "type": "string",
                        "description": "Dynamic entity type expected on the target side.",
                    },
                    "target_field": {
                        "type": "string",
                        "description": "Target entity property to match exactly. Defaults to id.",
                    },
                    "target_value": {
                        "type": "string",
                        "description": "Exact target property value to look up.",
                    },
                },
                "required": ["relationship_type", "target_entity_type", "target_value"],
                "additionalProperties": False,
            },
            handler=_fetch_relation_detail,
        ),
        ToolSpec(
            name="hybrid_search",
            description="Run vector retrieval over stored chunks and enrich the results with graph grounding from `MENTIONED_IN` and `DERIVED_FROM` edges. Use this when the model needs both raw chunk evidence and connected student graph context in one retrieval step.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural-language search query to match against stored chunk embeddings.",
                    },
                    "k": {
                        "type": "integer",
                        "description": "Maximum number of chunk results to retrieve before graph enrichment.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=_hybrid_search,
        ),
    ]
