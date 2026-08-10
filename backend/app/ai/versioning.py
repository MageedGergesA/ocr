"""Prompt / schema / preprocessing versioning for reproducibility.

Every benchmarkable extraction must be attributable to the exact prompt and schema
that produced it, so we can later answer: "did accuracy change because of the model,
the prompt, or the schema?" We identify each by a short stable hash (content-
addressed) plus a human-readable family/version label — no need to store the full
blob when a reference suffices.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

# Bump when the preprocessing pipeline (resize/EXIF/re-encode) changes in a way
# that could affect model input — recorded per extraction so coordinates/quality
# comparisons stay honest across pipeline changes.
PREPROCESS_VERSION = "pp-1"


def _stable_hash(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def prompt_version(family: str, template_text: str) -> str:
    """A stable id for a prompt: '<family>@<hash>'. `family` is the human label
    (e.g. 'extract_auto', 'prescription'); the hash pins the exact template text."""
    return f"{family}@{_stable_hash(template_text or '')}"


def schema_version(schema: Any) -> str:
    """A stable id for a target schema: 'schema@<hash>' over a canonical JSON form
    (sorted keys) so equivalent schemas hash identically regardless of key order."""
    try:
        canon = json.dumps(schema, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        canon = str(schema)
    return f"schema@{_stable_hash(canon)}"


def requested_fields(schema: Any) -> list[str]:
    """Best-effort list of the field names a schema requests (top-level keys),
    recorded so a benchmark can attribute per-field results to the schema."""
    if isinstance(schema, dict):
        return sorted(str(k) for k in schema.keys())
    return []
