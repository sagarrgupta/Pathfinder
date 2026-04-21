"""Embedding backends.

Currently only Ollama (`ollama.py`). The public shape is one async
function that turns a list of texts into a list of vectors. The vector
dimensions must line up with `settings.EMBEDDING_DIMENSIONS` and the
Neo4j vector index dim set at startup.
"""
