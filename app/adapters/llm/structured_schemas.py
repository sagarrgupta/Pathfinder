"""Structured-output schemas for LLM nodes that return machine-consumed JSON."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def get_structured_output_schema(node_name: str) -> dict[str, Any] | None:
    """Return a JSON schema for the given node, if one is registered."""
    schema = _SCHEMA_MAP.get(node_name)
    return deepcopy(schema) if schema is not None else None


def _decision_payload_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "decision_type": {"type": "string"},
            "answer_outline": {"type": "array", "items": {"type": "string"}},
            "assumptions": {"type": "array", "items": {"type": "string"}},
            "next_best_action": {"type": "string"},
            "recommended_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {
                        "label": {"type": "string"},
                        "reason": {"type": "string"},
                        "status": {"type": "string"},
                        "assumption": {"type": "string"},
                        "support_codes": {"type": "array", "items": {"type": "string"}},
                        "support_refs": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "blocked_or_uncertain_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {
                        "label": {"type": "string"},
                        "reason": {"type": "string"},
                        "kind": {"type": "string"},
                    },
                },
            },
            "source_refs": {"type": "array", "items": {"type": "string"}},
            "recommendation_paths": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {
                        "label": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                },
            },
            "student_strategy": {
                "type": "object",
                "additionalProperties": True,
            },
        },
    }


_SCHEMA_MAP: dict[str, dict[str, Any]] = {
    "orchestrator": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "intent": {"type": "string"},
            "plan": {"type": "array", "items": {"type": "string"}},
            "missing_info": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["intent", "plan", "missing_info"],
    },
    "evaluator": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "is_grounded": {"type": "boolean"},
            "confidence_score": {"type": "number"},
            "issues": {
                "type": "array",
                "items": {
                    "anyOf": [
                        {"type": "string"},
                        {
                            "type": "object",
                            "additionalProperties": True,
                            "properties": {
                                "type": {"type": "string"},
                                "text": {"type": "string"},
                            },
                        },
                    ]
                },
            },
            "profile_updates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {
                        "field": {"type": "string"},
                        "value": {"type": "string"},
                    },
                },
            },
            "needs_disclaimer": {"type": "boolean"},
            "disclaimer": {"type": "string"},
        },
        "required": [
            "is_grounded",
            "confidence_score",
            "issues",
            "profile_updates",
            "needs_disclaimer",
            "disclaimer",
        ],
    },
    "course_planner": _decision_payload_schema(),
    "advisor_runtime": _decision_payload_schema(),
}
