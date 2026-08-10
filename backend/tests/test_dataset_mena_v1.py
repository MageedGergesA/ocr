"""Phase 1B §5-11 — the mena_v1 business benchmark: determinism, ground-truth
consistency, balance, and that the validator actually catches bad ground truth.

Rendering is exercised on a small sample (full render is slow and optional).
"""
import copy

import pytest

from benchmarks import manifest, validate
from benchmarks.datasets.mena_v1 import generate as G

MAN_PATH = "benchmarks/datasets/mena_v1/manifest.json"


def test_manifest_build_is_deterministic():
    a = G.build_manifest()
    b = G.build_manifest()
    assert a == b
    assert len(a["cases"]) >= 120


def test_committed_manifest_matches_generator():
    """The checked-in manifest must equal what the generator emits — otherwise the
    committed ground truth has drifted from its source."""
    import json
    committed = json.load(open(MAN_PATH, encoding="utf-8"))
    assert committed == G.build_manifest()


def test_dataset_validates_clean():
    ds = manifest.load_dataset(MAN_PATH)
    problems = validate.validate_dataset(ds)
    assert problems == [], problems


def test_dataset_is_balanced():
    ds = manifest.load_dataset(MAN_PATH)
    stats = manifest.dataset_stats(ds)
    total = stats["total"]
    # no single country dominates (>60%)
    for country, n in stats["by_country"].items():
        assert n / total < 0.6, f"{country} dominates: {n}/{total}"
    # all three core countries present
    assert {"EG", "SA", "AE"} <= set(stats["by_country"])
    # languages all present
    assert {"ar", "en", "bilingual"} <= set(stats["by_language"])
    # hard slices exist (not 90 easy invoices + 10 rest)
    for tag in ("handwriting", "arabic_indic_digits", "phone_photo", "rotated",
                "bilingual", "noise"):
        assert stats["by_difficulty"].get(tag, 0) > 0, f"missing slice {tag}"
    # both valid and invalid ID fixtures exist (Section 22 needs both)
    assert stats["id_fixtures_by_validity"].get("valid_format", 0) > 0
    assert stats["id_fixtures_by_validity"].get("invalid_format", 0) > 0


def test_id_fixtures_match_product_validators():
    """Every id_validity label must agree with app/services/validators — this is
    what makes the validator-value analysis trustworthy."""
    ds = manifest.load_dataset(MAN_PATH)
    labelled = [c for c in ds.cases if c.id_validity]
    assert labelled, "expected labelled ID fixtures"
    for c in labelled:
        assert validate.validate_case(c) == []


# ---- negative tests: the validator must CATCH broken ground truth ----
def _load_one():
    ds = manifest.load_dataset(MAN_PATH)
    return next(c for c in ds.cases if c.doc_type in ("tax_invoice", "vat_invoice"))


def test_validator_catches_bad_date():
    c = copy.deepcopy(_load_one())
    c.truth["invoice_date"] = "2026-13-45"
    assert any("not a valid date" in p for p in validate.validate_case(c))


def test_validator_catches_bad_math():
    c = copy.deepcopy(_load_one())
    c.truth["total"] = "999999.99"
    assert any("!= total" in p for p in validate.validate_case(c))


def test_validator_catches_currency_mismatch():
    c = copy.deepcopy(_load_one())
    c.truth["currency"] = "USD"
    assert any("currency" in p for p in validate.validate_case(c))


def test_validator_catches_mislabelled_id():
    ds = manifest.load_dataset(MAN_PATH)
    c = copy.deepcopy(next(x for x in ds.cases if x.id_validity == "valid_format"))
    c.id_validity = "invalid_format"     # lie about a genuinely-valid ID
    assert any("validator ACCEPTS" in p for p in validate.validate_case(c))


def test_render_sample_does_not_crash(tmp_path):
    man = G.build_manifest()
    # render one of each language to exercise Arabic/Latin/bilingual paths
    picks = {}
    for c in man["cases"]:
        picks.setdefault(c["language"], c)
    for c in picks.values():
        path = G.render_case(c, str(tmp_path))
        assert path.endswith(".png")
        # non-trivial image (not blank/failed)
        import os
        assert os.path.getsize(path) > 2000
