"""End-to-end benchmark harness test in REPLAY mode (no live model, no cost)."""
import json
import os

from benchmarks import manifest, runner

_DS = os.path.join(os.path.dirname(__file__), "..", "benchmarks", "datasets",
                   "mena_v0", "manifest.json")
_PRED = os.path.join(os.path.dirname(__file__), "..", "benchmarks", "datasets",
                     "mena_v0", "predictions_sample.json")


def _load():
    ds = manifest.load_dataset(_DS)
    with open(_PRED, encoding="utf-8") as fh:
        preds = json.load(fh)
    return ds, preds


def test_dataset_loads_and_stats():
    ds = manifest.load_dataset(_DS)
    assert len(ds.cases) == 4
    st = manifest.dataset_stats(ds)
    assert st["total"] == 4
    assert st["by_country"]["EG"] == 2 and st["by_country"]["SA"] == 1


def test_replay_run_scores_and_slices():
    ds, preds = _load()
    rr = runner.run(ds, run_id="t1", model_id="replay-sample", predictions=preds)
    assert rr.n_cases == 4 and rr.aggregate["n_scored"] == 4
    # Aggregate accuracy is a real fraction in (0,1) given the mixed fixture.
    assert 0.0 < rr.aggregate["normalized_accuracy"] < 1.0
    # Slices exist for every dimension.
    for dim in ("country", "doc_type", "language", "difficulty"):
        assert rr.slices[dim]
    # Calibration + classification computed.
    assert rr.calibration["n"] > 0
    assert rr.classification and 0.0 <= rr.classification["accuracy"] <= 1.0


def test_replay_catches_missing_and_wrong_and_classification():
    ds, preds = _load()
    rr = runner.run(ds, run_id="t2", model_id="replay-sample", predictions=preds)
    by_id = {c["case_id"]: c for c in rr.cases}
    # eg_receipt omitted 'total' → a missed_field error.
    assert by_id["eg_receipt_synth_01"]["error_histogram"].get("missed_field", 0) >= 1
    # ae case has a wrong date + wrong amount + wrong doc-type classification.
    ae = by_id["ae_tax_invoice_synth_01"]["error_histogram"]
    assert ae.get("date_confusion", 0) >= 1 and ae.get("amount_confusion", 0) >= 1
    # eg_tax + sa_vat fixtures are fully normalizable → 100% on those two cases.
    assert by_id["eg_tax_invoice_synth_01"]["field_metrics"]["normalized_accuracy"] == 1.0
    assert by_id["sa_vat_invoice_synth_01"]["field_metrics"]["normalized_accuracy"] == 1.0


def test_dry_run_returns_plan_without_executing():
    ds, preds = _load()
    plan = runner.run(ds, run_id="t3", model_id="x", predictions=preds,
                      max_docs=2, dry_run=True)
    assert plan["dry_run"] is True and plan["n_cases"] == 2


def test_save_run_writes_artifact(tmp_path):
    ds, preds = _load()
    rr = runner.run(ds, run_id="t4", model_id="replay-sample", predictions=preds)
    path = runner.save_run(rr, str(tmp_path))
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as fh:
        saved = json.load(fh)
    assert saved["run_id"] == "t4" and saved["aggregate"]["n_scored"] == 4
