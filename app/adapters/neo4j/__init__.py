"""Neo4j adapter layer — everything that talks Cypher lives here.

- `graphDB.py`   : `GraphDB` class with all structured reads/writes
                   (students, sections, entities, relations, fields,
                   documents, chunks).
- `vectorDB.py`  : `VectorDB` class for chunk embeddings and vector
                   similarity search over the `chunk_embeddings` index.
- `_sanitize.py` : converts Neo4j-native types (DateTime, Node, etc.)
                   into JSON-safe Python values for API responses.

The tools in `app.tools.graph_tools` and `app.tools.vector_tools` are
thin wrappers over these classes with LLM-friendly shapes on top.
"""
