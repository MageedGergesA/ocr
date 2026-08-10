"""Tests for the benchmark metrics — the evaluation code must itself be trusted."""
import math

from benchmarks import canon, metrics


# --- canonicalization -----------------------------------------------------
def test_canon_digits_dates_amounts_currency_bool():
    assert canon.fold_digits("٢٠٢٦") == "2026"
    assert canon.canon_date("2026-03-05") == "2026-03-05"
    assert canon.canon_date("05/03/2026") == "2026-03-05"       # day-first
    assert canon.canon_date("5 March 2026") == "2026-03-05"
    assert canon.canon_date("2026-02-30") is None               # impossible
    assert canon.canon_amount("1,234.50") == "1234.5"
    assert canon.canon_amount("1.234,50") == "1234.5"           # European
    assert canon.canon_currency("ر.س") == "SAR"
    assert canon.canon_currency("$") == "USD"
    assert canon.canon_bool("نعم") is True and canon.canon_bool("no") is False
    assert canon.canon_id("EG38 0019 0005") == "EG3800190005"


# --- field metrics --------------------------------------------------------
def _truth():
    return {"vendor": "Acme Co", "total": "1,234.50", "invoice_date": "2026-03-05",
            "currency": "SAR", "notes": ""}   # notes SHOULD be absent


def _types():
    return {"total": "amount", "invoice_date": "date", "currency": "currency"}


def test_perfect_extraction_scores_100():
    pred = {"vendor": {"value": "Acme Co"}, "total": {"value": "1234.50"},
            "invoice_date": {"value": "05/03/2026"}, "currency": {"value": "SAR"}}
    m = metrics.score_fields(_truth(), pred, _types())
    assert m.normalized_accuracy == 1.0
    assert m.recall == 1.0 and m.precision == 1.0 and m.f1 == 1.0
    assert m.missing_rate == 0.0 and m.hallucinated_rate == 0.0


def test_wrong_amount_fails():
    pred = {"vendor": {"value": "Acme Co"}, "total": {"value": "9999.00"},
            "invoice_date": {"value": "2026-03-05"}, "currency": {"value": "SAR"}}
    m = metrics.score_fields(_truth(), pred, _types())
    assert m.normalized_accuracy == 0.75            # 3 of 4 correct
    assert m.recall < 1.0
    bad = [f for f in m.per_field if f.field == "total"][0]
    assert bad.outcome == "wrong"


def test_arabic_indic_digits_match_after_normalization():
    pred = {"vendor": {"value": "Acme Co"}, "total": {"value": "١٢٣٤٫٥٠"},
            "invoice_date": {"value": "٢٠٢٦-٠٣-٠٥"}, "currency": {"value": "SAR"}}
    m = metrics.score_fields(_truth(), pred, _types())
    # amount + date recovered via digit folding + canonical forms
    assert m.normalized_accuracy == 1.0
    # but exact (whitespace-only) accuracy is lower since raw glyphs differ
    assert m.exact_accuracy < 1.0


def test_missing_field_lowers_recall():
    pred = {"vendor": {"value": "Acme Co"}, "total": {"value": "1234.50"},
            "currency": {"value": "SAR"}}     # invoice_date missing
    m = metrics.score_fields(_truth(), pred, _types())
    assert m.missing_rate == 0.25
    assert m.recall < 1.0


def test_hallucinated_field_lowers_precision():
    pred = {"vendor": {"value": "Acme Co"}, "total": {"value": "1234.50"},
            "invoice_date": {"value": "2026-03-05"}, "currency": {"value": "SAR"},
            "notes": {"value": "unexpected value"}}   # notes should be absent
    m = metrics.score_fields(_truth(), pred, _types())
    assert m.hallucinated_rate == 1.0
    assert m.precision < 1.0


# --- CER / WER ------------------------------------------------------------
def test_cer_wer_known_values():
    assert metrics.cer("kitten", "sitting") == 3 / 6
    assert metrics.wer("the cat sat", "the dog sat") == 1 / 3
    assert metrics.cer("abc", "abc") == 0.0


# --- classification -------------------------------------------------------
def test_classification_metrics():
    pairs = [("invoice", "invoice"), ("invoice", "receipt"),
             ("receipt", "receipt"), ("id", "id")]
    r = metrics.classification_metrics(pairs)
    assert r["accuracy"] == 0.75
    assert 0.0 <= r["macro_f1"] <= 1.0
    assert r["confusion"]["invoice"]["receipt"] == 1


# --- calibration ----------------------------------------------------------
def test_calibration_well_calibrated_low_ece():
    # 90%-confidence group correct ~90% of the time; 10% group correct ~10%.
    pairs = [(0.9, 1)] * 9 + [(0.9, 0)] * 1 + [(0.1, 1)] * 1 + [(0.1, 0)] * 9
    r = metrics.calibration(pairs)
    assert r["ece"] < 0.05


def test_calibration_badly_calibrated_high_ece():
    # Always says 0.99 but is only right half the time.
    pairs = [(0.99, 1)] * 50 + [(0.99, 0)] * 50
    r = metrics.calibration(pairs)
    assert r["ece"] > 0.4
    assert 0.0 <= r["brier"] <= 1.0


# --- tables ---------------------------------------------------------------
def test_table_rows_matched_despite_reordering():
    expected = [{"sku": "A", "qty": "2"}, {"sku": "B", "qty": "3"}]
    predicted = [{"sku": "B", "qty": "3"}, {"sku": "A", "qty": "2"}]  # reordered
    r = metrics.table_metrics(expected, predicted, key_fields=["sku"])
    assert r["matched_rows"] == 2 and r["missing_rows"] == 0 and r["extra_rows"] == 0
    assert r["cell_accuracy"] == 1.0


def test_table_missing_and_extra_rows():
    expected = [{"sku": "A", "qty": "2"}, {"sku": "B", "qty": "3"}]
    predicted = [{"sku": "A", "qty": "2"}, {"sku": "C", "qty": "9"}]
    r = metrics.table_metrics(expected, predicted, key_fields=["sku"])
    assert r["matched_rows"] == 1 and r["missing_rows"] == 1 and r["extra_rows"] == 1
