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

# Full tuning knobs we would send on a legacy-generation model.
_FULL_PARAMS = ("temperature", "top_p", "seed", "max_output_tokens")
# Reduced set for newer-generation models that DEPRECATE sampling knobs
# (temperature / top_p / top_k). Per current Gemini docs, gemini-3.5-flash-lite and
# gemini-3.6-flash reject or ignore those. This static list is a SAFE-SIDE default:
# `verify_generation_params()` reconfirms it against runtime model metadata before
# any production switch (Section 3 — "do not trust manually maintained metadata").
_REDUCED_PARAMS = ("seed", "max_output_tokens")
_PARAMS_DEPRECATED_MODELS = frozenset({
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
})


def _supported_params_for(model_id: str) -> tuple:
    return _REDUCED_PARAMS if model_id in _PARAMS_DEPRECATED_MODELS else _FULL_PARAMS


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
        supported_params=_supported_params_for(model_id),
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
    caller records the EFFECTIVE config for provenance.

    Unknown models fall back to the deprecation list directly (not just an empty
    filter) so a not-yet-registered new model still gets its sampling knobs dropped.
    """
    spec = get(model_id)
    allowed = spec.supported_params if spec else _supported_params_for(model_id)
    return {k: v for k, v in requested.items() if k in allowed}


def verify_generation_params(model_id: str) -> dict:
    """Reconfirm which generation params a model ACTUALLY accepts by querying the
    provider's runtime model metadata, rather than trusting the static table
    (Section 3). Returns:
        {"model_id", "static": [...], "runtime": [...]|None, "agrees": bool|None,
         "checked": bool, "note": str}
    - runtime is None / checked False when no client is configured (offline env):
      the static list stands, but we FLAG that it is unverified.
    - Never raises; a metadata failure is reported, not swallowed into a false OK.
    """
    static = list(_supported_params_for(model_id))
    out = {"model_id": model_id, "static": static, "runtime": None,
           "agrees": None, "checked": False, "note": ""}
    try:
        from app.services import llm
        if not llm.is_configured():
            out["note"] = "no client configured — static list UNVERIFIED"
            return out
        client = llm._client_()  # noqa: SLF001
        meta = client.models.get(model=model_id)
    except Exception as e:  # noqa: BLE001
        out["note"] = f"runtime metadata unavailable: {type(e).__name__}"
        return out
    # The SDK exposes supported params inconsistently across versions; probe the
    # common attribute names and only assert agreement when we actually read them.
    runtime = None
    for attr in ("supported_generation_methods", "supported_parameters",
                 "supported_generation_config"):
        val = getattr(meta, attr, None)
        if val:
            runtime = [str(x) for x in val]
            break
    out["checked"] = True
    if runtime is None:
        out["note"] = "model metadata exposed no param list; static list stands"
        return out
    out["runtime"] = runtime
    # Agreement: none of our static-allowed sampling knobs should be absent from
    # runtime, and we should not be sending anything runtime rejects.
    knobs = {"temperature", "top_p", "top_k"}
    static_knobs = knobs & set(static)
    runtime_knobs = knobs & set(runtime)
    out["agrees"] = static_knobs <= runtime_knobs
    if not out["agrees"]:
        out["note"] = ("MISMATCH: static allows sampling knobs the runtime does not "
                       "advertise — update _PARAMS_DEPRECATED_MODELS before switching")
    return out
