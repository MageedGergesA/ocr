"""Wraps a raw extraction result in the canonical Mostakhles response envelope.

The envelope is additive — every key the legacy `/v1/extract` response already
returns (`document_type`, `layout`, `data`, `usage`) is preserved exactly. We
add:

  - `language`     : detected primary/secondary languages with confidence
  - `summary`      : one-sentence human-readable description (hoisted from data)
  - `validations`  : checksum + format validations (TIN, IBAN, MRZ, national-ID)
  - `confidence`   : aggregate (total / high / review / low / overall)
  - `warnings`     : free-text notes the model emitted
  - `extracted_at` : ISO 8601 timestamp set by the caller
  - `_meta`        : model / tier / duration_ms / credits_charged / request_id

This module is pure: it takes the raw extracted `data` dict and returns a new
dict. The caller decides whether to also apply `normalize.apply_normalization`
in-place on the data tree (recommended).
"""
from __future__ import annotations

from . import normalize, validators


def _detect_language(data: dict) -> dict | None:
    """If the extracted data carries a `language` field, hoist it. Otherwise
    leave it absent — better to omit than to lie about the model's confidence.
    """
    if not isinstance(data, dict):
        return None
    lang = data.get("language") or data.get("اللغة")
    if isinstance(lang, dict):
        return lang
    if isinstance(lang, str):
        return {"primary": lang}
    return None


def _extract_summary(data: dict) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in ("summary", "ملخص", "summary_text"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _extract_warnings(data: dict) -> list[str]:
    if not isinstance(data, dict):
        return []
    notes = data.get("warnings") or data.get("notes") or data.get("ملاحظات")
    if isinstance(notes, list):
        return [str(n) for n in notes if n]
    if isinstance(notes, str):
        return [notes]
    return []


def wrap_extraction(
    *,
    raw_data,
    document_type: str | None,
    layout: str | None,
    output_lang: str,
    files_count: int,
    usage: dict,
    duration_ms: int,
    model: str = "gemini",
    tier: str = "explicit",
    request_id: str | None = None,
    extracted_at_iso: str,
    extra_warnings: list[str] | None = None,
    normalize_in_place: bool = True,
) -> dict:
    """Return the canonical response envelope. `raw_data` is mutated when
    `normalize_in_place=True` to add `value_iso` / `amount` siblings on
    date- and amount-shaped cells.
    """
    if isinstance(raw_data, dict) and normalize_in_place:
        normalize.apply_normalization(raw_data)

    body = {
        "document_type": document_type,
        "layout": layout,
        "output_lang": output_lang,
        "files_count": files_count,
        "data": raw_data,                    # back-compat
        "usage": usage,                       # back-compat
        # --- NEW envelope fields (additive) ---
        "language": _detect_language(raw_data) if isinstance(raw_data, dict) else None,
        "summary": _extract_summary(raw_data) if isinstance(raw_data, dict) else None,
        "validations": validators.collect_validations(raw_data) if isinstance(raw_data, dict) else [],
        "confidence": normalize.aggregate_confidence(raw_data),
        "warnings": _extract_warnings(raw_data) + (extra_warnings or []),
        "extracted_at": extracted_at_iso,
        "_meta": {
            "model": model,
            "tier": tier,
            "duration_ms": duration_ms,
            "credits_charged": usage.get("charged") if isinstance(usage, dict) else None,
            "request_id": request_id,
        },
    }
    return body
