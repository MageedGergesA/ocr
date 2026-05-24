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


def _run(file_bytes: bytes, media_type: str, prompt: str, hard: bool) -> dict:
    b64 = base64.standard_b64encode(file_bytes).decode()
    # PDFs go in a 'document' block (Claude reads all pages with cross-page context);
    # images go in an 'image' block.
    if media_type == "application/pdf":
        source_block = {"type": "document",
                        "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    else:
        source_block = {"type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": b64}}
    params = {
        "model": MODEL_HARD if hard else MODEL_EASY,
        # Generous output room: multi-page / many-line docs produce long JSON.
        # Too small a cap truncates the response mid-string and breaks parsing.
        # (You're billed for tokens actually generated, not the cap.)
        "max_tokens": 16000 if hard else 8192,
        "messages": [{"role": "user", "content": [source_block, {"type": "text", "text": prompt}]}],
    }
    if hard:
        # Let the model deliberate over ambiguous handwriting before answering.
        # Improves reading accuracy without suppressing outputs (billed as output tokens).
        params["thinking"] = {"type": "enabled", "budget_tokens": 2048}
    msg = _get_client().messages.create(**params)
    # With thinking on, content holds thinking block(s) + a text block — take the text.
    text = next((b.text for b in msg.content if getattr(b, "type", None) == "text"), "")
    try:
        return json.loads(_strip_code_fence(text))
    except json.JSONDecodeError:
        if getattr(msg, "stop_reason", None) == "max_tokens":
            raise ValueError(
                "the response was truncated — this document is unusually large/complex. "
                "Try splitting the PDF or using specific-fields mode to extract fewer fields."
            )
        raise


def extract_auto(image_bytes: bytes, media_type: str, hard: bool = True) -> dict:
    """Detect the document type and extract every meaningful field automatically.

    Returns: {"document_type": str, "fields": {name: {"value": ..., "confidence": 0-1}}}
    """
    prompt = (
        "You are a document data-extraction system. Look at this document and:\n"
        "1. Identify its type (e.g., passport, national ID, invoice, receipt, contract, "
        "prescription, business card, OR a freeform letter / note / handwritten paragraph).\n"
        "2. Choose the right output form:\n"
        "   - If it is a STRUCTURED document (invoice, ID, form, receipt, card, etc.), "
        "extract its individual named fields. Choose names that fit the document; "
        "do not invent fields that are not present.\n"
        "   - If it is FREEFORM TEXT (a letter, note, essay, or any narrative prose with no "
        "structured fields), do NOT split it into invented fields. Instead return a single "
        'field named "full_text" whose value is the COMPLETE transcription, preserving line breaks.\n'
        "The document may be in Arabic, English, or handwritten; keep the original language. "
        "Be thorough and give your best reading for everything — do not skip unclear parts.\n"
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
        "Extract the following fields from this document. "
        "The document may be in Arabic, English, or handwritten. "
        "Return ONLY valid JSON, no other text. "
        "For each field, return an object with 'value' and 'confidence' (0-1). "
        "If a field is not present, set its value to null.\n\n"
        f"Fields:\n{field_list}"
    )
    return _run(image_bytes, media_type, prompt, hard)
