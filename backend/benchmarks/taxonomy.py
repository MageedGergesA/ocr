"""Benchmark error taxonomy — classify WHY a field failed, so we know what to fix."""
from __future__ import annotations

import re

from benchmarks import canon

# Pipeline-level failure classes (whole-document), set by the runner.
DOC_ERRORS = (
    "provider_timeout", "provider_refusal", "parse_error", "schema_failure",
    "read_failure", "wrong_classification", "ok",
)


def classify_field_error(outcome: str, ftype: str, expected, predicted) -> str:
    """Map a scored field to an error category (Section 37)."""
    if outcome == "correct":
        return "none"
    if outcome == "missing":
        return "missed_field"
    if outcome == "hallucinated":
        return "hallucinated_field"
    # outcome == "wrong"
    if ftype == "date":
        return "date_confusion"
    if ftype == "amount":
        return "amount_confusion"
    if ftype == "currency":
        return "currency_confusion"
    if ftype == "id":
        return "identifier_error"
    e = canon.normalize_text(expected)
    p = canon.normalize_text(predicted)
    # Digit-only difference → likely a digit-confusion (e.g. Arabic-Indic misread).
    if re.sub(r"\d", "", e) == re.sub(r"\d", "", p) and e != p:
        return "digit_confusion"
    # Same ASCII skeleton, differs only in Arabic letters/diacritics → spelling.
    if any("؀" <= ch <= "ۿ" for ch in e + p):
        return "arabic_spelling"
    return "wrong_value"
