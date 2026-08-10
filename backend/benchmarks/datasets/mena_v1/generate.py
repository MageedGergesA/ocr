"""Deterministic generator for the Mostakhles Business Benchmark, mena_v1.

WHAT IT PRODUCES
  * manifest.json  — balanced, versioned cases with EXACT ground truth. Committed.
  * _media/<id>.png — rendered document images. Regenerable, GITIGNORED (we do not
    store document blobs in Git; `--render` recreates them byte-deterministically).

HONESTY
  * 100% SYNTHETIC. No real customers, no real identities. Ground truth is exact by
    construction (we author the values, then render them).
  * IDs are genuinely valid/invalid against app/services/validators.py, so the
    validator-value analysis (Section 22) has trustworthy labels.
  * A balanced synthetic set is for MODEL/ARCHITECTURE SELECTION. It does NOT prove
    universal field accuracy — see dataset_stats + the README.

USAGE
  python -m benchmarks.datasets.mena_v1.generate --out <dir>/manifest.json   # metadata
  python -m benchmarks.datasets.mena_v1.generate --out <dir>/manifest.json --render
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
from typing import Optional

from benchmarks.datasets.mena_v1 import ids


def _seed(*parts) -> int:
    """Stable 32-bit seed from string parts. MUST NOT use builtin hash() — it is
    randomized per-process (PYTHONHASHSEED), which would make the dataset differ
    between runs. hashlib is process-independent, so the manifest and every render
    are byte-reproducible."""
    h = hashlib.md5("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return int(h[:8], 16)

DATASET_VERSION = "mena_v1.0"
PROVENANCE = (
    "SYNTHETIC — procedurally generated for model/architecture selection. No real "
    "customer documents or identities. Ground truth exact by construction; IDs "
    "valid/invalid against app/services/validators.py. Balanced but modest n — NOT "
    "a universal accuracy proof.")

# --- deterministic content pools -------------------------------------------------
AR_COMPANIES = ["شركة النور للتجارة", "مؤسسة الأصيل", "شركة الواحة الخضراء",
                "مصنع الشرق للصناعات", "شركة البركة للمقاولات", "مؤسسة الفجر التجارية",
                "شركة الرواد للتوريدات", "مجموعة السلام الغذائية"]
EN_COMPANIES = ["Gulf Star Trading LLC", "Al Waha Trading Co", "Nile Foods Ltd",
                "Desert Rose Contracting", "Orient Supplies FZE", "Sahara Logistics",
                "Cedar Tech Solutions", "Pearl Retail Group"]
AR_PERSONS = ["محمد أحمد علي", "فاطمة حسن إبراهيم", "خالد عبدالله سالم",
              "نورة سعيد المطيري", "أحمد يوسف عبدالرحمن", "مريم علي القحطاني"]
AR_MEDS = [["أموكسيسيلين ٥٠٠", "باراسيتامول", "أوميبرازول"],
           ["ميتفورمين ٨٥٠", "أتورفاستاتين", "أسبرين ٨١"],
           ["سيفترياكسون", "ديكلوفيناك", "فيتامين د"]]
EN_ITEMS = ["Steel pipe 2in", "Cement bag 50kg", "Copper wire 10m", "Paint 20L",
            "Ceramic tile box", "LED panel 40W", "Office chair", "A4 paper ream"]
AR_ITEMS = ["أنبوب صلب", "كيس أسمنت", "سلك نحاس", "دهان", "بلاط سيراميك",
            "لوح إضاءة", "كرسي مكتب", "ورق طباعة"]

CURRENCY = {"EG": "EGP", "SA": "SAR", "AE": "AED"}
_INDIC = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def _to_indic(s: str) -> str:
    return s.translate(_INDIC)


def _money(rng: random.Random) -> tuple[str, str, str]:
    """(subtotal, tax, total) as '1,234.56' strings with subtotal+tax==total."""
    subtotal = round(rng.uniform(120, 9800), 2)
    tax = round(subtotal * 0.15, 2)
    total = round(subtotal + tax, 2)
    fmt = lambda v: f"{v:,.2f}"
    return fmt(subtotal), fmt(tax), fmt(total)


def _date(rng: random.Random) -> str:
    return f"2026-{rng.randint(1,12):02d}-{rng.randint(1,28):02d}"


# --- the build plan: (country, doc_type, language, count) ------------------------
# Balanced across country x doc_type x language; not 90 easy invoices + 10 rest.
_PLAN = [
    ("EG", "tax_invoice", "ar", 10), ("EG", "tax_invoice", "bilingual", 4),
    ("EG", "receipt", "ar", 6), ("EG", "purchase_order", "ar", 5),
    ("EG", "bank_statement", "ar", 4), ("EG", "national_id", "ar", 6),
    ("EG", "prescription", "ar", 6), ("EG", "business_form", "ar", 4),
    ("SA", "vat_invoice", "ar", 8), ("SA", "vat_invoice", "bilingual", 5),
    ("SA", "receipt", "ar", 5), ("SA", "purchase_order", "bilingual", 5),
    ("SA", "bank_statement", "ar", 4), ("SA", "business_form", "ar", 4),
    ("AE", "tax_invoice", "en", 7), ("AE", "tax_invoice", "bilingual", 5),
    ("AE", "receipt", "en", 5), ("AE", "purchase_order", "en", 5),
    ("AE", "bank_statement", "en", 4), ("AE", "business_form", "bilingual", 4),
    ("EG", "table", "ar", 6), ("SA", "contract", "bilingual", 5),
    ("AE", "form", "en", 5),
]

# Arabic labels + titles so ar/bilingual documents look native (not ASCII tofu).
_AR_LABELS = {
    "supplier_name": "اسم المورد", "supplier_tax_id": "الرقم الضريبي",
    "vat_number": "الرقم الضريبي", "trn": "الرقم الضريبي", "invoice_date": "تاريخ الفاتورة",
    "currency": "العملة", "subtotal": "المجموع الفرعي", "tax": "الضريبة",
    "total": "الإجمالي", "merchant": "التاجر", "date": "التاريخ",
    "po_number": "رقم أمر الشراء", "account_holder": "صاحب الحساب",
    "iban": "رقم الآيبان", "statement_date": "تاريخ الكشف",
    "closing_balance": "الرصيد الختامي", "full_name": "الاسم الكامل",
    "national_id": "الرقم القومي", "date_of_birth": "تاريخ الميلاد",
    "patient_name": "اسم المريض", "medications": "الأدوية",
    "entity_name": "اسم الجهة", "reference": "المرجع",
}
_AR_TITLES = {
    "tax_invoice": "فاتورة ضريبية", "vat_invoice": "فاتورة ضريبية",
    "receipt": "إيصال", "purchase_order": "أمر شراء", "bank_statement": "كشف حساب",
    "national_id": "بطاقة رقم قومي", "prescription": "روشتة طبية",
    "business_form": "نموذج", "table": "جدول", "contract": "عقد", "form": "نموذج",
}

# difficulty rotation so degradations spread evenly across the set.
_DIFF_CYCLE = [
    ["clean_scan"], ["phone_photo"], ["rotated"], ["low_contrast"], ["blur"],
    ["noise"], ["shadow"], ["jpeg"], ["phone_photo", "rotated"],
    ["low_contrast", "noise"], ["clean_scan"], ["shadow", "jpeg"],
]


def _fields_for(country, doc_type, language, rng):
    """Return (truth, field_types, expected_doc_type, extra_tags, id_validity)."""
    cur = CURRENCY.get(country, "USD")
    ar = language in ("ar", "bilingual")
    company = (rng.choice(AR_COMPANIES) if ar else rng.choice(EN_COMPANIES))
    tags: list = []
    id_validity = None

    if doc_type in ("tax_invoice", "vat_invoice"):
        sub, tax, tot = _money(rng)
        valid = rng.random() > 0.25
        id_validity = "valid_format" if valid else "invalid_format"
        if country == "SA":
            idf, idv = "vat_number", ids.saudi_vat(rng, valid=valid)
        elif country == "AE":
            idf, idv = "trn", ids.uae_trn(rng, valid=valid)
        else:
            idf, idv = "supplier_tax_id", ids.eg_tin(rng, valid=valid)
        truth = {"supplier_name": company, idf: idv, "invoice_date": _date(rng),
                 "currency": cur, "subtotal": sub, "tax": tax, "total": tot}
        ftypes = {"invoice_date": "date", "subtotal": "amount", "tax": "amount",
                  "total": "amount", "currency": "currency", idf: "id"}
        tags += ["line_items", "currency"]
        return truth, ftypes, doc_type, tags, id_validity

    if doc_type == "receipt":
        _, _, tot = _money(rng)
        truth = {"merchant": company, "date": _date(rng), "currency": cur, "total": tot}
        return truth, {"date": "date", "total": "amount", "currency": "currency"}, \
            "receipt", ["currency"], None

    if doc_type == "purchase_order":
        _, _, tot = _money(rng)
        truth = {"supplier_name": company, "po_number": f"PO-{rng.randint(1000,9999)}",
                 "date": _date(rng), "currency": cur, "total": tot}
        return truth, {"date": "date", "total": "amount", "currency": "currency"}, \
            "purchase_order", ["line_items"], None

    if doc_type == "bank_statement":
        valid = rng.random() > 0.2
        id_validity = "valid_format" if valid else "invalid_format"
        _, _, bal = _money(rng)
        truth = {"account_holder": company, "iban": ids.iban(rng, country, valid=valid),
                 "statement_date": _date(rng), "currency": cur, "closing_balance": bal}
        ftypes = {"statement_date": "date", "closing_balance": "amount",
                  "currency": "currency", "iban": "id"}
        tags = ["multi_page"] if rng.random() > 0.5 else []
        return truth, ftypes, "bank_statement", tags, id_validity

    if doc_type == "national_id":
        valid = rng.random() > 0.2
        id_validity = "valid_format" if valid else "invalid_format"
        truth = {"full_name": rng.choice(AR_PERSONS),
                 "national_id": ids.eg_national_id(rng, valid=valid),
                 "date_of_birth": _date(rng)}
        return truth, {"national_id": "id", "date_of_birth": "date"}, \
            "national_id", ["synthetic_identity"], id_validity

    if doc_type == "prescription":
        truth = {"patient_name": rng.choice(AR_PERSONS), "date": _date(rng),
                 "medications": ", ".join(rng.choice(AR_MEDS))}
        return truth, {"date": "date"}, "prescription", ["handwriting"], None

    # business_form / table / contract / form → generic key fields
    truth = {"entity_name": company, "reference": f"REF-{rng.randint(10000,99999)}",
             "date": _date(rng)}
    return truth, {"date": "date"}, doc_type, [], None


def build_manifest() -> dict:
    cases = []
    idx = 0
    for country, doc_type, language, count in _PLAN:
        for j in range(count):
            rng = random.Random(_seed(DATASET_VERSION, country, doc_type, language, j))
            truth, ftypes, exp_dt, extra, id_validity = _fields_for(country, doc_type, language, rng)
            diff = list(_DIFF_CYCLE[idx % len(_DIFF_CYCLE)])
            if language == "bilingual":
                diff.append("bilingual")
            if language in ("ar", "bilingual") and rng.random() > 0.5:
                diff.append("arabic_indic_digits")
            for t in extra:
                if t not in diff:
                    diff.append(t)
            cid = f"{country.lower()}_{doc_type}_{language}_{j:02d}"
            pages = 2 if "multi_page" in diff else 1
            case = {
                "id": cid, "country": country, "language": language,
                "doc_type": doc_type, "layout": _layout_for(doc_type),
                "source": "synthetic", "media": "image", "pages": pages,
                "difficulty": diff, "pii": "synthetic_identity" if id_validity else "none",
                "expected_doc_type": exp_dt, "field_types": ftypes, "truth": truth,
                "input_ref": f"_media/{cid}.png", "license": "internal-synthetic",
            }
            if id_validity:
                case["id_validity"] = id_validity
            cases.append(case)
            idx += 1
    return {"dataset_version": DATASET_VERSION, "provenance": PROVENANCE, "cases": cases}


def _layout_for(doc_type: str) -> str:
    return {"tax_invoice": "invoice", "vat_invoice": "invoice",
            "purchase_order": "invoice", "receipt": "narrative",
            "bank_statement": "table", "national_id": "form",
            "prescription": "narrative", "table": "table",
            "contract": "narrative", "form": "form",
            "business_form": "form"}.get(doc_type, "form")


# ================================ RENDERING ======================================
# arabic_reshaper emits Arabic PRESENTATION FORMS (U+FE70+/FB50+), because PIL does
# no HarfBuzz shaping. Only fonts that actually contain those presentation glyphs
# render — Noto Naskh (Regular/Bold) and Noto Sans Arabic do; Noto KUFI does NOT
# (its cmap omits the presentation-forms block → tofu), so it is deliberately
# excluded. These three still give real visual variation (two families, two weights).
_FONTS = ["/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
          "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf",
          "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf"]
_LATIN = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _shape_ar(text: str) -> str:
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    except Exception:  # noqa: BLE001
        return text


def render_case(case: dict, out_dir: str, *, indic: Optional[bool] = None) -> str:
    """Render one case to a deterministic PNG. Returns the file path."""
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageChops

    rng = random.Random(_seed(case["id"], "render"))
    diff = case.get("difficulty", [])
    use_indic = indic if indic is not None else ("arabic_indic_digits" in diff)
    ar = case["language"] in ("ar", "bilingual")

    W, H = 1000, 1400
    img = Image.new("RGB", (W, H), (252, 251, 248))
    d = ImageDraw.Draw(img)
    ar_path = rng.choice(_FONTS)

    def _font(size, arabic):
        try:
            return ImageFont.truetype(ar_path if arabic else _LATIN, size)
        except Exception:  # noqa: BLE001
            return ImageFont.load_default()

    def _has_arabic(s):
        return any("؀" <= c <= "ۿ" for c in s)

    def txt(x, y, s, size=26, fill=(20, 20, 20), indic=None):
        """Draw a string with a font that actually covers its script (per-string),
        so Latin labels never turn into tofu on an Arabic document and vice-versa."""
        s = str(s)
        if (use_indic if indic is None else indic):
            s = _to_indic(s)
        arabic = _has_arabic(s)
        f = _font(size, arabic)
        if arabic:
            s = _shape_ar(s)
        d.text((x, y), s, font=f, fill=fill)

    # title — native language
    title = _AR_TITLES.get(case["doc_type"], case["doc_type"]) if ar \
        else case["doc_type"].replace("_", " ").upper()
    txt(60, 50, title, size=40, fill=(40, 60, 90), indic=False)
    d.line([(60, 110), (W - 60, 110)], fill=(120, 120, 120), width=2)

    # body: render each truth field as label: value
    y = 160
    for k, v in case["truth"].items():
        label = _AR_LABELS.get(k, k) if ar else k.replace("_", " ")
        txt(60, y, f"{label}:", size=26, fill=(90, 90, 90), indic=False)
        txt(420, y, v, size=26)
        y += 60

    # line-item table for invoices/PO
    if "line_items" in diff:
        y += 20
        d.line([(60, y), (W - 60, y)], fill=(160, 160, 160), width=1)
        y += 15
        items = AR_ITEMS if ar else EN_ITEMS
        for _ in range(rng.randint(3, 6)):
            it = rng.choice(items)
            qty = rng.randint(1, 40)
            price = f"{rng.uniform(10, 900):,.2f}"
            txt(60, y, it)
            txt(640, y, str(qty))
            txt(760, y, price)
            y += 50

    # optional stamp
    if "stamp" in diff or rng.random() > 0.85:
        _draw_stamp(d, rng, W, H)

    img = _degrade(img, diff, rng, Image, ImageFilter, ImageEnhance, ImageChops)

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{case['id']}.png")
    img.save(path, "PNG")
    return path


def _draw_stamp(d, rng, W, H):
    cx, cy = rng.randint(650, 850), rng.randint(1050, 1250)
    r = 90
    col = (180, 40, 40)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col, width=4)
    d.ellipse([cx - r + 12, cy - r + 12, cx + r - 12, cy + r - 12], outline=col, width=2)


def _degrade(img, diff, rng, Image, ImageFilter, ImageEnhance, ImageChops):
    """Deterministic, ground-truth-preserving photo degradations (Section 9)."""
    if "low_contrast" in diff:
        img = ImageEnhance.Contrast(img).enhance(0.55)
        img = ImageEnhance.Brightness(img).enhance(1.1)
    if "blur" in diff:
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.8, 1.8)))
    if "shadow" in diff:
        shadow = Image.new("L", img.size, 0)
        from PIL import ImageDraw as _ID
        sd = _ID.Draw(shadow)
        w, h = img.size
        sd.polygon([(0, 0), (int(w * 0.4), 0), (0, h)], fill=90)
        img = ImageChops.subtract(img, Image.merge("RGB", (shadow, shadow, shadow)))
    if "noise" in diff:
        noise = Image.effect_noise(img.size, 18).convert("L")
        img = ImageChops.add(img, Image.merge("RGB", (noise, noise, noise)), scale=2)
    if "phone_photo" in diff:
        img = ImageEnhance.Color(img).enhance(1.15)
        img = img.filter(ImageFilter.GaussianBlur(0.4))
    if "rotated" in diff:
        img = img.rotate(rng.uniform(-7, 7), expand=False, fillcolor=(250, 249, 246))
    if "jpeg" in diff:
        import io
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=rng.randint(28, 55))
        buf.seek(0)
        img = Image.open(buf).convert("RGB")
    return img


def main(argv=None):
    p = argparse.ArgumentParser(prog="mena_v1.generate")
    p.add_argument("--out", required=True, help="manifest.json output path")
    p.add_argument("--render", action="store_true", help="also render _media/*.png")
    p.add_argument("--limit", type=int, default=None, help="render only first N (smoke)")
    args = p.parse_args(argv)

    man = build_manifest()
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(man, fh, ensure_ascii=False, indent=2)
    print(f"wrote {args.out}: {len(man['cases'])} cases")

    if args.render:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(args.out)), "_media")
        cases = man["cases"][: args.limit] if args.limit else man["cases"]
        for i, c in enumerate(cases, 1):
            render_case(c, out_dir)
            if i % 20 == 0:
                print(f"  rendered {i}/{len(cases)}")
        print(f"rendered {len(cases)} images into {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
