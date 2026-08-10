"""Golden-ground-truth validator (Section 11).

Before a benchmark is trusted, its manifest must be internally consistent — a
scoring run against wrong ground truth produces confidently wrong numbers. This
rejects cases whose truth is self-contradictory:

  * dates that do not parse as real calendar dates,
  * invoice math that does not add up (subtotal + tax != total),
  * currency that does not match the case country,
  * an id_validity LABEL that disagrees with the product validator
    (app/services/validators.py) — so "this fixture is a valid Saudi VAT" is
    actually a valid Saudi VAT, and an "invalid" one is actually rejected.

Returns a list of problems (empty == clean). Used by the CLI and the tests.
"""
from __future__ import annotations

import datetime
import re
from typing import Optional

from benchmarks import manifest as _manifest

_COUNTRY_CCY = {"EG": "EGP", "SA": "SAR", "AE": "AED"}


def _parse_date(s: str) -> bool:
    try:
        datetime.date.fromisoformat(str(s))
        return True
    except (ValueError, TypeError):
        return False


def _num(s) -> Optional[float]:
    try:
        return float(str(s).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _id_ok(field: str, value: str) -> Optional[bool]:
    """Run the PRODUCT validator matching a field; None if no validator applies."""
    from app.services import validators as V
    f = field.lower()
    if f in ("vat_number",) or "saudi_vat" in f:
        return V.validate_saudi_vat(value)[0]
    if f in ("trn",):
        return V.validate_uae_trn(value)[0]
    if f in ("supplier_tax_id", "tax_id", "tin"):
        return V.validate_egyptian_tin(value)[0]
    if f in ("iban",):
        return V.validate_iban(value)[0]
    if f in ("national_id",):
        return V.validate_egyptian_national_id(value)[0]
    return None


def validate_case(case) -> list:
    problems: list[str] = []
    truth = case.truth or {}
    ftypes = case.field_types or {}

    # dates
    for field, ftype in ftypes.items():
        if ftype == "date" and field in truth and not _parse_date(truth[field]):
            problems.append(f"{case.id}: field '{field}' is not a valid date: {truth[field]!r}")

    # invoice math
    sub, tax, tot = _num(truth.get("subtotal")), _num(truth.get("tax")), _num(truth.get("total"))
    if sub is not None and tax is not None and tot is not None:
        if abs((sub + tax) - tot) > 0.01:
            problems.append(f"{case.id}: subtotal+tax ({sub}+{tax}) != total ({tot})")

    # currency vs country
    exp_ccy = _COUNTRY_CCY.get(case.country)
    if exp_ccy and truth.get("currency") and truth["currency"] != exp_ccy:
        problems.append(f"{case.id}: currency {truth['currency']} != {exp_ccy} for {case.country}")

    # id_validity label agrees with the product validator
    label = getattr(case, "id_validity", "")
    if label:
        id_fields = [f for f, t in ftypes.items() if t == "id"]
        for field in id_fields:
            if field not in truth:
                continue
            ok = _id_ok(field, truth[field])
            if ok is None:
                continue
            if label == "valid_format" and not ok:
                problems.append(f"{case.id}: labelled valid_format but validator REJECTS {field}={truth[field]!r}")
            if label == "invalid_format" and ok:
                problems.append(f"{case.id}: labelled invalid_format but validator ACCEPTS {field}={truth[field]!r}")
    return problems


def validate_dataset(ds) -> list:
    problems: list[str] = []
    seen_ids: set = set()
    for c in ds.cases:
        if c.id in seen_ids:
            problems.append(f"duplicate case id: {c.id}")
        seen_ids.add(c.id)
        problems.extend(validate_case(c))
    return problems


def main(argv=None):
    import argparse
    import sys
    p = argparse.ArgumentParser(prog="benchmarks.validate")
    p.add_argument("--dataset", required=True)
    args = p.parse_args(argv)
    ds = _manifest.load_dataset(args.dataset)
    problems = validate_dataset(ds)
    if problems:
        print(f"INVALID: {len(problems)} problem(s) in {ds.version}", file=sys.stderr)
        for pr in problems:
            print("  -", pr, file=sys.stderr)
        return 1
    print(f"OK: {len(ds.cases)} cases in {ds.version} are internally consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
