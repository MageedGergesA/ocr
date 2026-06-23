"""Format + checksum validators for ID-like fields we extract.

Used by `envelope.wrap_extraction` to populate the `validations[]` block of
every extraction response. Each validator returns `(ok: bool, detail: str)`.
Pure functions — no I/O, easy to test.

References:
  - Egyptian National ID: 14 digits, encodes birth date + governorate + sex.
    https://en.wikipedia.org/wiki/National_identification_number#Egypt
  - ICAO 9303 MRZ check digit (weighted 7-3-1 mod 10):
    https://www.icao.int/publications/Documents/9303_p3_cons_en.pdf
  - IBAN mod-97 (ISO 13616):
    https://en.wikipedia.org/wiki/International_Bank_Account_Number
"""
from __future__ import annotations

import re

# ---- IBAN ------------------------------------------------------------------

_IBAN_LENGTHS = {
    "EG": 29, "SA": 24, "AE": 23, "KW": 30, "BH": 22, "QA": 29, "JO": 30,
    "LB": 28, "OM": 23, "MA": 28, "TN": 24, "DZ": 26, "IQ": 23, "PS": 29,
    "GB": 22, "DE": 22, "FR": 27, "ES": 24, "IT": 27, "NL": 18, "BE": 16,
    "CH": 21, "US": 0,  # US has no IBAN
}


def validate_iban(raw: str) -> tuple[bool, str]:
    """Mod-97 IBAN validation (ISO 13616). Returns (ok, detail)."""
    if not raw:
        return False, "empty"
    s = re.sub(r"\s+", "", str(raw)).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]+", s):
        return False, "shape mismatch — expected CC + 2 digits + alphanumeric"
    country = s[:2]
    expected_len = _IBAN_LENGTHS.get(country)
    if expected_len and len(s) != expected_len:
        return False, f"country={country} expects length {expected_len}, got {len(s)}"
    # Move first 4 chars to the end, replace letters with A=10..Z=35.
    rearranged = s[4:] + s[:4]
    digits = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
    try:
        rem = int(digits) % 97
    except ValueError:
        return False, "non-numeric after letter substitution"
    if rem != 1:
        return False, f"mod-97 = {rem} (expected 1)"
    return True, f"valid IBAN ({country})"


# ---- Egyptian Tax ID (TIN) -------------------------------------------------
# The Egyptian Tax Authority assigns a 9-digit TIN. There is NO public checksum
# algorithm — validate format only and reject obvious garbage.

def validate_egyptian_tin(raw: str) -> tuple[bool, str]:
    if not raw:
        return False, "empty"
    s = re.sub(r"[\s\-/]", "", str(raw))
    if not s.isdigit():
        return False, "non-digit characters"
    if len(s) != 9:
        return False, f"Egyptian TIN is 9 digits, got {len(s)}"
    if s == "0" * 9 or len(set(s)) == 1:
        return False, "all identical digits — likely placeholder"
    return True, "9-digit Egyptian TIN, format OK"


# ---- Saudi VAT number ------------------------------------------------------
# 15 digits, starts with 3, ends with 03 (per ZATCA rules).

def validate_saudi_vat(raw: str) -> tuple[bool, str]:
    if not raw:
        return False, "empty"
    s = re.sub(r"[\s\-/]", "", str(raw))
    if not s.isdigit():
        return False, "non-digit characters"
    if len(s) != 15:
        return False, f"Saudi VAT is 15 digits, got {len(s)}"
    if not s.startswith("3"):
        return False, "must start with 3"
    if not s.endswith("03"):
        return False, "must end with 03"
    return True, "15-digit Saudi VAT, format OK"


# ---- UAE Tax Registration Number -------------------------------------------
# 15 digits, starts with 100.

def validate_uae_trn(raw: str) -> tuple[bool, str]:
    if not raw:
        return False, "empty"
    s = re.sub(r"[\s\-/]", "", str(raw))
    if not s.isdigit():
        return False, "non-digit characters"
    if len(s) != 15:
        return False, f"UAE TRN is 15 digits, got {len(s)}"
    if not s.startswith("100"):
        return False, "UAE TRN must start with '100'"
    return True, "15-digit UAE TRN, format OK"


# ---- Egyptian National ID --------------------------------------------------
# 14 digits: C YYMMDD GG SSSS X
#   C: century (2=1900s, 3=2000s)
#   YYMMDD: birth date
#   GG: governorate code (01..35, 88 = born abroad)
#   SSSS: sequential + sex (odd=male, even=female on the last of 4)
#   X: check digit (no public algorithm; many sources use weighted 2-7-9-3-... but
#      it isn't authoritatively documented; we skip the check digit and just
#      validate structure + decode the fields).

_EG_GOVERNORATES = {
    "01": "Cairo",         "02": "Alexandria", "03": "Port Said",   "04": "Suez",
    "11": "Damietta",      "12": "Dakahlia",   "13": "Sharqia",     "14": "Qalyubia",
    "15": "Kafr el-Sheikh","16": "Gharbia",    "17": "Monufia",     "18": "Beheira",
    "19": "Ismailia",      "21": "Giza",       "22": "Beni Suef",   "23": "Fayoum",
    "24": "Minya",         "25": "Asyut",      "26": "Sohag",       "27": "Qena",
    "28": "Aswan",         "29": "Luxor",      "31": "Red Sea",     "32": "New Valley",
    "33": "Matrouh",       "34": "North Sinai","35": "South Sinai", "88": "Born abroad",
}


def validate_egyptian_national_id(raw: str) -> tuple[bool, str, dict | None]:
    """Returns (ok, detail, decoded?). decoded is None if structure is invalid."""
    if not raw:
        return False, "empty", None
    s = re.sub(r"[\s\-/]", "", str(raw))
    if not s.isdigit():
        return False, "non-digit characters", None
    if len(s) != 14:
        return False, f"Egyptian national ID is 14 digits, got {len(s)}", None
    century_digit = s[0]
    if century_digit not in "23":
        return False, f"first digit must be 2 or 3 (century), got {century_digit}", None
    yy, mm, dd = s[1:3], s[3:5], s[5:7]
    gov = s[7:9]
    seq = s[9:13]
    check = s[13]
    century = 1900 if century_digit == "2" else 2000
    try:
        year = century + int(yy)
        month = int(mm); day = int(dd)
        if not (1 <= month <= 12 and 1 <= day <= 31):
            raise ValueError("invalid date")
    except ValueError as e:
        return False, f"invalid birth date encoded: {e}", None
    gov_name = _EG_GOVERNORATES.get(gov, f"unknown ({gov})")
    sex = "male" if int(seq[-1]) % 2 == 1 else "female"
    decoded = {
        "birth_date": f"{year:04d}-{month:02d}-{day:02d}",
        "governorate_code": gov,
        "governorate_name": gov_name,
        "sex": sex,
        "sequence": seq,
        "check_digit": check,
    }
    return True, "valid Egyptian national ID structure", decoded


# ---- ICAO 9303 MRZ check digits --------------------------------------------
# Weighted sum mod 10 with weights repeating 7, 3, 1.
# Character values: 0-9 → 0-9, A-Z → 10-35, '<' → 0.

def _mrz_char_value(c: str) -> int:
    if c == "<":
        return 0
    if c.isdigit():
        return int(c)
    if "A" <= c <= "Z":
        return ord(c) - 55
    raise ValueError(f"invalid MRZ char: {c!r}")


def mrz_check_digit(field: str) -> int:
    weights = [7, 3, 1]
    total = sum(_mrz_char_value(c) * weights[i % 3] for i, c in enumerate(field))
    return total % 10


def validate_mrz_field(field: str, check_char: str) -> tuple[bool, str]:
    """Verify a single MRZ field against its check digit."""
    if not field or not check_char or not check_char.isdigit():
        return False, "missing or non-digit check char"
    try:
        expected = mrz_check_digit(field)
    except ValueError as e:
        return False, str(e)
    if expected != int(check_char):
        return False, f"check digit {check_char} != computed {expected}"
    return True, f"check digit OK ({check_char})"


# ---- Walker entry point used by the envelope -------------------------------

def collect_validations(data: dict) -> list[dict]:
    """Inspect an extracted-fields tree, run known validators, return a list of
    `{check, ok, detail}` entries to attach to the response envelope.

    Looks for any leaf node whose key matches a known ID pattern (tax_id,
    iban, national_id, mrz) and runs the appropriate validator.
    """
    out: list[dict] = []
    if not isinstance(data, dict):
        return out

    def _val(node):
        if isinstance(node, dict) and "value" in node:
            return str(node.get("value") or "")
        return str(node or "")

    def walk(node):
        if isinstance(node, dict):
            for key, child in node.items():
                kl = key.lower()
                v = _val(child) if not isinstance(child, (dict, list)) or "value" in (child if isinstance(child, dict) else {}) else None
                # IBAN
                if v and ("iban" in kl):
                    ok, detail = validate_iban(v)
                    out.append({"check": f"iban:{key}", "ok": ok, "detail": detail})
                # Egyptian TIN
                elif v and ("tax_id" in kl or "tin" in kl or "tax_number" in kl) and "saudi" not in kl and "uae" not in kl:
                    ok, detail = validate_egyptian_tin(v)
                    if ok or len(v.replace(" ", "")) == 9:
                        out.append({"check": f"egyptian_tin:{key}", "ok": ok, "detail": detail})
                # Saudi VAT
                elif v and ("saudi_vat" in kl or "vat_sa" in kl):
                    ok, detail = validate_saudi_vat(v)
                    out.append({"check": f"saudi_vat:{key}", "ok": ok, "detail": detail})
                # UAE TRN
                elif v and ("trn" in kl or "uae_vat" in kl):
                    ok, detail = validate_uae_trn(v)
                    out.append({"check": f"uae_trn:{key}", "ok": ok, "detail": detail})
                # Egyptian national ID
                elif v and ("national_id" in kl or "id_number" in kl or "الرقم_القومي" in kl):
                    ok, detail, decoded = validate_egyptian_national_id(v)
                    entry = {"check": f"egyptian_national_id:{key}", "ok": ok, "detail": detail}
                    if decoded:
                        entry["decoded"] = decoded
                    out.append(entry)
                # Recurse
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return out
