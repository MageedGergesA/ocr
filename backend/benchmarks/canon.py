"""Benchmark-only canonicalization for fair comparison.

Two levels are offered per field so results are never inflated by over-normalization:
  - the EXACT level trims surrounding whitespace only;
  - the NORMALIZED level applies conservative, documented transforms
    (Unicode NFKC, Arabic/Persian digit folding, whitespace collapse, safe
     punctuation) plus type-aware canonical forms for dates / amounts / currencies /
     identifiers / booleans.

Deliberately independent of app.services.normalize so we don't grade with the same
code that produces the answer. Aggressive folding (e.g. dropping Arabic diacritics)
is OFF by default so a wrong answer cannot be normalized into a right one.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

_AR_INDIC = "٠١٢٣٤٥٦٧٨٩"
_FA_INDIC = "۰۱۲۳۴۵۶۷۸۹"
_DIGIT_MAP = {ord(c): str(i) for i, c in enumerate(_AR_INDIC)}
_DIGIT_MAP.update({ord(c): str(i) for i, c in enumerate(_FA_INDIC)})


def fold_digits(s: str) -> str:
    return (s or "").translate(_DIGIT_MAP)


def normalize_text(s, *, fold_case: bool = False) -> str:
    """Conservative text canonicalization: NFKC, digit fold, whitespace collapse."""
    if s is None:
        return ""
    out = unicodedata.normalize("NFKC", str(s))
    out = fold_digits(out)
    out = re.sub(r"\s+", " ", out).strip()
    if fold_case:
        out = out.lower()
    return out


def exact_text(s) -> str:
    return "" if s is None else str(s).strip()


# --- Dates ----------------------------------------------------------------
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"])}
_MONTHS.update({m[:3]: i + 1 for m, i in list(_MONTHS.items())})


def canon_date(s) -> str | None:
    """Return an ISO 'YYYY-MM-DD' canonical form, or None if not confidently a date.
    Handles ISO, D/M/Y and Y/M/D numeric, and 'D Month YYYY' (English). Day-first
    for ambiguous numeric forms (MENA convention). Returns None on impossible dates
    so a wrong value cannot pass as a date."""
    t = fold_digits(normalize_text(s))
    if not t:
        return None
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", t)
    if m:
        return _iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$", t)
    if m:
        return _iso(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.match(r"^(\d{1,2})\s+([a-zA-Z]+)\s+(\d{4})$", t)
    if m and m.group(2).lower() in _MONTHS:
        return _iso(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
    return None


def _iso(y, mo, d) -> str | None:
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    from calendar import monthrange
    try:
        if d > monthrange(y, mo)[1]:
            return None
    except Exception:  # noqa: BLE001
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


# --- Amounts --------------------------------------------------------------
def canon_amount(s) -> str | None:
    """Return a canonical decimal string (no grouping) or None. Handles both
    '1,234.56' and European '1.234,56'."""
    t = fold_digits(normalize_text(s))
    # Arabic decimal (U+066B) / thousands (U+066C) separators → ASCII equivalents.
    t = t.replace("٫", ".").replace("٬", ",")
    t = re.sub(r"[^\d.,\-]", "", t)
    if not t or t in ("-", ".", ","):
        return None
    if "," in t and "." in t:
        # last separator is the decimal one
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        parts = t.split(",")
        if len(parts[-1]) == 2 and all(len(p) == 3 for p in parts[1:-1] if p):
            t = t.replace(",", ".")     # decimal comma
        else:
            t = t.replace(",", "")      # thousands
    try:
        return str(Decimal(t).normalize())
    except (InvalidOperation, ValueError):
        return None


# --- Currency -------------------------------------------------------------
_CUR = {
    "$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR", "£": "GBP", "gbp": "GBP",
    "egp": "EGP", "ج.م": "EGP", "جنيه": "EGP", "sar": "SAR", "ر.س": "SAR",
    "aed": "AED", "د.إ": "AED", "kwd": "KWD", "bhd": "BHD", "qar": "QAR",
    "omr": "OMR", "jod": "JOD",
}


def canon_currency(s) -> str | None:
    t = normalize_text(s, fold_case=True)
    if not t:
        return None
    if t.upper() in {"USD", "EUR", "GBP", "EGP", "SAR", "AED", "KWD", "BHD",
                     "QAR", "OMR", "JOD"}:
        return t.upper()
    for k, v in _CUR.items():
        if k in t:
            return v
    return None


# --- Identifiers ----------------------------------------------------------
def canon_id(s) -> str:
    """Strip separators/whitespace and uppercase — for IBAN/VAT/TRN/national ids."""
    return re.sub(r"[\s\-]", "", fold_digits(normalize_text(s))).upper()


# --- Booleans -------------------------------------------------------------
_TRUE = {"true", "yes", "1", "y", "نعم", "صح", "صحيح"}
_FALSE = {"false", "no", "0", "n", "لا", "خطأ", "غير صحيح"}


def canon_bool(s):
    t = normalize_text(s, fold_case=True)
    if t in _TRUE:
        return True
    if t in _FALSE:
        return False
    return None


# --- Dispatch -------------------------------------------------------------
_CANON = {
    "text": normalize_text,
    "date": canon_date,
    "amount": canon_amount,
    "currency": canon_currency,
    "id": canon_id,
    "bool": canon_bool,
}


def canonicalize(value, field_type: str = "text"):
    """Canonicalize `value` for the given field type. Unknown types fall back to
    text. Returns None where the value can't be confidently canonicalized (so a
    junk value doesn't compare equal to a valid one)."""
    fn = _CANON.get(field_type or "text", normalize_text)
    return fn(value)
