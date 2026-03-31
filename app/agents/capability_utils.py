"""Helpers for capability-native reasoning agents."""

from __future__ import annotations

from typing import Any


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def format_personal_context(state: dict[str, Any]) -> str:
    pack = state.get("memory_pack", {})
    always_on = pack.get("always_on_context", {})
    if not always_on:
        always_on = {}
    parts = []
    for key in ("name", "university", "program", "semester", "top_goal"):
        value = always_on.get(key)
        if value:
            parts.append(f"{key}: {value}")
    return _clip("\n".join(parts) if parts else "No core identity context available.", 320)


def format_profile_context(state: dict[str, Any]) -> str:
    profile_context = state.get("graph_results", {}) or {}
    sections = []
    for key, values in profile_context.items():
        if not values:
            continue
        if isinstance(values, list):
            snippets = []
            for item in values[:4]:
                if isinstance(item, dict):
                    snippets.append(
                        _clip(
                            item.get("name")
                        or item.get("code")
                        or item.get("summary")
                        or item.get("value")
                        or str(item)[:80],
                            60,
                        )
                    )
                else:
                    snippets.append(_clip(str(item), 60))
            sections.append(f"{key}: {', '.join(snippets)}")
        else:
            sections.append(f"{key}: {_clip(str(values), 80)}")
    return _clip("\n".join(sections) if sections else "No scoped profile context available.", 700)


def format_semantic_memory(state: dict[str, Any]) -> str:
    semantic = state.get("semantic_memory", {}) or {}
    lines = []
    for key in ("candidate_facts", "memory_items", "evidence"):
        items = semantic.get(key, [])
        if not items:
            continue
        snippets = []
        for item in items[:3]:
            if key == "candidate_facts":
                snippets.append(
                    f"{item.get('fact_type', 'fact')}: {_clip(item.get('value', ''), 70)} "
                    f"(conf={item.get('confidence', 0):.2f})"
                )
            elif key == "memory_items":
                snippets.append(
                    f"{item.get('memory_type', 'memory')}: {_clip(item.get('summary', ''), 90)} "
                    f"(conf={item.get('confidence', 0):.2f})"
                )
            else:
                snippets.append(f"{item.get('source_type', 'evidence')}: {_clip(item.get('content', ''), 100)}")
        lines.append(f"{key}: " + " | ".join(snippets))
    return _clip("\n".join(lines) if lines else "No semantic memory available.", 900)


def format_documents(state: dict[str, Any]) -> str:
    documents = state.get("retrieved_documents", []) or []
    if not documents:
        return "No document evidence available."
    return _clip(
        "\n".join(
            f"[{doc.get('filename', 'doc')}] {_clip(doc.get('text', ''), 140)}"
            for doc in documents[:3]
        ),
        700,
    )


def format_web_results(state: dict[str, Any]) -> str:
    web_results = state.get("web_results", []) or []
    if not web_results:
        return "No web evidence available."
    return _clip(
        "\n".join(
            f"[{_clip(result.get('title', 'Untitled'), 60)}] {_clip(result.get('url', ''), 100)} :: {_clip(result.get('content', ''), 120)}"
            for result in web_results[:3]
        ),
        800,
    )


def format_missing_and_conflicts(state: dict[str, Any]) -> str:
    missing = state.get("missing_info", []) or []
    conflicts = state.get("conflicts", []) or []
    parts = []
    if missing:
        parts.append("Missing info: " + ", ".join(missing))
    if conflicts:
        conflict_bits = []
        for item in conflicts[:3]:
            conflict_bits.append(
                item.get("value")
                or item.get("summary")
                or item.get("name")
                or str(item)[:80]
            )
        parts.append("Conflicts: " + " | ".join(conflict_bits))
    return _clip("\n".join(parts) if parts else "No important missing info or conflicts.", 300)


def format_saved_recommendations(state: dict[str, Any]) -> str:
    items = state.get("saved_recommendations", []) or []
    if not items:
        return "No prior saved plans to revisit."
    lines = []
    for item in items[:2]:
        title = item.get("metadata", {}).get("title") or item.get("summary", "Saved plan")
        status = item.get("metadata", {}).get("status", "active")
        prompt = item.get("metadata", {}).get("follow_up_prompt", "")
        lines.append(f"{_clip(title, 60)} [{status}] {_clip(prompt, 80)}".strip())
    return _clip("\n".join(lines), 260)


def build_reasoning_context(state: dict[str, Any], *, include_web: bool = True) -> str:
    sections = [
        "Personal Context:\n" + format_personal_context(state),
        "Scoped Profile:\n" + format_profile_context(state),
        "Semantic Memory:\n" + format_semantic_memory(state),
        "Saved Plans To Revisit:\n" + format_saved_recommendations(state),
        "Document Evidence:\n" + format_documents(state),
    ]
    if include_web:
        sections.append("Web Evidence:\n" + format_web_results(state))
    sections.append("Missing/Conflicts:\n" + format_missing_and_conflicts(state))
    return _clip("\n\n".join(sections), 3200)
