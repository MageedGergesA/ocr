"""Phase 1B §2+§4 — pre-run cost/volume estimate, verify CLI, and cost gates.

All offline: a dry-run is a free cost PREVIEW; a real live run is refused without
--allow-cost; verify never claims availability it could not check.
"""
import json

from benchmarks import estimate, manifest, runner
from benchmarks import __main__ as cli


DATASET = "benchmarks/datasets/mena_v0/manifest.json"


def test_estimate_scales_with_repeats_and_models():
    e1 = estimate.estimate_plan(n_cases=10, total_pages=12, repeats=1,
                                model_ids=["gemini-3.5-flash"])
    e3 = estimate.estimate_plan(n_cases=10, total_pages=12, repeats=3,
                                model_ids=["gemini-3.5-flash"])
    assert e1["requests_per_model"] == 10
    assert e3["requests_per_model"] == 30
    # 3x repeats ≈ 3x cost
    assert e3["estimated_usd_total"] > e1["estimated_usd_total"]
    assert abs(e3["estimated_usd_total"] - 3 * e1["estimated_usd_total"]) < 1e-3
    # matrix sums models
    matrix = estimate.estimate_plan(n_cases=10, total_pages=12, repeats=1,
                                    model_ids=["gemini-3.5-flash", "gemini-3.6-flash"])
    assert matrix["requests_total"] == 20


def test_estimate_never_invents_price_for_unknown_model():
    e = estimate.estimate_plan(n_cases=5, total_pages=5, repeats=1,
                               model_ids=["gemini-does-not-exist"])
    assert e["per_model"][0]["usd"] is None
    assert e["estimated_usd_total"] is None  # not zero — unknown


def test_estimate_flags_pricing_unverified():
    e = estimate.estimate_plan(n_cases=1, total_pages=1, repeats=1,
                               model_ids=["gemini-3.5-flash"])
    assert e["pricing_verified"] is False
    assert "UNVERIFIED" in e["assumptions"]


def test_live_dry_run_prices_matrix_without_spending():
    ds = manifest.load_dataset(DATASET)
    plan = runner.run(ds, run_id="dry", model_id="unknown",
                      live_provider=lambda c: {}, dry_run=True, repeats=1,
                      estimate_model_ids=["gemini-3.5-flash"])
    assert plan["dry_run"] is True
    assert plan["mode"] == "live"
    assert plan["estimate"]["estimated_usd_total"] is not None


def test_replay_dry_run_costs_nothing():
    ds = manifest.load_dataset(DATASET)
    plan = runner.run(ds, run_id="dry", model_id="x",
                      predictions={}, dry_run=True)
    assert plan["mode"] == "replay"
    assert "0 provider spend" in plan["estimate"]["note"]


def test_cli_refuses_live_without_allow_cost(capsys):
    rc = cli.main(["run", "--dataset", DATASET, "--live"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "allow-cost" in err


def test_cli_live_dry_run_is_free(capsys):
    rc = cli.main(["run", "--dataset", DATASET, "--live", "--dry-run",
                   "--profile", "standard"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "live"
    assert out["estimate"]["requests_per_model"] == out["n_cases"]


def test_cli_verify_offline_is_honest(capsys, monkeypatch):
    from app.services import llm
    monkeypatch.setattr(llm, "is_configured", lambda: False)
    rc = cli.main(["verify", "--models", "gemini-3.6-flash"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["client_configured"] is False
    assert out["availability"]["gemini-3.6-flash"] is False
    assert "GEMINI_API_KEY" in out["note"]
