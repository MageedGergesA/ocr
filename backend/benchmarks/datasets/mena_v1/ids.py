"""Deterministic construction of MENA identifiers for benchmark fixtures.

Every "valid" value here is genuinely valid against the PRODUCT validators in
app/services/validators.py (same rules: IBAN mod-97, EG national-ID structure with
a real encoded birth date, Saudi VAT 3…03, UAE TRN 100…, EG TIN 9-digit). Every
"invalid" value is genuinely invalid against the same rules. That makes the
Section-22 validator-value analysis self-consistent: the fixture's valid/invalid
LABEL matches what the product validator will actually decide.

No real personal identities — values are procedurally generated from a seed.
"""
from __future__ import annotations

import random

_EG_GOV_CODES = ["01", "02", "03", "12", "13", "14", "21", "24", "26"]


def _digits(rng: random.Random, n: int) -> str:
    return "".join(str(rng.randint(0, 9)) for _ in range(n))


# ---- Egyptian National ID (14 digits, 1st=2/3 century, YYMMDD, gov, seq, check) --
def eg_national_id(rng: random.Random, *, valid: bool = True) -> str:
    century = rng.choice("23")
    yy = f"{rng.randint(70, 99):02d}" if century == "2" else f"{rng.randint(0, 20):02d}"
    month = rng.randint(1, 12)
    day = rng.randint(1, 28)
    gov = rng.choice(_EG_GOV_CODES)
    seq = _digits(rng, 4)
    check = str(rng.randint(0, 9))
    s = f"{century}{yy}{month:02d}{day:02d}{gov}{seq}{check}"
    if valid:
        return s
    # Break it deterministically: impossible month 19.
    return f"{century}{yy}19{day:02d}{gov}{seq}{check}"


# ---- Egyptian TIN (9 digits, not all identical) ---------------------------------
def eg_tin(rng: random.Random, *, valid: bool = True) -> str:
    if not valid:
        return _digits(rng, 8)  # wrong length
    s = _digits(rng, 9)
    if len(set(s)) == 1:              # avoid the "all identical" rejection
        s = s[:-1] + ("1" if s[-1] != "1" else "2")
    return s


# ---- Saudi VAT (15 digits, starts 3, ends 03) -----------------------------------
def saudi_vat(rng: random.Random, *, valid: bool = True) -> str:
    if not valid:
        return "4" + _digits(rng, 12) + "03"   # wrong prefix
    return "3" + _digits(rng, 12) + "03"


# ---- UAE TRN (15 digits, starts 100) --------------------------------------------
def uae_trn(rng: random.Random, *, valid: bool = True) -> str:
    if not valid:
        return "200" + _digits(rng, 12)        # wrong prefix
    return "100" + _digits(rng, 12)


# ---- IBAN (mod-97) --------------------------------------------------------------
_IBAN_LEN = {"EG": 29, "SA": 24, "AE": 23}


def _iban_check(country: str, bban: str) -> str:
    rearranged = bban + country + "00"
    conv = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
    check = 98 - (int(conv) % 97)
    return f"{check:02d}"


def iban(rng: random.Random, country: str = "EG", *, valid: bool = True) -> str:
    total = _IBAN_LEN[country]
    bban = _digits(rng, total - 4)
    check = _iban_check(country, bban)
    s = f"{country}{check}{bban}"
    if valid:
        return s
    # Corrupt one digit so mod-97 fails but shape stays valid.
    pos = 6
    bad = str((int(s[pos]) + 1) % 10)
    return s[:pos] + bad + s[pos + 1:]
