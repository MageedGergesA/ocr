"""Document extraction via Claude Vision.

One job: take an image/PDF page + a target schema, return structured JSON.
Model routing keeps cost down — Haiku for easy docs, Sonnet for hard/handwritten.
"""
import base64
import json
import os

from anthropic import Anthropic

client = Anthropic()  # reads ANTHROPIC_API_KEY from env

MODEL_EASY = os.getenv("MODEL_EASY", "claude-haiku-4-5-20251001")
MODEL_HARD = os.getenv("MODEL_HARD", "claude-sonnet-4-6")


def _strip_code_fence(text: str) -> str:
    """Claude sometimes wraps JSON in ```json ... ``` fences. Peel them off."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


def extract(image_bytes: bytes, media_type: str, target_schema: dict, hard: bool = True) -> dict:
    """Extract `target_schema` fields from a document image.

    target_schema: {field_name: human description}
    hard: route to Sonnet (handwritten/Arabic/low-quality); else Haiku.
    Returns: {field_name: {"value": ..., "confidence": 0-1}, ...}
    """
    image_b64 = base64.standard_b64encode(image_bytes).decode()
    field_list = "\n".join(f"- {k}: {v}" for k, v in target_schema.items())

    prompt = (
        "Extract the following fields from this document. "
        "The document may be in Arabic, English, or handwritten. "
        "Return ONLY valid JSON, no other text. "
        "For each field, return an object with 'value' and 'confidence' (0-1).\n\n"
        f"Fields:\n{field_list}"
    )

    msg = client.messages.create(
        model=MODEL_HARD if hard else MODEL_EASY,
        max_tokens=2048,
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
    response_text = _strip_code_fence(msg.content[0].text)
    return json.loads(response_text)
