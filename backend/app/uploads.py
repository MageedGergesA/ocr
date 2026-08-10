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
import zipfile

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


# --- Template uploads (xlsx / docx / pdf / html) --------------------------
# Office documents are ZIP archives, so they carry the zip-bomb / archive-abuse
# risks that a plain image doesn't. These bounds are checked from the archive's
# CENTRAL DIRECTORY (metadata) — nothing is decompressed — so a bomb that DECLARES
# a huge uncompressed size is rejected without ever expanding it.
_ZIP_MAGIC = b"PK\x03\x04"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0"      # legacy .doc/.xls (OLE compound) — not zip-bomb-prone
_OFFICE_MIMES = frozenset({
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
})
_HTML_MIMES = frozenset({"text/html", "application/xhtml+xml"})

MAX_TEMPLATE_ENTRIES = int(os.getenv("MAX_TEMPLATE_ENTRIES", "2000"))
MAX_TEMPLATE_UNCOMPRESSED = int(os.getenv("MAX_TEMPLATE_UNCOMPRESSED",
                                          str(200 * 1024 * 1024)))   # 200 MB
MAX_TEMPLATE_RATIO = int(os.getenv("MAX_TEMPLATE_RATIO", "200"))     # bomb ratio


def _check_office_archive(data: bytes) -> None:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
    except Exception:  # noqa: BLE001 — not a valid zip / corrupt central directory
        raise HTTPException(400, "the Office document is malformed or unreadable")
    if len(infos) > MAX_TEMPLATE_ENTRIES:
        raise HTTPException(413, "template archive has too many entries "
                                 f"(> {MAX_TEMPLATE_ENTRIES}); refusing to process")
    total = sum(max(0, i.file_size) for i in infos)
    if total > MAX_TEMPLATE_UNCOMPRESSED:
        raise HTTPException(413, "template archive expands too large "
                                 f"(> {MAX_TEMPLATE_UNCOMPRESSED:,} bytes)")
    comp = sum(max(0, i.compress_size) for i in infos) or 1
    if total / comp > MAX_TEMPLATE_RATIO:
        raise HTTPException(413, "template archive compression ratio is suspicious "
                                 "(possible zip bomb); refusing to process")


def validate_template_upload(data: bytes, declared_ct: str | None) -> None:
    """Validate a template upload against its declared type using file signatures
    plus (for Office/ZIP files) archive-metadata bomb protection. Raises 415 on a
    signature mismatch / unsupported type, 400 on a malformed archive, 413 on an
    archive that is too large / too many entries / a suspicious ratio. Narrow: it
    does NOT change how template_parser reads the file."""
    ct = (declared_ct or "").lower()
    if ct == "application/pdf":
        if data[:5] != b"%PDF-":
            raise HTTPException(415, "file signature does not match a PDF")
        return
    if ct in _OFFICE_MIMES:
        if data[:4] == _ZIP_MAGIC:
            _check_office_archive(data)
            return
        if data[:4] == _OLE_MAGIC:
            return                      # legacy binary Office — no zip-bomb vector
        raise HTTPException(415, "file signature does not match an Office document")
    if ct in _HTML_MIMES:
        # Must be text, not a disguised binary (zip/pdf/image).
        if (data[:4] in (_ZIP_MAGIC, _OLE_MAGIC) or data[:5] == b"%PDF-"
                or sniff_mime(data) is not None):
            raise HTTPException(415, "HTML template must be a text/HTML file")
        try:
            data[:8192].decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(415, "HTML template must be UTF-8 text")
        return
    raise HTTPException(415, "unsupported template type. Use .xlsx, .docx, .pdf, or .html")
