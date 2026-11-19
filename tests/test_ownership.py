"""Ownership regression tests against an explicitly selected test Neo4j.

Run with PATHFINDER_OWNERSHIP_TEST_URI pointing at a disposable database;
credentials use PATHFINDER_OWNERSHIP_TEST_USER / _PASSWORD. Embeddings are
stubbed so these tests exercise real Cypher without requiring a model.
"""

import os
from uuid import uuid4

import pytest
import pytest_asyncio
from neo4j import AsyncGraphDatabase

from app.adapters.neo4j.graphDB import GraphDB
from app.adapters.neo4j.vectorDB import VectorDB
from app.adapters.embeddings import ollama
from app.tools import vector_tools
from app.tools.tools import ToolContext, execute_agent_tool, execute_tool


@pytest_asyncio.fixture
async def data(monkeypatch):
    uri = os.environ.get("PATHFINDER_OWNERSHIP_TEST_URI")
    if not uri:
        pytest.skip("Set PATHFINDER_OWNERSHIP_TEST_URI to a disposable Neo4j")
    driver = AsyncGraphDatabase.driver(uri, auth=(
        os.environ.get("PATHFINDER_OWNERSHIP_TEST_USER", "neo4j"),
        os.environ["PATHFINDER_OWNERSHIP_TEST_PASSWORD"],
    ))

    async def embeddings(texts):
        return [[1.0, 0.0, 0.0] for _ in texts]

    async def embedding(text):
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr(ollama, "aembed_documents", embeddings)
    monkeypatch.setattr(ollama, "aembed_query", embedding)
    graph = GraphDB(driver)
    vector = VectorDB(driver, index_name="ownership_tests", dimensions=3)
    prefix = uuid4().hex
    owners = [prefix + "_a", prefix + "_b"]
    try:
        await graph.init_schema()
        for owner in owners:
            await graph.create_document(student_id=owner, document_id=owner + "_doc", filename="transcript.pdf")
            await vector.upsert_chunk_metadata(student_id=owner, chunk_id=owner + "_chunk",
                                               document_id=owner + "_doc", text=owner + " private text")
            await graph.upsert_graph_node(student_id=owner, entity_type="Course", section_key="courses",
                                          identity={"code": "CSC500"}, properties={"id": owner + "_entity"})
        yield graph, vector, owners
    finally:
        # Only fixture-owned nodes; never clear an entire database.
        async with driver.session() as session:
            result = await session.run("""
                MATCH (e:Entity)-[:HAS_FIELD*1..6]->(f:Field)
                WHERE e.student_id IN $owners
                DETACH DELETE f
            """, owners=owners)
            await result.consume()
            result = await session.run("""
                MATCH (n)
                WHERE n.student_id IN $owners OR n.id IN $owners
                   OR n.document_id IN $docs
                DETACH DELETE n
            """, owners=owners, docs=[owner + "_doc" for owner in owners])
            await result.consume()
        await driver.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("method,arg,suffix", [
    ("get_chunk", "chunk_id", "_chunk"),
    ("get_chunk_neighbors", "chunk_id", "_chunk"),
    ("get_chunks_for_document", "document_id", "_doc"),
    ("get_document_search_context", "document_id", "_doc"),
])
async def test_reads_allow_owner_and_hide_other_student(data, method, arg, suffix):
    _, vector, (a, b) = data
    read = getattr(vector, method)
    assert await read(student_id=a, **{arg: a + suffix})
    if arg == "chunk_id":
        with pytest.raises(ValueError, match="chunk not found"):
            await read(student_id=a, **{arg: b + suffix})
    else:
        assert await read(student_id=a, **{arg: b + suffix}) == []


async def write_chunk(vector, method, owner, doc, chunk, text="updated"):
    if method == "batch_upsert_chunks":
        return await vector.batch_upsert_chunks(student_id=owner, document_id=doc,
                                                chunks=[{"id": chunk, "text": text}])
    return await getattr(vector, method)(student_id=owner, document_id=doc, chunk_id=chunk, text=text)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["upsert_chunk_metadata", "upsert_chunk", "batch_upsert_chunks"])
async def test_writes_allow_owner_and_reject_foreign_document_and_chunk(data, method):
    _, vector, (a, b) = data
    assert await write_chunk(vector, method, a, a + "_doc", a + "_chunk")
    assert (await vector.get_chunk(student_id=a, chunk_id=a + "_chunk"))["text"] == "updated"
    for doc, chunk in [(b + "_doc", b + "_chunk"), (b + "_doc", a + "_new"),
                       (a + "_doc", b + "_chunk")]:
        with pytest.raises(ValueError, match="not found"):
            await write_chunk(vector, method, a, doc, chunk)
    assert (await vector.get_chunk(student_id=b, chunk_id=b + "_chunk"))["text"] == b + " private text"


@pytest.mark.asyncio
async def test_batch_collision_does_not_partially_write(data):
    _, vector, (a, b) = data
    with pytest.raises(ValueError, match="not found"):
        await vector.batch_upsert_chunks(student_id=a, document_id=a + "_doc", chunks=[
            {"id": a + "_new", "text": "valid"}, {"id": b + "_chunk", "text": "overwrite"},
        ])
    with pytest.raises(ValueError, match="chunk not found"):
        await vector.get_chunk(student_id=a, chunk_id=a + "_new")


@pytest.mark.asyncio
@pytest.mark.parametrize("method,arg,suffix", [
    ("delete_chunk", "chunk_id", "_chunk"),
    ("delete_document_chunks", "document_id", "_doc"),
])
async def test_deletes_cannot_touch_other_students(data, method, arg, suffix):
    _, vector, (a, b) = data
    delete = getattr(vector, method)
    with pytest.raises(ValueError, match="not found"):
        await delete(student_id=a, **{arg: b + suffix})
    assert await vector.get_chunk(student_id=b, chunk_id=b + "_chunk")
    await delete(student_id=a, **{arg: a + suffix})
    assert await vector.get_chunks_for_document(student_id=a, document_id=a + "_doc") == []
    if method == "delete_document_chunks":
        assert (await delete(student_id=a, document_id=a + "_doc"))["deleted_chunks"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("method,arg,suffix", [
    ("link_entity_to_chunk", "chunk_id", "_chunk"),
    ("link_entity_to_document", "document_id", "_doc"),
])
async def test_evidence_links_require_both_ends_to_have_same_owner(data, method, arg, suffix):
    graph, _, (a, b) = data
    link = getattr(graph, method)
    args = dict(student_id=a, entity_type="Course", identity={"code": "CSC500"})
    with pytest.raises(ValueError, match="link failed"):
        await link(**args, **{arg: b + suffix})
    assert await link(**args, **{arg: a + suffix})


@pytest.mark.asyncio
async def test_bfs_scopes_start_intermediate_and_returned_nodes(data):
    graph, _, (a, b) = data
    async with graph.driver.session() as session:
        # Simulate legacy contamination: a short path through a foreign
        # node back to an owned document must not be traversable either.
        await session.run("""
            MATCH (a:Entity {id: $a}), (b:Entity {id: $b}), (d:Document {id: $doc})
            CREATE (a)-[:TEST_CROSS_STUDENT]->(b)-[:TEST_CROSS_STUDENT]->(d)
        """, a=a + "_entity", b=b + "_entity", doc=a + "_doc")
    for start in [b, b + "_entity", b + "_chunk", b + "_doc"]:
        with pytest.raises(ValueError, match="not found"):
            await graph.bfs_neighbors(student_id=a, start_node_id=start)
    result = await graph.bfs_neighbors(student_id=a, start_node_id=a + "_entity", max_depth=2)
    nodes = [node for level in result["levels"] for node in level["nodes"]]
    assert nodes
    assert not any(str(node.get("id", "")).startswith(b) for node in nodes)
    assert not any(node.get("id") == a + "_doc" for node in nodes)
    # Chunk, document and student roots remain valid starting points.
    for start in [a, a + "_chunk", a + "_doc"]:
        assert await graph.bfs_neighbors(student_id=a, start_node_id=start)


@pytest.mark.asyncio
async def test_chunk_entities_rejects_legacy_foreign_evidence(data):
    graph, _, (a, b) = data
    async with graph.driver.session() as session:
        await session.run("""
            MATCH (e:Entity {id: $entity}), (c:Chunk {id: $chunk}), (d:Document {id: $doc})
            CREATE (e)-[:MENTIONED_IN]->(c), (e)-[:DERIVED_FROM]->(d)
        """, entity=a + "_entity", chunk=b + "_chunk", doc=b + "_doc")
    assert await graph.get_chunk_entities(student_id=a, chunk_id=b + "_chunk") == []
    profile = await graph.get_full_student(student_id=a)
    assert profile["entities"][0]["chunks"] == []
    assert profile["entities"][0]["documents"] == []


@pytest.mark.asyncio
async def test_relation_reads_filter_foreign_endpoints(data):
    graph, _, (a, b) = data
    async with graph.driver.session() as session:
        await session.run("""
            MATCH (a:Entity {id: $a}), (b:Entity {id: $b})
            CREATE (a)-[:TEST_CROSS_STUDENT]->(b)
        """, a=a + "_entity", b=b + "_entity")
    args = dict(student_id=a, relationship_type="TEST_CROSS_STUDENT", target_entity_type="Course")
    assert await graph.typed_relation_lookup(**args) == []
    with pytest.raises(ValueError, match="relation not found"):
        await graph.fetch_relation_detail(**args, target_value=b + "_entity")
    await graph.upsert_graph_node(student_id=a, entity_type="Course", section_key="courses",
                                  identity={"code": "CSC501"}, properties={"id": a + "_second"})
    await graph.upsert_graph_relation(student_id=a, source_entity_type="Course", source_identity={"code": "CSC500"},
                                      target_entity_type="Course", target_identity={"code": "CSC501"},
                                      relationship_type="TEST_OWNED", properties={})
    args["relationship_type"] = "TEST_OWNED"
    assert len(await graph.typed_relation_lookup(**args)) == 1
    assert await graph.fetch_relation_detail(**args, target_value=a + "_second")


@pytest.mark.asyncio
async def test_replacement_cascade_respects_owner(data):
    graph, vector, (a, b) = data
    await graph.delete_document_cascade(student_id=a, document_id=b + "_doc")
    assert await vector.get_chunk(student_id=b, chunk_id=b + "_chunk")
    await graph.delete_document_cascade(student_id=a, document_id=a + "_doc")
    assert await graph.get_student(student_id=a)
    assert await graph.get_entity_by_identity(student_id=a, entity_type="Course", identity={"code": "CSC500"})
    with pytest.raises(ValueError, match="chunk not found"):
        await vector.get_chunk(student_id=a, chunk_id=a + "_chunk")
    # Replacement can register and populate a fresh document normally.
    await graph.create_document(student_id=a, document_id=a + "_doc", filename="replacement.pdf")
    await write_chunk(vector, "batch_upsert_chunks", a, a + "_doc", a + "_chunk")


@pytest.mark.asyncio
async def test_llm_cannot_change_ownership_metadata(data):
    graph, _, (a, b) = data
    with pytest.raises(ValueError, match="identity cannot be changed"):
        await graph.update_student(student_id=a, updates={"id": b})
    with pytest.raises(ValueError, match="managed by the application"):
        await graph.upsert_graph_node(student_id=a, entity_type="Course", section_key="courses",
                                      identity={"student_id": b}, properties={"code": "bad"})
    with pytest.raises(ValueError, match="managed by the application"):
        await graph.upsert_graph_node(student_id=a, entity_type="Course", section_key="courses",
                                      identity={"code": "CSC500"}, properties={"student_id": b})


@pytest.mark.asyncio
async def test_dispatch_rejects_missing_owner():
    assert "error" in await execute_tool("get_chunk", {"chunk_id": "x"}, ToolContext(student_id=""))
    assert "error" in await execute_agent_tool("specialist", "get_chunk", {}, ToolContext(student_id=" "))


@pytest.mark.asyncio
async def test_bfs_allows_owned_fields_and_rejects_foreign_fields(data):
    graph, _, (a, b) = data
    for owner in (a, b):
        field = await graph.upsert_entity_field(student_id=owner, entity_type="Course",
                                                identity={"code": "CSC500"}, field_name="rubric", field_value="details")
        nested = await graph.upsert_nested_field(student_id=owner, parent_field_id=field["id"],
                                                 field_name="criteria", field_value="accuracy")
        for node_id in (field["id"], nested["id"]):
            if owner == a:
                assert await graph.bfs_neighbors(student_id=a, start_node_id=node_id)
            else:
                with pytest.raises(ValueError, match="not found"):
                    await graph.bfs_neighbors(student_id=a, start_node_id=node_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", [
    "get_chunk", "get_chunks_for_document", "get_chunk_neighbors", "get_document_search_context",
    "upsert_chunk_metadata", "upsert_chunk", "batch_upsert_chunks", "delete_chunk", "delete_document_chunks",
])
async def test_vector_tools_use_context_owner_not_llm_argument(monkeypatch, tool):
    class CaptureDB:
        def __getattr__(self, name):
            async def capture(**args):
                assert args["student_id"] == "trusted-owner"
                return {}
            return capture

    async def database(context):
        return CaptureDB()

    monkeypatch.setattr(vector_tools, "_vector_db", database)
    await getattr(vector_tools, "_" + tool)({"student_id": "foreign-owner"}, ToolContext(student_id="trusted-owner"))
