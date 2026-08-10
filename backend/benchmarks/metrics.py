"""Deterministic benchmark metrics. No LLM judging of deterministic fields.

All comparisons are computable and testable. Field-level metrics compare a flat
ground-truth dict to a (possibly nested) extraction result, matching by normalized
field name. Type-aware canonicalization (benchmarks.canon) governs the NORMALIZED
level; the EXACT level trims whitespace only.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any

from benchmarks import canon


# --- result flattening ----------------------------------------------------
def _leaf_value(node: Any):
    """A result leaf is either {'value':..,'confidence':..} or a scalar."""
    if isinstance(node, dict) and "value" in node:
        return node.get("value"), node.get("confidence")
    return node, None


def flatten_fields(result: Any) -> dict[str, tuple]:
    """Map normalized field-name -> (value, confidence) over a nested result.
    Last-key-wins on collisions (matches the production learning-loop matcher)."""
    out: dict[str, tuple] = {}

    def walk(obj):
        if isinstance(obj, dict):
            if "value" in obj and not any(isinstance(v, (dict, list)) for v in obj.values()):
                return  # handled by the parent as a leaf
            for k, v in obj.items():
                val, conf = _leaf_value(v)
                if not isinstance(val, (dict, list)):
                    out[canon.normalize_text(k, fold_case=True)] = (val, conf)
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(result)
    return out


def _empty(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def _match(expected, predicted, ftype: str) -> tuple[bool, bool]:
    """Return (exact_match, normalized_match)."""
    ex = canon.exact_text(expected) == canon.exact_text(predicted)
    ce, cp = canon.canonicalize(expected, ftype), canon.canonicalize(predicted, ftype)
    norm = ce is not None and ce == cp
    return ex, norm


# --- field metrics --------------------------------------------------------
@dataclass
class FieldResult:
    field: str
    ftype: str
    expected: Any
    predicted: Any
    present: bool
    exact: bool
    normalized: bool
    outcome: str          # correct | wrong | missing | hallucinated
    confidence: Any = None


@dataclass
class FieldMetrics:
    exact_accuracy: float
    normalized_accuracy: float
    precision: float
    recall: float
    f1: float
    missing_rate: float
    hallucinated_rate: float
    n_expected_present: int
    n_expected_absent: int
    per_field: list = dc_field(default_factory=list)


def score_fields(expected: dict, predicted_result: Any,
                 field_types: dict | None = None) -> FieldMetrics:
    """Score a single document. `expected` is the ground-truth {field: value} (an
    empty/None value means the field SHOULD be absent). `field_types` maps field ->
    one of canon's types (default 'text')."""
    field_types = field_types or {}
    flat = flatten_fields(predicted_result)

    def _pred(k):
        return flat.get(canon.normalize_text(k, fold_case=True), (None, None))

    present_keys = [k for k, v in expected.items() if not _empty(v)]
    absent_keys = [k for k, v in expected.items() if _empty(v)]

    per: list[FieldResult] = []
    correct = wrong = missing = 0
    exact_hits = norm_hits = 0
    for k in present_keys:
        ftype = field_types.get(k, "text")
        pv, pconf = _pred(k)
        if _empty(pv):
            per.append(FieldResult(k, ftype, expected[k], pv, False, False, False,
                                   "missing", pconf))
            missing += 1
            continue
        ex, norm = _match(expected[k], pv, ftype)
        exact_hits += int(ex)
        norm_hits += int(norm)
        if norm:
            correct += 1
            per.append(FieldResult(k, ftype, expected[k], pv, True, ex, norm,
                                   "correct", pconf))
        else:
            wrong += 1
            per.append(FieldResult(k, ftype, expected[k], pv, True, ex, norm,
                                   "wrong", pconf))

    hallucinated = 0
    for k in absent_keys:
        pv, pconf = _pred(k)
        if not _empty(pv):
            hallucinated += 1
            per.append(FieldResult(k, field_types.get(k, "text"), expected[k], pv,
                                   True, False, False, "hallucinated", pconf))

    n_present = len(present_keys)
    tp = correct
    # A wrong value is both a false positive (bad value emitted) AND a false
    # negative (the correct value was not retrieved), so it lowers precision AND
    # recall. A missing field is a false negative; a hallucination a false positive.
    fp = wrong + hallucinated
    fn = wrong + missing
    precision = tp / (tp + fp) if (tp + fp) else (1.0 if n_present == 0 else 0.0)
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return FieldMetrics(
        exact_accuracy=exact_hits / n_present if n_present else 1.0,
        normalized_accuracy=norm_hits / n_present if n_present else 1.0,
        precision=precision, recall=recall, f1=f1,
        missing_rate=missing / n_present if n_present else 0.0,
        hallucinated_rate=hallucinated / len(absent_keys) if absent_keys else 0.0,
        n_expected_present=n_present, n_expected_absent=len(absent_keys),
        per_field=per,
    )


# --- CER / WER ------------------------------------------------------------
def _levenshtein(a: list, b: list) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(reference: str, hypothesis: str, *, normalized: bool = False) -> float:
    r = canon.normalize_text(reference) if normalized else (reference or "")
    h = canon.normalize_text(hypothesis) if normalized else (hypothesis or "")
    if not r:
        return 0.0 if not h else 1.0
    return _levenshtein(list(r), list(h)) / len(r)


def wer(reference: str, hypothesis: str, *, normalized: bool = False) -> float:
    r = canon.normalize_text(reference) if normalized else (reference or "")
    h = canon.normalize_text(hypothesis) if normalized else (hypothesis or "")
    rw, hw = r.split(), h.split()
    if not rw:
        return 0.0 if not hw else 1.0
    return _levenshtein(rw, hw) / len(rw)


# --- classification -------------------------------------------------------
def classification_metrics(pairs: list[tuple]) -> dict:
    """pairs: list of (expected_label, predicted_label). Returns accuracy, macro-F1,
    per-class precision/recall/F1, and a confusion matrix."""
    labels = sorted({e for e, _ in pairs} | {p for _, p in pairs})
    n = len(pairs)
    correct = sum(1 for e, p in pairs if e == p)
    conf = {a: {b: 0 for b in labels} for a in labels}
    for e, p in pairs:
        conf[e][p] += 1
    per = {}
    f1s = []
    for lab in labels:
        tp = conf[lab][lab]
        fp = sum(conf[o][lab] for o in labels if o != lab)
        fn = sum(conf[lab][o] for o in labels if o != lab)
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
        per[lab] = {"precision": prec, "recall": rec, "f1": f1,
                    "support": sum(conf[lab].values())}
        f1s.append(f1)
    return {
        "accuracy": correct / n if n else 0.0,
        "macro_f1": sum(f1s) / len(f1s) if f1s else 0.0,
        "per_class": per,
        "confusion": conf,
        "n": n,
    }


# --- confidence calibration ----------------------------------------------
def calibration(pairs: list[tuple], *, bins: int = 10) -> dict:
    """pairs: list of (confidence in [0,1], correct in {0,1}). Returns per-bin
    observed accuracy, Expected Calibration Error (ECE), and Brier score."""
    pts = [(_to01(c), 1 if ok else 0) for c, ok in pairs if c is not None]
    if not pts:
        return {"n": 0, "ece": None, "brier": None, "bins": []}
    edges = [i / bins for i in range(bins + 1)]
    buckets = [[] for _ in range(bins)]
    for c, ok in pts:
        idx = min(bins - 1, int(c * bins))
        buckets[idx].append((c, ok))
    n = len(pts)
    ece = 0.0
    out_bins = []
    for i, bkt in enumerate(buckets):
        if not bkt:
            out_bins.append({"lo": edges[i], "hi": edges[i + 1], "n": 0,
                             "avg_confidence": None, "accuracy": None})
            continue
        avg_conf = sum(c for c, _ in bkt) / len(bkt)
        acc = sum(ok for _, ok in bkt) / len(bkt)
        ece += (len(bkt) / n) * abs(avg_conf - acc)
        out_bins.append({"lo": edges[i], "hi": edges[i + 1], "n": len(bkt),
                         "avg_confidence": avg_conf, "accuracy": acc})
    brier = sum((c - ok) ** 2 for c, ok in pts) / n
    return {"n": n, "ece": ece, "brier": brier, "bins": out_bins}


def _to01(c) -> float:
    try:
        c = float(c)
    except (TypeError, ValueError):
        return 0.0
    return c / 100.0 if c > 1 else c


# --- tables / line items --------------------------------------------------
def table_metrics(expected_rows: list[dict], predicted_rows: list[dict],
                  key_fields: list[str], field_types: dict | None = None) -> dict:
    """Match rows by `key_fields` (order-independent) then score cells. Avoids naive
    index comparison so reordered rows still align. Returns rows/cells/missing/extra."""
    field_types = field_types or {}
    used = set()

    def _key(row):
        return tuple(canon.normalize_text(row.get(k, ""), fold_case=True) for k in key_fields)

    pred_by_key: dict[tuple, list[int]] = {}
    for i, r in enumerate(predicted_rows):
        pred_by_key.setdefault(_key(r), []).append(i)

    matched = 0
    cell_total = cell_correct = 0
    all_cols = set()
    for er in expected_rows:
        for c in er:
            all_cols.add(c)
    for er in expected_rows:
        k = _key(er)
        cands = [i for i in pred_by_key.get(k, []) if i not in used]
        if not cands:
            continue
        j = cands[0]
        used.add(j)
        matched += 1
        pr = predicted_rows[j]
        for col in er:
            cell_total += 1
            _, norm = _match(er.get(col), pr.get(col), field_types.get(col, "text"))
            cell_correct += int(norm)
    return {
        "expected_rows": len(expected_rows),
        "predicted_rows": len(predicted_rows),
        "matched_rows": matched,
        "missing_rows": len(expected_rows) - matched,
        "extra_rows": len(predicted_rows) - matched,
        "row_recall": matched / len(expected_rows) if expected_rows else 1.0,
        "cell_accuracy": cell_correct / cell_total if cell_total else 1.0,
        "columns": sorted(all_cols),
    }
