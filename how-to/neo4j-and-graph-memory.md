# Neo4j and Graph Memory

Neo4j stores both **graph data** (users, documents, skills, goals, relationships) and **vector embeddings** (for semantic search over document chunks). Your agent uses it as long-term memory.

---

## 1. How to Install

### 1.1 Prerequisites

- Docker running (see `docker-for-local-services.md`)
- Python 3.10+ for the Neo4j driver

### 1.2 Run Neo4j via Docker

Add Neo4j to your `docker-compose.yml` and start it:

```yaml
services:
  neo4j:
    image: neo4j:5-community
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      - NEO4J_AUTH=neo4j/your-password
    volumes:
      - neo4j_data:/data
volumes:
  neo4j_data:
```

```bash
docker compose up -d neo4j
docker compose ps
```

Verify at http://localhost:7474 (Browser) with `neo4j` / `your-password`.

### 1.3 Install Python Driver

```bash
pip install neo4j
```

For LangChain integration (optional):

```bash
pip install langchain-neo4j
```

---

## 2. Why Use Neo4j for Your Agent

| Capability | Description |
|------------|-------------|
| **Graph memory** | Model users, documents, skills, goals, courses as nodes and relationships. |
| **Cypher queries** | Ask questions like "what skills link to this goal?" or "which courses relate to these interests?" |
| **Vector memory** | Store embeddings (from Ollama) with text chunks; run semantic similarity search. |
| **Single store** | One database for structured profile data and unstructured chunks. |
| **Traversals** | Navigate relationships (e.g. user → documents → chunks) efficiently. |

---

## 3. Key Concepts

| Concept | Description |
|---------|-------------|
| **Node** | Entity with labels (e.g. `:User`, `:Document`, `:Chunk`, `:Skill`) and properties. |
| **Relationship** | Directed edge between nodes (e.g. `(User)-[:UPLOADED]->(Document)`). |
| **Cypher** | Query language for creating and querying the graph. |
| **Vector index** | Index on embedding properties for `db.index.vector.queryNodes()`. |

---

## 4. How to Set Up and Use

### 4.1 Configure Connection

Add to `.env`:

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-password
```

### 4.2 Create Driver in Python

```python
from neo4j import GraphDatabase
import os

driver = GraphDatabase.driver(
    os.environ["NEO4J_URI"],
    auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
)

# Test
with driver.session() as session:
    result = session.run("RETURN 1 AS ok")
    assert result.single()["ok"] == 1
```

### 4.3 Create Graph Schema (Example)

Run in Neo4j Browser or via Python:

```cypher
-- User and skills
CREATE (u:User {id: "default", name: "Alice"});
CREATE (s:Skill {name: "Python"});
MATCH (u:User {id: "default"}), (s:Skill {name: "Python"})
CREATE (u)-[:HAS_SKILL]->(s);

-- Document and chunks (for RAG)
CREATE (d:Document {id: "doc1", filename: "notes.pdf"});
CREATE (c:Chunk {id: "chunk1", text: "Sample text...", embedding: $embedding})
CREATE (c)-[:FROM_DOCUMENT]->(d);
```

### 4.4 Create Vector Index

Embedding dimension must match your model (e.g. `mxbai-embed-large` → 1024):

```cypher
CREATE VECTOR INDEX chunk_embeddings IF NOT EXISTS
FOR (c:Chunk) ON (c.embedding)
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 1024,
    `vector.similarity_function`: 'cosine'
  }
};
```

### 4.5 Query Similar Chunks (RAG)

```cypher
CALL db.index.vector.queryNodes('chunk_embeddings', 5, $query_embedding)
YIELD node, score
RETURN node.text AS text, score
ORDER BY score DESC;
```

---

## 5. End-to-End Retrieval Flow

### Ingest (when user uploads a document)

1. Split text into chunks (e.g. 500 chars, 100 overlap).
2. Call Ollama to get embeddings for each chunk.
3. Store in Neo4j:

```cypher
CREATE (d:Document {id: $doc_id, filename: $filename});
UNWIND $chunks AS chunk
CREATE (c:Chunk {
  id: chunk.id,
  text: chunk.text,
  embedding: chunk.embedding,
  page_number: chunk.page,
  chunk_index: chunk.index
})
CREATE (c)-[:FROM_DOCUMENT]->(d);
```

### Query (when user asks a question)

1. Embed the query with Ollama.
2. Run vector search (see 4.5).
3. Pass top-k chunks as context to your LLM.
4. LLM generates an answer grounded in those chunks.

---

## 6. Common Pitfalls and Fixes

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Authentication failure" | Password mismatch | `docker compose down -v` then `up -d` with correct `NEO4J_AUTH`; update `.env` |
| "Connection refused" | Neo4j not running or wrong port | `docker compose ps`; verify `bolt://localhost:7687`; wait 10–20s after startup |
| Vector index fails | Wrong dimensions | Check `len(embedding)` from your model; use that value in index config |
| "Node not found" in vector query | Index name typo | Use exact index name: `'chunk_embeddings'` |
| Slow vector queries | Large dataset, no index | Ensure index exists; limit `TOP_K` (e.g. 5–10) |

---

## 7. Common Cypher Patterns

| Task | Cypher |
|------|--------|
| Create node | `CREATE (n:Label {prop: "value"})` |
| Create relationship | `MATCH (a), (b) CREATE (a)-[:REL]->(b)` |
| Find by property | `MATCH (u:User {id: $id}) RETURN u` |
| Traverse | `MATCH (u:User)-[:HAS_SKILL]->(s:Skill) RETURN s.name` |
| Vector search | `CALL db.index.vector.queryNodes('index_name', k, $embedding) YIELD node, score` |
| Delete node + relationships | `MATCH (n {id: $id}) DETACH DELETE n` |

---

## 8. Official Documentation

- **Neo4j Docs:** https://neo4j.com/docs/
- **Cypher Manual:** https://neo4j.com/docs/cypher-manual/
- **Python Driver:** https://neo4j.com/docs/python-manual/
- **Vector Indexes:** https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/
- **Docker:** https://neo4j.com/docs/operations-manual/current/docker/
