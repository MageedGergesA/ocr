"""Central model capability registry.

Replaces model-ID strings scattered across the codebase with one declarative
registry describing each model's capabilities (structured output, media, thinking,
supported generation params) and its eligibility for production vs benchmarking.

IMPORTANT:
- The PRODUCTION fast/strong model IDs come from the same env vars llm.py reads
  (GEMINI_MODEL_EASY / GEMINI_MODEL_HARD), so this registry never silently changes
  the production model. It only *describes* models and offers candidates to the
  benchmark.
- Model existence is NOT assumed just because it is listed here. `verify_availability`
  queries the Google client's model-metadata endpoint at runtime/test time.
- Pricing lives OUTSIDE this module (benchmarks/pricing.py) — capability config must
  not carry external commercial pricing.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    tier: str                       # "fast" | "strong"
    provider: str = "gemini"
    status: str = "unknown"         # "stable" | "preview" | "unknown"
    supports_structured_output: bool = True
    supports_pdf: bool = True
    supports_image: bool = True
    supports_thinking: bool = False
    default_thinking: Optional[str] = None
    # Generation params this model accepts; the request layer must not send others.
    supported_params: tuple = ("temperature", "top_p", "seed", "max_output_tokens")
    benchmark_eligible: bool = True
    production_eligible: bool = False
    notes: str = ""


def production_fast_model_id() -> str:
    return os.getenv("GEMINI_MODEL_EASY", "gemini-3.1-flash-lite")


def production_strong_model_id() -> str:
    return os.getenv("GEMINI_MODEL_HARD", "gemini-3.5-flash")


# Candidate models for the Phase-1 benchmark matrix. status='unknown' until verified
# against the account; DO NOT treat a listing here as proof a model exists.
_CANDIDATE_IDS = (
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.6-flash",
)


def _default_spec(model_id: str, tier: str, production: bool) -> ModelSpec:
    # Conservative defaults; refine per-model as capabilities are verified.
    flash_lite = "lite" in model_id
    return ModelSpec(
        model_id=model_id,
        tier=tier,
        status="unknown",
        supports_structured_output=True,
        supports_thinking=not flash_lite,
        default_thinking=None,
        benchmark_eligible=True,
        production_eligible=production,
        notes="capabilities unverified; confirm via verify_availability + a smoke run",
    )


def build_registry() -> dict[str, ModelSpec]:
    """Assemble the registry from the env-driven production models + named
    candidates. The production models are ALWAYS present and part of any comparison."""
    reg: dict[str, ModelSpec] = {}
    fast_id, strong_id = production_fast_model_id(), production_strong_model_id()
    reg[fast_id] = _default_spec(fast_id, "fast", production=True)
    reg[strong_id] = _default_spec(strong_id, "strong", production=True)
    for mid in _CANDIDATE_IDS:
        if mid in reg:
            continue
        tier = "fast" if "lite" in mid or "flash-lite" in mid else "strong"
        reg[mid] = _default_spec(mid, tier, production=False)
    return reg


REGISTRY: dict[str, ModelSpec] = build_registry()


def get(model_id: str) -> Optional[ModelSpec]:
    return REGISTRY.get(model_id)


def candidates() -> list[ModelSpec]:
    return [s for s in REGISTRY.values() if s.benchmark_eligible]


def production_specs() -> list[ModelSpec]:
    return [s for s in REGISTRY.values() if s.production_eligible]


def verify_availability(model_ids: Optional[list[str]] = None) -> dict[str, bool]:
    """Query the Google GenAI client for which candidate models the configured
    account can actually use. Returns {model_id: available}. Never raises — a model
    we can't verify is reported False (NOT silently substituted). Requires a
    configured client; without one, everything is False.
    """
    ids = model_ids or list(REGISTRY.keys())
    result = {mid: False for mid in ids}
    try:
        from app.services import llm
        if not llm.is_configured():
            return result
        client = llm._client_()  # noqa: SLF001 — internal, intentional
    except Exception:  # noqa: BLE001
        return result
    # Try a models.list() first; fall back to per-id models.get().
    listed: set[str] = set()
    try:
        for m in client.models.list():
            name = getattr(m, "name", "") or ""
            listed.add(name.split("/")[-1])
    except Exception:  # noqa: BLE001
        listed = set()
    for mid in ids:
        if mid in listed:
            result[mid] = True
            continue
        try:
            client.models.get(model=mid)
            result[mid] = True
        except Exception:  # noqa: BLE001
            result[mid] = False
    return result


def effective_generation_config(model_id: str, requested: dict) -> dict:
    """Filter a requested generation config down to the params the model supports,
    so we never send deprecated/unsupported params. Returns the filtered dict; the
    caller records the EFFECTIVE config for provenance."""
    spec = get(model_id)
    if not spec:
        return dict(requested)
    return {k: v for k, v in requested.items() if k in spec.supported_params}
