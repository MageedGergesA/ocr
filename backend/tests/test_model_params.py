"""Phase 1B §3 — generation-parameter regression.

Newer Gemini models (gemini-3.5-flash-lite, gemini-3.6-flash) deprecate the
sampling knobs temperature / top_p / top_k. These tests prove that:

  1. the registry declares the reduced param set for those models,
  2. effective_generation_config() strips the deprecated params for them,
  3. the CURRENT production models are UNCHANGED (byte-identical request), and
  4. the production llm.py path routes its config through the registry filter.

All deterministic — no live model calls.
"""
import pytest

from app.ai import registry


NEW_GEN = ["gemini-3.5-flash-lite", "gemini-3.6-flash"]
LEGACY = ["gemini-3.1-flash-lite", "gemini-3.5-flash"]

REQUESTED = {"max_output_tokens": 8192, "temperature": 0.0, "top_p": 1.0, "seed": 42}


@pytest.mark.parametrize("mid", NEW_GEN)
def test_new_models_drop_sampling_knobs(mid):
    eff = registry.effective_generation_config(mid, REQUESTED)
    assert "temperature" not in eff
    assert "top_p" not in eff
    assert "top_k" not in eff
    # useful params survive
    assert eff["max_output_tokens"] == 8192
    assert eff["seed"] == 42


@pytest.mark.parametrize("mid", LEGACY)
def test_legacy_models_keep_all_params(mid):
    eff = registry.effective_generation_config(mid, REQUESTED)
    # current production behaviour must be unchanged
    assert eff == REQUESTED


def test_unknown_new_model_still_stripped_by_fallback():
    # A model not yet in the registry but on the deprecation list is still handled.
    eff = registry.effective_generation_config("gemini-3.6-flash", dict(REQUESTED))
    assert "temperature" not in eff


def test_registry_spec_declares_reduced_params():
    for mid in NEW_GEN:
        spec = registry.get(mid)
        assert spec is not None
        assert "temperature" not in spec.supported_params
        assert "top_p" not in spec.supported_params
    for mid in LEGACY:
        spec = registry.get(mid)
        assert spec is not None
        assert "temperature" in spec.supported_params
        assert "top_p" in spec.supported_params


def test_verify_generation_params_offline_is_honest(monkeypatch):
    # No client configured → static list stands but is flagged UNVERIFIED (never
    # silently reported as confirmed). Pin is_configured=False so the assertion is
    # deterministic regardless of what earlier tests configured.
    from app.services import llm
    monkeypatch.setattr(llm, "is_configured", lambda: False)
    out = registry.verify_generation_params("gemini-3.6-flash")
    assert out["model_id"] == "gemini-3.6-flash"
    assert out["static"] == ["seed", "max_output_tokens"]
    assert out["checked"] is False
    assert out["runtime"] is None
    assert out["agrees"] is None
    assert "UNVERIFIED" in out["note"] or "unavailable" in out["note"]


def test_llm_path_uses_registry_filter(monkeypatch):
    """The production multimodal path must build its GenerateContentConfig through
    effective_generation_config, so a param-deprecating model never receives
    temperature/top_p. We capture the kwargs the config is built with."""
    from app.services import llm

    seen = {}
    real_eff = registry.effective_generation_config

    def fake_eff(model, requested):
        seen["model"] = model
        seen["requested"] = dict(requested)
        return real_eff(model, requested)

    # Route llm through a param-deprecating model and capture the effective config.
    monkeypatch.setattr(registry, "effective_generation_config", fake_eff)
    monkeypatch.setattr(llm, "GEMINI_HARD", "gemini-3.6-flash")
    monkeypatch.setattr(llm, "GEMINI_EASY", "gemini-3.6-flash")

    captured = {}

    def fake_generate(*, _credits, model, contents, config):
        captured["config"] = config

        class _R:
            text = "{}"
            candidates = []
        return _R()

    monkeypatch.setattr(llm, "_generate", fake_generate)
    monkeypatch.setattr(llm, "enforce_daily_budget", lambda *a, **k: None)

    llm.generate_from_documents([(b"x", "image/png")], "prompt", hard=True)

    assert seen["model"] == "gemini-3.6-flash"
    # The config actually sent must not carry the deprecated knobs.
    cfg = captured["config"]
    assert getattr(cfg, "temperature", None) is None
    assert getattr(cfg, "top_p", None) is None
    assert getattr(cfg, "seed", None) == 42
