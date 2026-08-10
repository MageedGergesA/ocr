"""P0.8 — untrusted-upload hardening: magic-byte typing + decompression-bomb guard.

Regression for the discovery findings: content-type was trusted from the client
(no magic-byte check), there was no Image.MAX_IMAGE_PIXELS cap, and the <200 KB
preprocessing bypass let a small gigapixel image skip the size guard entirely.
"""
import io

import pytest
from fastapi import HTTPException
from PIL import Image

from app import uploads


def _png(w=8, h=8) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg(w=8, h=8) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (0, 128, 0)).save(buf, format="JPEG")
    return buf.getvalue()


_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def test_valid_types_detected_by_magic_bytes():
    assert uploads.validate_upload(_png(), "image/png") == "image/png"
    assert uploads.validate_upload(_jpeg(), "image/jpeg") == "image/jpeg"
    assert uploads.validate_upload(_PDF, "application/pdf") == "application/pdf"


def test_declared_type_is_ignored_in_favor_of_magic_bytes():
    # A real PNG uploaded as 'application/pdf' is still typed PNG (we don't trust
    # the header); a real PDF uploaded as 'image/png' is typed PDF.
    assert uploads.validate_upload(_png(), "application/pdf") == "image/png"
    assert uploads.validate_upload(_PDF, "image/png") == "application/pdf"


def test_unrecognized_bytes_rejected():
    with pytest.raises(HTTPException) as ei:
        uploads.validate_upload(b"this is not a document", "image/png")
    assert ei.value.status_code == 415


def test_executable_renamed_as_pdf_rejected():
    # An ELF binary with a .pdf name / pdf content-type must not pass.
    elf = b"\x7fELF" + b"\x00" * 64
    with pytest.raises(HTTPException) as ei:
        uploads.validate_upload(elf, "application/pdf")
    assert ei.value.status_code == 415


def test_malformed_image_rejected():
    # Valid PNG magic but truncated/garbage body → unreadable image → 400.
    fake = b"\x89PNG\r\n\x1a\n" + b"\x00\x01\x02\x03garbage"
    with pytest.raises(HTTPException) as ei:
        uploads.validate_upload(fake, "image/png")
    assert ei.value.status_code == 400


def test_oversized_dimensions_rejected_before_decode(monkeypatch):
    # Lower the cap so a modest real image trips the dimension guard deterministically
    # (proving the check happens on header dimensions, not file size).
    monkeypatch.setattr(uploads, "MAX_IMAGE_PIXELS", 100)   # 10x10
    with pytest.raises(HTTPException) as ei:
        uploads.validate_upload(_png(50, 50), "image/png")  # 2500 px > 100
    assert ei.value.status_code == 413


def test_pillow_global_cap_is_lowered():
    # Second layer: Pillow itself won't decode beyond the configured cap.
    assert Image.MAX_IMAGE_PIXELS == uploads.MAX_IMAGE_PIXELS


def test_demo_endpoint_rejects_garbage_upload(client):
    """End-to-end: a garbage upload is rejected by the guard before any model call."""
    r = client.post("/v1/demo-extract",
                    files={"file": ("x.png", b"not a real image", "image/png")})
    assert r.status_code == 415, r.text
