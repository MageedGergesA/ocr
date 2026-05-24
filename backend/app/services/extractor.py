"""Document extraction via Claude Vision.

Two modes:
  - auto   : model detects the document type and extracts whatever fields belong to it.
  - schema : caller supplies an exact field list (used by the Odoo module to map to model fields).

Model routing keeps cost down — Haiku for easy docs, Sonnet for hard/handwritten.
"""
import base64
import json
import os

from anthropic import Anthropic

MODEL_EASY = os.getenv("MODEL_EASY", "claude-haiku-4-5-20251001")
MODEL_HARD = os.getenv("MODEL_HARD", "claude-sonnet-4-6")

_client = None


def _get_client() -> Anthropic:
    """Build the Anthropic client lazily so the server (and its pages) can
    start without a key. Only actual extraction requires ANTHROPIC_API_KEY."""
    global _client
    if _client is None:
        _client = Anthropic()  # reads ANTHROPIC_API_KEY from env
    return _client


def _strip_code_fence(text: str) -> str:
    """Claude sometimes wraps JSON in ```json ... ``` fences. Peel them off."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


# Shared guidance that makes handwriting / Arabic extraction more accurate and
# keeps the confidence score honest instead of optimistic.
HANDWRITING_GUIDANCE = (
    "This document may be handwritten and/or in Arabic. Read it slowly and carefully, "
    "letter by letter — account for Arabic letter forms, ligatures, diacritics, and "
    "commonly confused characters and digits. Transcribe exactly what is written; "
    "never guess, autocomplete, or invent a value. If part of a value is unclear, "
    "extract what you can read and lower its confidence. If a field is illegible or "
    "absent, set its value to null. Calibrate confidence honestly: use 0.9+ only when "
    "you are genuinely certain, and below 0.6 when the writing is hard to read."
)


def _run(image_bytes: bytes, media_type: str, prompt: str, hard: bool) -> dict:
    image_b64 = base64.standard_b64encode(image_bytes).decode()
    msg = _get_client().messages.create(
        model=MODEL_HARD if hard else MODEL_EASY,
        max_tokens=2048,
        temperature=0,  # deterministic extraction — minimizes guessing/drift
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": media_type, "data": image_b64,
                }},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    text = next((b.text for b in msg.content if getattr(b, "type", None) == "text"), "")
    return json.loads(_strip_code_fence(text))


def extract_auto(image_bytes: bytes, media_type: str, hard: bool = True) -> dict:
    """Detect the document type and extract every meaningful field automatically.

    Returns: {"document_type": str, "fields": {name: {"value": ..., "confidence": 0-1}}}
    """
    prompt = (
        "You are a document data-extraction system. Look at this document and:\n"
        "1. Identify its type (e.g., passport, national ID, driver license, invoice, "
        "receipt, contract, bank statement, prescription, business card).\n"
        "2. Extract ALL meaningful fields that actually appear on THIS document. "
        "Choose field names that fit the document type — do not invent fields that are not present. "
        "Keep each value in its original language.\n\n"
        f"{HANDWRITING_GUIDANCE}\n\n"
        "Return ONLY valid JSON, no other text, in exactly this shape:\n"
        '{"document_type": "<type>", "fields": {"<field name>": '
        '{"value": <value>, "confidence": <0-1>}, ...}}'
    )
    return _run(image_bytes, media_type, prompt, hard)


def extract_schema(image_bytes: bytes, media_type: str, target_schema: dict, hard: bool = True) -> dict:
    """Extract a caller-defined set of fields.

    target_schema: {field_name: human description}
    Returns: {field_name: {"value": ..., "confidence": 0-1}, ...}
    """
    field_list = "\n".join(f"- {k}: {v}" for k, v in target_schema.items())
    prompt = (
        "Extract the following fields from this document.\n\n"
        f"{HANDWRITING_GUIDANCE}\n\n"
        "Return ONLY valid JSON, no other text. "
        "For each field, return an object with 'value' and 'confidence' (0-1). "
        "If a field is not present, set its value to null.\n\n"
        f"Fields:\n{field_list}"
    )
    return _run(image_bytes, media_type, prompt, hard)
