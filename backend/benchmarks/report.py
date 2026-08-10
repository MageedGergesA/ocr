"""Render a RunResult (dict) into human + machine reports."""
from __future__ import annotations

import csv
import io


def _pct(x):
    return "n/a" if x is None else f"{x * 100:.1f}%"


def render_markdown(rr: dict) -> str:
    a = rr.get("aggregate", {})
    L = []
    L.append(f"# Benchmark run `{rr.get('run_id')}`")
    L.append("")
    L.append(f"- dataset: `{rr.get('dataset_version')}` ({rr.get('dataset_provenance')})")
    L.append(f"- model: `{rr.get('model_id')}`  · mode: `{rr.get('mode')}`  · "
             f"prompt: `{rr.get('prompt_version')}`  · schema: `{rr.get('schema_version')}`")
    L.append(f"- git: `{rr.get('git_sha')}`  · cases: {rr.get('n_cases')}  · "
             f"scored: {a.get('n_scored')}")
    L.append("")
    L.append("## Overall")
    L.append(f"- normalized field accuracy: **{_pct(a.get('normalized_accuracy'))}**")
    L.append(f"- exact field accuracy: {_pct(a.get('exact_accuracy'))}")
    L.append(f"- precision / recall / F1: {_pct(a.get('precision'))} / "
             f"{_pct(a.get('recall'))} / {_pct(a.get('f1'))}")
    L.append(f"- missing / hallucinated: {_pct(a.get('missing_rate'))} / "
             f"{_pct(a.get('hallucinated_rate'))}")
    L.append(f"- document-level error rate: {_pct(a.get('doc_error_rate'))}")
    cal = rr.get("calibration") or {}
    if cal.get("n"):
        L.append(f"- confidence: ECE={cal.get('ece'):.3f} Brier={cal.get('brier'):.3f} "
                 f"(n={cal['n']})")
    for dim in ("country", "doc_type", "language", "difficulty"):
        sl = (rr.get("slices") or {}).get(dim) or {}
        if sl:
            L.append("")
            L.append(f"## By {dim}")
            for k, v in sl.items():
                L.append(f"- {k}: {_pct(v['normalized_accuracy'])} (n={v['n']})")
    # error taxonomy
    hist: dict[str, int] = {}
    for cr in rr.get("cases", []):
        for cat, n in (cr.get("error_histogram") or {}).items():
            hist[cat] = hist.get(cat, 0) + n
    if hist:
        L.append("")
        L.append("## Errors by category")
        for cat, n in sorted(hist.items(), key=lambda kv: -kv[1]):
            L.append(f"- {cat}: {n}")
    if rr.get("warnings"):
        L.append("")
        L.append("## Warnings")
        for w in rr["warnings"]:
            L.append(f"- {w}")
    return "\n".join(L) + "\n"


def render_cases_csv(rr: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["case_id", "country", "doc_type", "language", "doc_error",
                "normalized_accuracy", "precision", "recall", "missing_rate",
                "hallucinated_rate", "errors"])
    for cr in rr.get("cases", []):
        fm = cr.get("field_metrics") or {}
        w.writerow([cr["case_id"], cr["country"], cr["doc_type"], cr["language"],
                    cr["doc_error"], fm.get("normalized_accuracy"),
                    fm.get("precision"), fm.get("recall"), fm.get("missing_rate"),
                    fm.get("hallucinated_rate"),
                    ";".join(f"{k}:{v}" for k, v in (cr.get("error_histogram") or {}).items())])
    return buf.getvalue()
