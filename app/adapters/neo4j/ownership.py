"""Ownership predicates for traversals across the student graph.

Only structural ownership edges count; evidence and semantic links cannot
grant access to another student's data. Aliases are application constants.
"""

import re


def owned_node_predicate(alias: str) -> str:
    """Return Cypher using the bound `student` node and `$student_id`."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias):
        raise ValueError("invalid node alias")
    return f"""(
        ({alias}.student_id IS NULL OR {alias}.student_id = $student_id)
        AND (
            {alias} = student
            OR EXISTS {{ MATCH (student)-[:HAS_SECTION]->({alias}:Section) }}
            OR EXISTS {{ MATCH (student)-[:HAS_SECTION]->(:Section)-[:HAS_ITEM]->({alias}:Entity) }}
            OR EXISTS {{ MATCH (student)-[:UPLOADED]->({alias}:Document) }}
            OR EXISTS {{ MATCH (student)-[:UPLOADED]->(:Document)<-[:FROM_DOCUMENT]-({alias}:Chunk) }}
            OR EXISTS {{ MATCH (student)-[:HAS_SECTION]->(:Section)-[:HAS_ITEM]->(:Entity)-[:HAS_FIELD*1..6]->({alias}:Field) }}
        )
    )"""
