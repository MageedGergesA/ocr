"""Cross-tool post-processing: date → ISO 8601, amount → {value, currency},
confidence aggregation. Pure functions. Used by `envelope.wrap_extraction`.

Dates: we recognise the seven most-common shapes (ISO, EU slash, US slash,
"15 March 2026", Arabic month names, etc.) and convert to ISO 8601. Hijri
dates are flagged as a warning — converting requires the hijri-converter lib
which we don't want to pull in for the launch.

Amounts: detect currency from symbol or 3-letter code, strip thousands
separators (both `,` and `٬`), normalise decimal mark.
"""
from __future__ import annotations

import re
from datetime import date


# ---- Date normalization ----------------------------------------------------

_AR_MONTHS = {
    "يناير": 1, "كانون الثاني": 1,
    "فبراير": 2, "شباط": 2,
    "مارس": 3, "آذار": 3,
    "أبريل": 4, "ابريل": 4, "نيسان": 4,
    "مايو": 5, "أيار": 5,
    "يونيو": 6, "حزيران": 6,
    "يوليو": 7, "تموز": 7,
    "أغسطس": 8, "اغسطس": 8, "آب": 8,
    "سبتمبر": 9, "أيلول": 9,
    "أكتوبر": 10, "اكتوبر": 10, "تشرين الأول": 10,
    "نوفمبر": 11, "تشرين الثاني": 11,
    "ديسمبر": 12, "كانون الأول": 12,
}

_EN_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6,
    "jul": 7, "july": 7, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def _digits_to_ascii(s: str) -> str:
    """Map Arabic-Indic / Persian digits to ASCII so the parser sees 0-9."""
    table = str.maketrans(
        "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
        "01234567890123456789",
    )
    return s.translate(table)


def normalize_date(raw: str) -> str | None:
    """Return ISO 8601 (YYYY-MM-DD) or None if unrecognised.

    Recognises: 2026-03-15, 2026/3/15, 15/3/2026, 15-Mar-2026, 15 March 2026,
    March 15 2026, 15 مارس 2026.
    """
    if not raw:
        return None
    s = _digits_to_ascii(str(raw).strip())
    # Hijri marker — punt for launch.
    if re.search(r"\bه\.?\b|هـ|هجري", s):
        return None
    # 1. Already ISO.
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        y, mo, d = m.groups()
        return _safe_iso(int(y), int(mo), int(d))
    # 2. DD-MM-YYYY or DD/MM/YYYY (MENA + EU default).
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", s)
    if m:
        d, mo, y = m.groups()
        return _safe_iso(int(y), int(mo), int(d))
    # 3. DD Month YYYY (English or Arabic month name).
    parts = re.findall(r"[^\s,]+", s)
    if 2 <= len(parts) <= 4:
        # Try "D Month Y" and "Month D Y".
        for order in ((0, 1, 2), (1, 0, 2)):
            try:
                day_s, mon_s, year_s = parts[order[0]], parts[order[1]], parts[order[2] if len(parts) > 2 else order[2]]
            except IndexError:
                continue
            day = _to_int(day_s)
            year = _to_int(year_s)
            month = _name_to_month(mon_s)
            if day and month and year and 1900 <= year <= 2100 and 1 <= day <= 31:
                return _safe_iso(year, month, day)
    return None


def _to_int(s: str):
    try:
        return int(re.sub(r"[^\d]", "", s))
    except ValueError:
        return None


def _name_to_month(s: str):
    sl = s.lower().strip(",.").rstrip("هـ")
    if sl in _EN_MONTHS:
        return _EN_MONTHS[sl]
    for key, mo in _AR_MONTHS.items():
        if key in s:
            return mo
    return None


def _safe_iso(y: int, mo: int, d: int) -> str | None:
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


# ---- Amount normalization --------------------------------------------------

# Symbol / code → ISO 4217 currency.
_CURRENCY_MAP = {
    "$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY",
    "egp": "EGP", "ج.م": "EGP", "جنيه": "EGP", "le": "EGP", "e£": "EGP",
    "sar": "SAR", "ر.س": "SAR", "ريال": "SAR", "sr": "SAR",
    "aed": "AED", "د.إ": "AED", "درهم": "AED", "dhs": "AED", "dh": "AED",
    "kwd": "KWD", "د.ك": "KWD",
    "bhd": "BHD", "د.ب": "BHD",
    "qar": "QAR", "ر.ق": "QAR",
    "omr": "OMR", "ر.ع": "OMR",
    "jod": "JOD", "د.أ": "JOD",
    "usd": "USD", "eur": "EUR", "gbp": "GBP",
}


def normalize_amount(raw: str) -> dict | None:
    """Return {value: float, currency: str|None} or None if not amount-like."""
    if raw in (None, ""):
        return None
    s = _digits_to_ascii(str(raw)).strip()
    # Detect currency.
    currency = None
    sl = s.lower()
    for token, code in _CURRENCY_MAP.items():
        if token in sl:
            currency = code
            break
    # Strip everything that isn't digits, '.', ',', '-'.
    digits = re.sub(r"[^\d.,\-]", "", s)
    if not re.search(r"\d", digits):
        return None
    # If both ',' and '.' present, the last one is decimal mark.
    if "," in digits and "." in digits:
        if digits.rfind(",") > digits.rfind("."):
            # European: 1.234,56 → 1234.56
            digits = digits.replace(".", "").replace(",", ".")
        else:
            # English: 1,234.56 → 1234.56
            digits = digits.replace(",", "")
    elif "," in digits:
        # Could be either thousands sep or decimal — heuristic: if the part
        # after the LAST comma is exactly 2 digits AND no other comma comes
        # close, treat as decimal. Otherwise treat as thousands sep.
        parts = digits.split(",")
        if len(parts[-1]) == 2 and all(len(p) == 3 for p in parts[1:-1]) is False:
            digits = digits.replace(",", ".")
        else:
            digits = digits.replace(",", "")
    try:
        value = float(digits)
    except ValueError:
        return None
    return {"value": value, "currency": currency}


# ---- Confidence aggregation ------------------------------------------------

def aggregate_confidence(data) -> dict:
    """Walk an extracted-fields tree, count {high, review, low} based on
    each leaf's confidence. Returns an aggregate summary."""
    high = mid = low = total = 0

    def walk(node):
        nonlocal high, mid, low, total
        if isinstance(node, dict):
            if "confidence" in node and isinstance(node["confidence"], (int, float)):
                total += 1
                c = float(node["confidence"])
                if c >= 0.85: high += 1
                elif c >= 0.6:  mid += 1
                else:           low += 1
            for k, v in node.items():
                if k == "confidence":
                    continue
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return {
        "total_fields": total,
        "high_confidence": high,
        "review_recommended": mid,
        "low_confidence": low,
        "overall": round((high + 0.7 * mid + 0.4 * low) / total, 3) if total else None,
    }


# ---- Tree walker: apply date + amount normalisation in-place --------------

# We don't override the model's value blindly — we add `value_iso` / `amount`
# sibling fields so the original `value` stays for back-compat. Customers can
# choose which to read.

_DATE_HINTS = {"date", "expiry", "expires", "issue", "due", "birth",
               "تاريخ", "انتهاء", "ميلاد"}
# IMPORTANT: do NOT include "value" here — it would re-wrap the cell forever.
# "tax" alone matches "tax_id"/"tax_number" — use specific suffixes only.
_AMOUNT_HINTS = {"total", "amount", "price", "subtotal", "discount",
                 "balance", "salary", "premium", "rent", "deposit",
                 "tax_amount", "tax_total", "vat_amount", "tax",  # tax as standalone word
                 "إجمالي", "اجمالي", "مبلغ", "سعر", "رصيد", "إيجار", "خصم", "ضريبة"}
_CELL_INNER_KEYS = {"value", "confidence", "value_iso", "amount", "raw", "polygon", "page"}


def _key_matches(key: str, hints: set[str]) -> bool:
    """Match a key against word-boundary hints. 'tax' matches 'tax' or 'tax_amount'
    but NOT 'supplier_tax_id' (where 'tax' is mid-key)."""
    if not key:
        return False
    kl = key.lower()
    # 1. Full-key exact match (covers 'date', 'invoice_date' via segment check below).
    if kl in hints:
        return True
    # 2. Snake-case segment match — split on '_' and ' ', check each segment.
    segments = re.split(r"[_\s]+", kl)
    if any(seg in hints for seg in segments):
        # Refuse if any other segment is a "negator" like "id", "number", "code",
        # which usually mean an identifier, not money/date.
        negators = {"id", "number", "code", "ref", "no", "num"}
        if any(seg in negators for seg in segments):
            return False
        return True
    # 3. Multi-word Arabic hints — substring is fine since Arabic doesn't snake_case.
    for h in hints:
        if not h.isascii() and h in key:
            return True
    return False


def apply_normalization(data, _parent_key: str = "") -> None:
    """Walk the tree; on cell-shaped nodes (with `value`) whose parent key
    suggests a date or amount, add `value_iso` / `amount` siblings.

    Does NOT recurse into a cell wrapper's inner keys to avoid re-wrapping.
    """
    if isinstance(data, dict):
        # Skip the inner workings of a cell wrapper — these aren't field names,
        # they're attributes of a single value, so don't try to normalize them.
        is_cell = "value" in data and any(k in data for k in ("confidence", "value_iso", "amount", "polygon", "page", "raw"))
        for key, child in list(data.items()):
            if is_cell and key in _CELL_INNER_KEYS:
                continue
            is_date_key = _key_matches(key, _DATE_HINTS)
            is_amt_key  = _key_matches(key, _AMOUNT_HINTS)
            if isinstance(child, dict) and "value" in child:
                raw_val = child["value"]
                if is_date_key and "value_iso" not in child:
                    iso = normalize_date(str(raw_val) if raw_val is not None else "")
                    if iso:
                        child["value_iso"] = iso
                elif is_amt_key and "amount" not in child:
                    amt = normalize_amount(str(raw_val) if raw_val is not None else "")
                    if amt is not None:
                        child["amount"] = amt
                # Descend into siblings of the cell (e.g. nested objects under it).
                apply_normalization(child, key)
            elif isinstance(child, (dict, list)):
                apply_normalization(child, key)
            elif isinstance(child, str) and child:
                # Bare-string field — rewrite only when normalization clearly succeeds.
                if is_date_key:
                    iso = normalize_date(child)
                    if iso and iso != child:
                        data[key] = {"value": child, "value_iso": iso}
                elif is_amt_key:
                    amt = normalize_amount(child)
                    # Only wrap if a currency was actually detected — otherwise
                    # plain numbers like "15" become bogus money.
                    if amt is not None and amt.get("currency"):
                        data[key] = {"value": child, "amount": amt}
    elif isinstance(data, list):
        for item in data:
            apply_normalization(item, _parent_key)
