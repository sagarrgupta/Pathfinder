"""Pydantic schemas shared between the API layer and the rest of the app.

Everything exposed over HTTP goes through the models in `models.py`. They
give us two things for free:
- request validation (bad payloads turn into clean 422 responses), and
- a single place to change the shape of any API contract.

Nothing in here touches Neo4j, the LLM, or the filesystem — these are
pure data classes.
"""
