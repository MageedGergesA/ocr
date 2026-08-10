"""Structured-output (JSON Schema) support for document extraction.

The legacy path coaxes JSON with prompt instructions + fence-stripping + json.loads
— brittle, and truncation surfaces as a user error. Gemini can instead be asked for
a typed JSON response via `response_schema`. This module converts a Mostakhles field
schema into a response schema and centralizes the on/off decision.

SAFE BY DEFAULT: `enabled()` is driven by settings.STRUCTURED_OUTPUT_ENABLED, which
defaults False. The production extraction path is unchanged until the benchmark
proves structured output reduces parse failures without regressing accuracy
(Section 32 A/B). Application-side semantic validation, normalization, confidence,
and CorrectionMemory remain mandatory regardless of this flag.
"""
from __future__ import annotations

from typing import Any


def enabled() -> bool:
    try:
        from app.config import settings
        return bool(getattr(settings, "STRUCTURED_OUTPUT_ENABLED", False))
    except Exception:  # noqa: BLE001
        return False


def field_cell_schema() -> dict:
    """Each extracted field is a {value, confidence} cell — matching the shape the
    rest of the pipeline (normalize/validate/learning/UI) already expects."""
    return {
        "type": "object",
        "properties": {
            "value": {"type": "string"},
            "confidence": {"type": "number"},
        },
        "required": ["value"],
    }


def to_response_schema(caller_schema: Any) -> dict:
    """Convert a Mostakhles caller schema {field: description, ...} into a Gemini
    response JSON Schema: an object whose properties are the requested fields, each
    a {value, confidence} cell. Preserves the field set and order-independence so
    the returned keys match the caller's schema regardless of document language.

    The returned schema is additive-compatible: downstream code already reads
    {value, confidence} cells, so a structured response drops straight in.
    """
    fields = list(caller_schema.keys()) if isinstance(caller_schema, dict) else []
    props = {str(f): field_cell_schema() for f in fields}
    return {
        "type": "object",
        "properties": props,
        # Do NOT mark fields required: absence is meaningful (missing-field signal),
        # and forcing values would push the model to hallucinate.
        "propertyOrdering": [str(f) for f in fields],
    }


def validate_structured_result(result: Any, caller_schema: Any) -> tuple[bool, list]:
    """Semantic check AFTER a structured response: it must be a dict and every
    present field must be a {value,...} cell or scalar. Returns (ok, problems).
    Semantic validation stays mandatory even with syntactically-structured output."""
    problems: list[str] = []
    if not isinstance(result, dict):
        return False, ["structured result is not an object"]
    for k, v in result.items():
        if isinstance(v, dict) and "value" not in v:
            problems.append(f"field '{k}' has no 'value'")
    return (len(problems) == 0), problems
