"""Shared helpers for the document and chat-message ingestion pipelines.

Both `app.utils.document_ingest` and `app.utils.query_ingest` log every
tool call the ingestion agent makes, and both want the same "what did
this ingestion actually change?" summary afterwards — so the summary
builder lives here and is shared by both.

Anything pipeline-specific (prompt templates, the agent loop itself,
final-answer normalization) stays in the per-pipeline module.
"""

from __future__ import annotations

import json
from typing import Any


def build_graph_updates(tool_call_log: list[dict[str, Any]]) -> dict[str, Any]:
    """Distill a raw tool-call log into a human-friendly change summary.

    The ingestion agents emit dozens of tool calls per document
    (upserts, linkages, field writes, failed attempts, ...). This
    function walks the log, keeps only the successful writes, and
    produces a compact report with:

    - `sections_touched` / `entity_types_touched` / `relationship_types_touched`
      — de-duplicated names that actually got written to,
    - `counts` — per-operation counters (sections_upserted, entities,
      relationships, chunk/document links, field writes),
    - `sample_entities_written` — up to 5 representative
      `{entity_type, identity}` pairs so the replay viewer can show
      "here's what we learned" without dumping every node.

    This report is what shows up in the `graph_updates` block of a
    replay artifact and in the UI "Saved N details from your file"
    toast.
    """
    sections_touched: list[str] = []
    entity_types_touched: list[str] = []
    relationship_types_touched: list[str] = []
    sample_entities_written: list[dict[str, Any]] = []
    seen_sections: set[str] = set()
    seen_entity_types: set[str] = set()
    seen_relationship_types: set[str] = set()
    seen_entity_samples: set[str] = set()
    counts = {
        "sections_upserted": 0,
        "entities_written": 0,
        "relationships_written": 0,
        "chunk_links_written": 0,
        "document_links_written": 0,
        "field_writes": 0,
    }

    for item in tool_call_log:
        if not isinstance(item, dict) or item.get("status") != "ok":
            continue
        tool_name = str(item.get("tool", "") or "")
        args = dict(item.get("input") or {})

        if tool_name == "upsert_section":
            counts["sections_upserted"] += 1
            key = str(args.get("key", "") or "").strip()
            if key and key not in seen_sections:
                seen_sections.add(key)
                sections_touched.append(key)
            continue

        if tool_name == "upsert_graph_node":
            counts["entities_written"] += 1
            entity_type = str(args.get("entity_type", "") or "").strip()
            if entity_type and entity_type not in seen_entity_types:
                seen_entity_types.add(entity_type)
                entity_types_touched.append(entity_type)
            identity = dict(args.get("identity") or {})
            if entity_type and identity:
                identity_signature = json.dumps(
                    {"entity_type": entity_type, "identity": identity},
                    sort_keys=True,
                    ensure_ascii=True,
                    default=str,
                )
                if identity_signature not in seen_entity_samples and len(sample_entities_written) < 5:
                    seen_entity_samples.add(identity_signature)
                    sample_entities_written.append(
                        {"entity_type": entity_type, "identity": identity}
                    )
            continue

        if tool_name == "upsert_graph_relation":
            counts["relationships_written"] += 1
            relationship_type = str(args.get("relationship_type", "") or "").strip()
            if relationship_type and relationship_type not in seen_relationship_types:
                seen_relationship_types.add(relationship_type)
                relationship_types_touched.append(relationship_type)
            continue

        if tool_name == "link_entity_to_chunk":
            counts["chunk_links_written"] += 1
            continue

        if tool_name == "link_entity_to_document":
            counts["document_links_written"] += 1
            continue

        if tool_name in {"upsert_entity_field", "upsert_nested_field"}:
            counts["field_writes"] += 1

    return {
        "sections_touched": sections_touched,
        "entity_types_touched": entity_types_touched,
        "relationship_types_touched": relationship_types_touched,
        "counts": counts,
        "sample_entities_written": sample_entities_written,
    }
