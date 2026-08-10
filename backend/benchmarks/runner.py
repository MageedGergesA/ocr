"""Benchmark runner: score a dataset, aggregate, slice, and persist a run.

Two modes:
  - REPLAY: score pre-recorded predictions {case_id: result}. Fully offline and
    deterministic — this is what the tests and CI use.
  - LIVE: call a provider callable per case. Gated by an explicit flag + cost caps
    in the CLI; the runner itself just invokes the callable you pass in.

Cost safety: `max_docs` caps how many cases run; `dry_run` returns the plan without
executing anything.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional

from benchmarks import manifest, metrics, taxonomy

# Bounded work profiles (Section 26): (max_docs, repeats).
PROFILES = {"smoke": (3, 1), "standard": (50, 1), "full": (10_000, 3)}


@dataclass
class CaseResult:
    case_id: str
    country: str
    doc_type: str
    language: str
    difficulty: list
    doc_error: str
    field_metrics: Optional[dict]
    error_histogram: dict
    latency_ms: Optional[float] = None


@dataclass
class RunResult:
    run_id: str
    dataset_version: str
    dataset_provenance: str
    model_id: str
    model_config: dict
    prompt_version: str
    schema_version: str
    preprocess_version: str
    git_sha: str
    mode: str
    n_cases: int
    aggregate: dict
    slices: dict
    calibration: dict
    classification: dict
    cases: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def _slice_accuracy(case_results: list, attr: str) -> dict:
    groups: dict[str, list] = {}
    for cr in case_results:
        if not cr.field_metrics:
            continue
        keys = cr.difficulty if attr == "difficulty" else [getattr(cr, attr) or "unknown"]
        for k in (keys or ["untagged"]):
            groups.setdefault(k, []).append(cr.field_metrics["normalized_accuracy"])
    return {k: {"n": len(v), "normalized_accuracy": sum(v) / len(v)}
            for k, v in sorted(groups.items())}


def run(dataset: manifest.Dataset, *, run_id: str, model_id: str,
        predictions: Optional[dict] = None,
        live_provider: Optional[Callable[[manifest.Case], dict]] = None,
        model_config: Optional[dict] = None, prompt_version: str = "",
        schema_version: str = "", preprocess_version: str = "pp-1",
        git_sha: str = "", max_docs: Optional[int] = None,
        dry_run: bool = False) -> Any:
    """Run the benchmark. Provide `predictions` for REPLAY or `live_provider` for
    LIVE. Returns a RunResult (or, for dry_run, a plan dict)."""
    cases = dataset.cases[: max_docs] if max_docs else dataset.cases
    mode = "replay" if predictions is not None else ("live" if live_provider else "none")
    if dry_run:
        return {"dry_run": True, "mode": mode, "n_cases": len(cases),
                "dataset_version": dataset.version, "model_id": model_id,
                "case_ids": [c.id for c in cases]}
    if mode == "none":
        raise ValueError("provide predictions (replay) or live_provider (live)")

    case_results: list[CaseResult] = []
    conf_pairs: list[tuple] = []
    class_pairs: list[tuple] = []
    warnings: list[str] = []

    for c in cases:
        doc_error = "ok"
        result = None
        try:
            if mode == "replay":
                if c.id not in predictions:
                    doc_error = "read_failure"
                    warnings.append(f"no prediction for case {c.id}")
                else:
                    result = predictions[c.id]
            else:
                result = live_provider(c)
        except Exception as e:  # noqa: BLE001
            doc_error = "provider_refusal"
            warnings.append(f"{c.id}: {type(e).__name__}: {e}")

        fm_dict = None
        hist: dict[str, int] = {}
        if result is not None and doc_error == "ok":
            fm = metrics.score_fields(c.truth, result, c.field_types)
            fm_dict = _fm_to_dict(fm)
            for fr in fm.per_field:
                cat = taxonomy.classify_field_error(fr.outcome, fr.ftype,
                                                    fr.expected, fr.predicted)
                if cat != "none":
                    hist[cat] = hist.get(cat, 0) + 1
                if fr.confidence is not None:
                    conf_pairs.append((fr.confidence, 1 if fr.outcome == "correct" else 0))
            # classification (predicted doc_type if the result carries one)
            if c.expected_doc_type:
                pred_dt = _predicted_doc_type(result)
                class_pairs.append((c.expected_doc_type, pred_dt or "unknown"))

        case_results.append(CaseResult(
            case_id=c.id, country=c.country, doc_type=c.doc_type,
            language=c.language, difficulty=c.difficulty, doc_error=doc_error,
            field_metrics=fm_dict, error_histogram=hist))

    scored = [cr for cr in case_results if cr.field_metrics]
    agg = _aggregate(scored)
    agg["doc_error_rate"] = (
        sum(1 for cr in case_results if cr.doc_error != "ok") / len(case_results)
        if case_results else 0.0)
    return RunResult(
        run_id=run_id, dataset_version=dataset.version,
        dataset_provenance=dataset.provenance, model_id=model_id,
        model_config=model_config or {}, prompt_version=prompt_version,
        schema_version=schema_version, preprocess_version=preprocess_version,
        git_sha=git_sha, mode=mode, n_cases=len(case_results), aggregate=agg,
        slices={"country": _slice_accuracy(case_results, "country"),
                "doc_type": _slice_accuracy(case_results, "doc_type"),
                "language": _slice_accuracy(case_results, "language"),
                "difficulty": _slice_accuracy(case_results, "difficulty")},
        calibration=metrics.calibration(conf_pairs),
        classification=metrics.classification_metrics(class_pairs) if class_pairs else {},
        cases=[asdict(cr) for cr in case_results], warnings=warnings)


def _fm_to_dict(fm) -> dict:
    d = {k: getattr(fm, k) for k in ("exact_accuracy", "normalized_accuracy",
         "precision", "recall", "f1", "missing_rate", "hallucinated_rate",
         "n_expected_present", "n_expected_absent")}
    return d


def _aggregate(scored: list) -> dict:
    if not scored:
        return {"n_scored": 0, "normalized_accuracy": None, "exact_accuracy": None,
                "precision": None, "recall": None, "f1": None}
    def mean(k):
        return sum(cr.field_metrics[k] for cr in scored) / len(scored)
    return {"n_scored": len(scored),
            "exact_accuracy": mean("exact_accuracy"),
            "normalized_accuracy": mean("normalized_accuracy"),
            "precision": mean("precision"), "recall": mean("recall"),
            "f1": mean("f1"), "missing_rate": mean("missing_rate"),
            "hallucinated_rate": mean("hallucinated_rate")}


def _predicted_doc_type(result) -> Optional[str]:
    if isinstance(result, dict):
        return result.get("document_type") or result.get("doc_type")
    return None


def save_run(rr: RunResult, out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{rr.run_id}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(asdict(rr), fh, ensure_ascii=False, indent=2, default=str)
    return path
