"""LIVE benchmark provider — calls the real extraction path (costs money).

Isolated here and only invoked by the CLI under an explicit --live --allow-cost
gate. It reuses the production extractor so a benchmark measures what customers
actually get. NOT executed by tests or by default.
"""
from __future__ import annotations

import os
import time
from typing import Callable

_EXT_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".webp": "image/webp", ".gif": "image/gif", ".pdf": "application/pdf"}


def build_live_provider(dataset_root: str, *, hard: bool = True) -> Callable:
    """Return a callable(case) -> result dict. Raises if the input is missing or a
    model isn't configured — never silently substitutes."""
    from app.services import extractor, llm
    if not llm.is_configured():
        raise RuntimeError("no model configured (GEMINI_API_KEY unset) — cannot run live")

    def _provider(case) -> dict:
        path = os.path.join(dataset_root, case.input_ref)
        if not case.input_ref or not os.path.exists(path):
            raise FileNotFoundError(f"missing input for case {case.id}: {path}")
        with open(path, "rb") as fh:
            data = fh.read()
        ext = os.path.splitext(path)[1].lower()
        media = _EXT_MIME.get(ext)
        if not media:
            raise ValueError(f"unsupported input extension for {case.id}: {ext}")
        t0 = time.time()
        if case.field_types or case.truth:
            schema = {k: f"{k}" for k in (case.truth or {}).keys()}
            result = extractor.extract_schema(data, media, schema, hard=hard)
        else:
            result = extractor.extract_auto(data, media, hard=hard)
        if isinstance(result, dict):
            result.setdefault("_bench", {})["latency_ms"] = int((time.time() - t0) * 1000)
        return result

    return _provider
