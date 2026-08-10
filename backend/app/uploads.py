"""Untrusted-upload validation (P0.8).

Two defenses the extraction endpoints share:

1. Magic-byte type detection — we do NOT trust the browser-supplied
   `Content-Type`. `sniff_mime` reads the leading bytes and returns the real type;
   an upload whose real type isn't in the allow-list is rejected.

2. Decompression-bomb protection — `validate_upload` reads an image's declared
   dimensions from its HEADER (Pillow `Image.open` does not decode pixels) and
   rejects anything over `MAX_IMAGE_PIXELS` BEFORE any pixel is decoded. This holds
   for tiny, highly-compressed files too (the old <200 KB preprocessing bypass let
   a small gigapixel PNG through). `Image.MAX_IMAGE_PIXELS` is also lowered as a
   second layer so any decode anywhere raises rather than exhausting memory.
"""
import io
import os

from fastapi import HTTPException
from PIL import Image

# Bound the pixels we will ever decode. ~100 MP covers A4@600dpi and high-res phone
# photos while blocking the gigapixel bombs. Overridable for unusual deployments.
MAX_IMAGE_PIXELS = int(os.getenv("MAX_IMAGE_PIXELS", str(100_000_000)))
# Second layer: make Pillow itself refuse to decode beyond the cap anywhere.
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

ALLOWED_DOC_MIMES = frozenset({
    "image/png", "image/jpeg", "image/webp", "image/gif", "application/pdf",
})


def sniff_mime(data: bytes) -> str | None:
    """Return the real MIME type from magic bytes, or None if unrecognized.
    Covers exactly the document types the pipeline accepts."""
    if not data:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:5] == b"%PDF-":
        return "application/pdf"
    return None


def validate_upload(data: bytes, declared_ct: str | None,
                    allowed: frozenset = ALLOWED_DOC_MIMES) -> str:
    """Validate an uploaded document and return its REAL content type (from magic
    bytes) for downstream use. Raises:
      - 415 if the real type isn't recognized / not allowed (ignores the header),
      - 400 if an image is malformed / unreadable,
      - 413 if an image's dimensions exceed MAX_IMAGE_PIXELS (bomb protection).
    """
    real = sniff_mime(data)
    if real is None or real not in allowed:
        raise HTTPException(
            415,
            "unsupported or unrecognized file type — allowed: PNG, JPEG, WEBP, "
            "GIF, PDF (checked by file signature, not the declared type)",
        )
    if real.startswith("image/"):
        try:
            with Image.open(io.BytesIO(data)) as img:
                w, h = img.size          # header read only — no pixel decode
        except Exception:                # noqa: BLE001 — malformed/hostile image
            raise HTTPException(400, "the image is malformed or unreadable")
        if w * h > MAX_IMAGE_PIXELS:
            raise HTTPException(
                413,
                f"image is too large to process safely ({w}x{h} pixels); "
                f"the limit is {MAX_IMAGE_PIXELS:,} pixels",
            )
    return real
