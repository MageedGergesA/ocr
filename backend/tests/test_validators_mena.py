"""MENA validator audit (Phase 1, Section 23).

Rigorous tests for the deterministic validators. Where the algorithm is
authoritative and public (IBAN ISO 13616 mod-97; MRZ ICAO 9303 7-3-1 mod 10),
we assert against known-good vectors. Where the government checksum is NOT publicly
verified (Egyptian National ID check digit, Saudi VAT, UAE TRN), the validator is
FORMAT-ONLY today; those tests are labelled NEEDS-SPEC-VERIFICATION and assert the
CURRENT (format) behavior rather than a fabricated checksum. We do not invent
government algorithms.
"""
from app.services import validators as V


# --- IBAN (ISO 13616 mod-97) — AUTHORITATIVE ------------------------------
def test_iban_valid_known_vectors():
    ok, _ = V.validate_iban("GB82WEST12345698765432")   # textbook-valid
    assert ok
    ok2, _ = V.validate_iban("DE89370400440532013000")  # textbook-valid
    assert ok2


def test_iban_valid_with_spaces_and_lowercase():
    ok, _ = V.validate_iban("gb82 west 1234 5698 7654 32")
    assert ok


def test_iban_invalid_checksum():
    ok, _ = V.validate_iban("GB82WEST12345698765433")    # last digit changed
    assert not ok


def test_iban_invalid_length_for_country():
    ok, _ = V.validate_iban("GB82WEST1234569876543")     # one short for GB(22)
    assert not ok


def test_iban_malformed():
    assert not V.validate_iban("")[0]
    assert not V.validate_iban("NOTANIBAN")[0]


# --- MRZ check digit (ICAO 9303, weights 7-3-1) — AUTHORITATIVE ------------
def test_mrz_check_digit_known_vectors():
    # ICAO 9303 worked example: date-of-birth field "740812" -> check digit 2.
    assert V.mrz_check_digit("740812") == 2
    # Independently computed: "030411" -> 0*7+3*3+0+4*7+1*3+1 = 41 -> 1
    assert V.mrz_check_digit("030411") == 1


def test_mrz_field_validation():
    ok, _ = V.validate_mrz_field("740812", "2")
    assert ok
    bad, _ = V.validate_mrz_field("740812", "3")
    assert not bad


# --- Egyptian National ID (14-digit decode) -------------------------------
# NEEDS-SPEC-VERIFICATION: the trailing check digit is NOT verified (public
# weighted algorithm unconfirmed) — this is a structural DECODER, not a full
# checksum validator. Tests assert decode + structural rejection only.
def test_egyptian_national_id_decodes_structure():
    # Synthetic, non-real identity: century 3 (2000s), 2000-01-01, gov 01 (Cairo).
    ok, _msg, decoded = V.validate_egyptian_national_id("30001010123456")
    assert ok and decoded is not None
    assert decoded.get("birth_date", "").startswith("2000-01-01")


def test_egyptian_national_id_rejects_bad_length_and_month():
    assert not V.validate_egyptian_national_id("123")[0]             # too short
    assert not V.validate_egyptian_national_id("30013010123456")[0]  # month 13


def test_egyptian_national_id_known_gap_feb_30_not_calendar_checked():
    # DOCUMENTED GAP: day range is 1..31, not true calendar — 30 Feb currently
    # decodes. This test PINS the current behavior so a future fix is a conscious
    # change, not a silent one.
    ok, _msg, _decoded = V.validate_egyptian_national_id("30002300123456")  # 2000-02-30
    assert ok is True   # NEEDS-SPEC-VERIFICATION: should become False after calendar check


# --- Egyptian TIN — FORMAT ONLY (NEEDS-SPEC-VERIFICATION) ------------------
def test_egyptian_tin_format_only():
    assert V.validate_egyptian_tin("123456789")[0]        # 9 digits -> format OK
    assert not V.validate_egyptian_tin("11111111")[0]     # 8 digits
    assert not V.validate_egyptian_tin("111111111")[0]    # all-identical rejected
    # HIGH false-positive risk acknowledged: any 9 distinct-ish digits pass.


# --- Saudi VAT / UAE TRN — FORMAT ONLY (NEEDS-SPEC-VERIFICATION) -----------
def test_saudi_vat_format_only():
    assert V.validate_saudi_vat("300000000000003")[0]     # 3...03, 15 digits
    assert not V.validate_saudi_vat("400000000000003")[0]  # wrong leading digit
    assert not V.validate_saudi_vat("30000000000003")[0]   # 14 digits


def test_uae_trn_format_only():
    assert V.validate_uae_trn("100000000000003")[0]       # starts 100, 15 digits
    assert not V.validate_uae_trn("200000000000003")[0]    # wrong prefix
    assert not V.validate_uae_trn("10000000000003")[0]     # 14 digits


# --- collect_validations dispatch -----------------------------------------
def test_collect_validations_runs_over_tree():
    data = {"iban": {"value": "GB82WEST12345698765432"},
            "vat_number": {"value": "not-checked-key"}}
    out = V.collect_validations(data)
    assert any(v.get("check") for v in out)   # at least the IBAN produced a check
