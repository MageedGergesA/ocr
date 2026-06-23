"""Document extraction — provider-agnostic.

Two modes:
  - auto   : model detects the document type and extracts whatever fields belong to it.
  - schema : caller supplies an exact field list (used by the Odoo module to map to model fields).

The actual model call lives in `llm` (Gemini), so cost/quality routing happens there.
Easy docs -> cheap model (Flash-Lite), hard/handwritten -> stronger model (Flash).

Auto-mode output now includes a `layout` field so the UI can render results in a
shape that matches the document (form / table / narrative / mixed / prescription).
Output language is controlled by `output_lang` ('preserve' | 'ar' | 'en').
"""
import json

from . import llm

# Field-name translation fallback for when the model returns English keys but
# the user wants Arabic UI. Tiny dictionary — extend as we see common drift.
EN_TO_AR_FIELDS = {
    "project_name": "اسم_المشروع",
    "building_model": "نموذج_المبنى",
    "name": "الاسم",
    "full_name": "الاسم_الكامل",
    "date": "التاريخ",
    "date_of_birth": "تاريخ_الميلاد",
    "issue_date": "تاريخ_الإصدار",
    "expiry_date": "تاريخ_الانتهاء",
    "amount": "المبلغ",
    "total": "الإجمالي",
    "subtotal": "الإجمالي_الفرعي",
    "tax": "الضريبة",
    "tax_number": "الرقم_الضريبي",
    "phone": "الهاتف",
    "email": "البريد_الإلكتروني",
    "address": "العنوان",
    "id_number": "الرقم_القومي",
    "passport_number": "رقم_جواز_السفر",
    "currency": "العملة",
    "seller": "البائع",
    "buyer": "المشتري",
    "company": "الشركة",
    "occupation": "الوظيفة",
    "nationality": "الجنسية",
    "place_of_birth": "محل_الميلاد",
    "sex": "الجنس",
}

# Convert Arabic-Indic and Persian digits to ASCII so numbers (phones, IDs, dates,
# amounts) are usable downstream (Odoo fields, exports) instead of "٠١٢".
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

# Reusable calibration rule — keeps the model from reporting high confidence on guesses.
CALIBRATION = (
    " Use REALISTIC confidence: only give 0.9+ for values you can read clearly and verbatim. "
    "For anything you infer, interpret, or that is unclear/handwritten (names, dates, phone digits, "
    "doses), give 0.4-0.7. NEVER report high confidence on a guess."
)


def _normalize_digits(obj):
    """Recursively convert Arabic-Indic/Persian digits to ASCII in all string values."""
    if isinstance(obj, str):
        return obj.translate(_AR_DIGITS)
    if isinstance(obj, list):
        return [_normalize_digits(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _normalize_digits(v) for k, v in obj.items()}
    return obj


def _strip_code_fence(text: str) -> str:
    """Models sometimes wrap JSON in ```json ... ``` fences. Peel them off."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


def _call_model_multi(files: list, prompt: str, hard: bool):
    """Call Gemini once with multiple images. Each image is preprocessed first."""
    processed = [_preprocess_image(b, mt) for b, mt in files]
    return llm.generate_from_documents(processed, prompt, hard)


def _run_multi(files: list, prompt: str, hard: bool) -> dict:
    """Multi-image variant of _run."""
    text, truncated = _call_model_multi(files, prompt, hard)
    try:
        return _normalize_digits(json.loads(_strip_code_fence(text)))
    except json.JSONDecodeError:
        if truncated:
            raise ValueError(
                "the response was truncated — try splitting the upload into smaller batches "
                "or extracting fewer fields."
            )
        raise


def _preprocess_image(file_bytes: bytes, media_type: str) -> tuple[bytes, str]:
    """Resize + auto-rotate + re-encode oversized photos before paying for Gemini tokens.

    Gemini bills by 1024x1024 tile; a 4MB phone photo wastes ~10x the tokens of the
    same image at 2048px long-side / quality 85. Skips PDFs and non-image inputs.
    Failures fall through to the original bytes (so a corrupt image still hits the
    model with its native error path).
    """
    if not media_type.startswith("image/") or len(file_bytes) < 200_000:
        return file_bytes, media_type
    try:
        import io
        from PIL import Image, ImageOps
        img = Image.open(io.BytesIO(file_bytes))
        img = ImageOps.exif_transpose(img)  # honour camera orientation tag
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        # Resize so long side is at most 2048px — preserves OCR-readable detail.
        w, h = img.size
        long_side = max(w, h)
        if long_side > 2048:
            ratio = 2048 / long_side
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        new_bytes = buf.getvalue()
        # Only swap if we actually shrunk it — sometimes a small PNG re-encodes larger.
        if len(new_bytes) < len(file_bytes):
            return new_bytes, "image/jpeg"
    except Exception:  # noqa: BLE001 — preprocessing is opportunistic, never mandatory
        pass
    return file_bytes, media_type


# Smart routing — heuristic recommendation for the fast/hard tier when the
# caller passes mode="auto". Conservative: only routes to fast when we're
# fairly sure the doc is easy enough; otherwise stays on the safe (hard) path.
# Saves ~50% of Gemini cost on a typical mixed workload without an extra LLM call.
_EASY_HINTS = ("receipt", "business_card", "business card", "card",
               "screenshot", "screen_shot", "table", "csv", "spreadsheet")
_HARD_HINTS = ("prescription", "handwrit", "contract", "real_estate", "real estate",
               "title_deed", "title deed", "marriage", "doctor_note", "doctor note",
               "passport", "national_id", "national id", "id_card", "id card",
               "rx", "روشتة", "عقد", "هوية", "جواز")


def recommend_tier(file_bytes: bytes, media_type: str, doctype_hint: str | None = None) -> str:
    """Return 'fast' or 'hard' based on cheap heuristics (no LLM call).

    The caller only consults this when mode='auto'. Other modes ('fast'/'hard') honour
    the user's explicit choice.
    """
    hint = (doctype_hint or "").lower()
    if hint and any(k in hint for k in _HARD_HINTS):
        return "hard"
    if hint and any(k in hint for k in _EASY_HINTS):
        return "fast"
    size = len(file_bytes or b"")
    if media_type == "application/pdf" and size < 250_000:
        # Small PDFs are almost always native-text — fast tier extracts them fine.
        return "fast"
    if media_type.startswith("image/") and size < 300_000:
        # Small phone images: receipts, screenshots, business cards.
        return "fast"
    return "hard"


def _resolve_hard(mode: str, hard: bool, file_bytes: bytes, media_type: str,
                  doctype_hint: str | None = None) -> bool:
    """Translate (mode, hard) into a single boolean for the LLM call."""
    if mode == "auto":
        return recommend_tier(file_bytes, media_type, doctype_hint) == "hard"
    if mode == "fast":
        return False
    if mode == "hard":
        return True
    return hard  # mode='explicit' (default) — honour the caller-provided hard flag


def _call_model(file_bytes: bytes, media_type: str, prompt: str, hard: bool):
    """One vision call via the configured provider. Returns (text, truncated)."""
    file_bytes, media_type = _preprocess_image(file_bytes, media_type)
    return llm.generate_from_document(file_bytes, media_type, prompt, hard)


def _run(file_bytes: bytes, media_type: str, prompt: str, hard: bool) -> dict:
    """Call the model and parse a JSON object out of the reply."""
    text, truncated = _call_model(file_bytes, media_type, prompt, hard)
    try:
        return _normalize_digits(json.loads(_strip_code_fence(text)))
    except json.JSONDecodeError:
        if truncated:
            raise ValueError(
                "the response was truncated — this document is unusually large/complex. "
                "Try splitting the PDF or extracting fewer fields."
            )
        raise


def run_text(file_bytes: bytes, media_type: str, prompt: str, hard: bool = False) -> str:
    """Run a service whose output is plain text (OCR, translation, summary…)."""
    text, _ = _call_model(file_bytes, media_type, prompt, hard)
    return _strip_code_fence(text) if text.strip().startswith("```") else text.strip()


def chat(document_text: str, question: str, history: list | None = None) -> str:
    """Answer a question about a document, using its already-extracted text.
    Text-only call (no re-OCR) so it's cheap and fast."""
    system = (
        "You are a helpful assistant answering questions about a document. "
        "Use ONLY the document content below; if the answer isn't there, say so honestly. "
        "Reply in the user's language (Arabic or English), concisely.\n\n"
        f"=== DOCUMENT ===\n{document_text}"
    )
    return llm.generate_text(system, question, hard=True, max_tokens=1024, history=history)


def compare(text_a: str, text_b: str) -> str:
    """Compare two documents' text and report differences."""
    system = ("You compare two documents. Report clearly: what CHANGED, what is MISSING in "
              "either, and what MATCHES. Be specific and concise. Reply in the documents' language.")
    user = (f"=== DOCUMENT A ===\n{text_a}\n\n=== DOCUMENT B ===\n{text_b}\n\nCompare A and B.")
    return llm.generate_text(system, user, hard=True, max_tokens=1500)


def extract_prescription(image_bytes: bytes, media_type: str, hard: bool = True) -> dict:
    """Rich, interpreted reading of a handwritten medical prescription.

    Returns the prescription shape plus a cognitive envelope:
      {
        "patient":     {field: {value, confidence}, ...},
        "medications": [{name, drug_class, form, dosage, duration?, confidence}, ...],
        "as_needed":   [{name, confidence}, ...],     # PRN medicines
        "phone_numbers": [...],
        "notes":       [...],
        "summary":     "one-sentence reading of the Rx",
        "validations": [{check, ok, detail}, ...],
        "derived":     {medication_count, antibiotic_present, nsaid_present, ...}
      }
    """
    prompt = (
        "This is a HANDWRITTEN Egyptian medical prescription (روشتة). Read it like an experienced "
        "Egyptian clinical pharmacist and produce a RICH, INTERPRETED result with cognitive cross-checks.\n"
        "Known Egyptian drugs — prefer the correct spelling if a handwritten name is close: Newclav, "
        "Augmentin, Hibiotic, Curam, Amrizole, Flagyl, Rhinopro, Telfast, Zyrtec, Allergyl, Histop, "
        "Nasostop, Otrivin, Sinucare, Ventolin, Farcolin, Brufen, Cetal, Abimol, Paramol, Zithromax, "
        "Klacid, Zisrocin, Voltaren, Nexium, Concor, Norvasc.\n"
        "For EACH medication identify: its name; its drug class / active ingredient if recognizable "
        "(e.g. Newclav → أموكسيسيلين/كلافولانيك، Amrizole → ميترونيدازول); its formulation (معلّق/شراب/"
        "نقط/أقراص…); INTERPRET the handwritten dose into a clear Arabic instruction "
        "(e.g. '4 مل كل 12 ساعة'، 'مرتين يوميًا لمدة 5 أيام'); and add a separate `duration` field if "
        "you can identify a course length in days. If a dose is illegible write 'غير واضح'.\n"
        "'Temp' is body temperature in Celsius (a lone '7' almost certainly means 37). 'Age' is in years, "
        "'Wt' is weight in kg.\n"
        "Keep all names and values in their ORIGINAL language; do NOT translate Arabic into English. "
        "Give a calibrated 0-1 confidence per item; never inflate confidence on unclear handwriting.\n\n"
        "ALSO produce, in the same JSON object:\n"
        "- summary: a one-sentence, plain-Arabic clinical summary (e.g. 'وصفة طبية لمريض عمره X سنة "
        "بتشخيص Y، تتضمن مضاد حيوي + خافض حرارة لمدة Z أيام').\n"
        "- derived: {\"medication_count\": <int>, \"antibiotic_present\": true|false, "
        "\"nsaid_present\": true|false (ibuprofen/diclofenac/naproxen/brufen/voltaren), "
        "\"duration_days_max\": <int or null>, \"has_handwritten_dose\": true|false "
        "(any medication confidence < 0.7)}.\n"
        "- validations: an array of {check, ok, detail} entries — include EVERY check that applies:\n"
        "  * has_patient_name (patient name extracted)\n"
        "  * has_doctor_name (doctor name extracted)\n"
        "  * has_date (date extracted and reasonable)\n"
        "  * has_diagnosis (D.G / تشخيص extracted)\n"
        "  * medications_have_doses (every med has a dosage AND duration)\n"
        "  * temp_sanity (if temperature present, 30 ≤ temp ≤ 42)\n"
        "  * age_sanity (if age present, 0 ≤ age ≤ 120)\n"
        "  * pediatric_dose_warning (if age < 12 years AND a typically-adult dose like 500mg+ amoxicillin seen)\n"
        "  * antibiotic_course (if antibiotic_present, full duration ≥ 5 days)\n"
        "Mark ok=true even for passing checks so the user can see what was verified.\n\n"
        "Return ONLY valid JSON in EXACTLY this shape:\n"
        '{"patient": {"الطبيب": {"value": "", "confidence": 0}, "التخصص": {"value": "", "confidence": 0}, '
        '"المريض": {"value": "", "confidence": 0}, "التاريخ": {"value": "", "confidence": 0}, '
        '"التشخيص": {"value": "", "confidence": 0}, "العمر": {"value": "", "confidence": 0}, '
        '"الوزن": {"value": "", "confidence": 0}, "الحرارة": {"value": "", "confidence": 0}}, '
        '"medications": [{"name": "", "drug_class": "", "form": "", "dosage": "", "duration": "", "confidence": 0}], '
        '"as_needed": [{"name": "", "confidence": 0}], '
        '"phone_numbers": [], "notes": [], '
        '"summary": "", '
        '"derived": {"medication_count": 0, "antibiotic_present": false, "nsaid_present": false, '
        '"duration_days_max": null, "has_handwritten_dose": false}, '
        '"validations": [{"check": "", "ok": true, "detail": ""}]}'
        + CALIBRATION
    )
    return _run(image_bytes, media_type, prompt, hard)


def run_table(file_bytes: bytes, media_type: str, hard: bool = True) -> dict:
    """Extract tabular data. Returns {"columns": [...], "rows": [[...], ...]}."""
    prompt = (
        "Extract the main table(s) from this document. Combine into ONE table. "
        "Keep cell text in its original language (Arabic/English). "
        'Return ONLY valid JSON in this shape: {"columns": ["..."], "rows": [["..."], ...]}. '
        "If there are no clear columns, use the first row's cells as columns."
    )
    data = _run(file_bytes, media_type, prompt, hard)
    return {"columns": data.get("columns", []), "rows": data.get("rows", [])}


def split_pdf_pages(pdf_bytes: bytes) -> list[bytes]:
    """Split a PDF into a list of single-page PDF byte blobs (for batch mode)."""
    import io

    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    for page in reader.pages:
        writer = PdfWriter()
        writer.add_page(page)
        buf = io.BytesIO()
        writer.write(buf)
        pages.append(buf.getvalue())
    return pages


_LANG_INSTRUCTION = {
    "preserve": (
        "Keep every value EXACTLY in the document's original language and script — "
        "do NOT translate, transliterate, or add another language in parentheses. "
        "Field NAMES should also be in the document's original language (Arabic field "
        "names like 'اسم_البائع' for an Arabic invoice, English ones for an English doc)."
    ),
    "ar": (
        "Return BOTH field names AND values in Arabic. Translate from the original "
        "language if needed. Preserve proper nouns (people, brands, ID numbers, codes) "
        "in their original spelling. Use Arabic snake_case field names like 'اسم_البائع', "
        "'تاريخ_الإصدار', 'الرقم_القومي'."
    ),
    "en": (
        "Return BOTH field names AND values in English. Translate from the original "
        "language if needed. Preserve proper nouns (people, brands, ID numbers, codes) "
        "in their original spelling. Use English snake_case field names like 'seller_name', "
        "'issue_date', 'national_id'."
    ),
}


def _postprocess_field_names(result, output_lang: str) -> dict:
    """When output_lang='ar' but the model returned English field names anyway,
    rewrite the top-level field keys via EN_TO_AR_FIELDS. Values untouched.
    Robust to non-dict results (Gemini occasionally returns a top-level list)."""
    if not isinstance(result, dict):
        return result
    if output_lang != "ar":
        return result
    fields = result.get("fields")
    if not isinstance(fields, dict):
        return result
    renamed = {}
    for k, v in fields.items():
        renamed[EN_TO_AR_FIELDS.get(k, k)] = v
    result["fields"] = renamed
    return result


def _ensure_dict_result(result, default_doc_type: str = "unknown") -> dict:
    """Defensive wrapper: Gemini sometimes returns a top-level JSON list or a
    bare primitive even though our prompt asks for a dict. Normalise so the
    rest of the pipeline (endpoint, renderer, _record_history) never crashes
    with 'list' object has no attribute 'get'."""
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        # If the list looks like medications (each item has 'name' / 'dosage'),
        # treat as a prescription with just the medications array.
        if result and isinstance(result[0], dict) and any(
            k in result[0] for k in ("name", "dosage", "medication")
        ):
            return {"document_type": "prescription", "layout": "prescription",
                    "medications": result}
        # Otherwise wrap as a generic table.
        return {"document_type": default_doc_type, "layout": "table",
                "table": {"columns": list(result[0].keys()) if result and isinstance(result[0], dict) else [],
                          "rows": [list(r.values()) if isinstance(r, dict) else [r] for r in result]}}
    # Primitive — wrap as a narrative.
    return {"document_type": default_doc_type, "layout": "narrative",
            "fields": {"full_text": {"value": str(result), "confidence": 0.5}}}


def extract_auto_multi(files: list, hard: bool = True,
                       output_lang: str = "preserve") -> dict:
    """Multi-image variant: extract from several images in a single Gemini call
    so the model can CROSS-REFERENCE them (e.g. ID front+back of the same
    person, multi-page receipts, a customer file with passport + ID + contract).

    `files` is a list of (bytes, media_type) tuples — pass in upload order.
    Returns the same rich shapes as extract_auto (prescription / invoice /
    contract / form / etc.).
    """
    lang_instr = _LANG_INSTRUCTION.get(output_lang, _LANG_INSTRUCTION["preserve"])
    n = len(files)
    # Always return a DICT — even when images are unrelated, wrap them in
    # {"documents": [...]} so the endpoint never sees a top-level list.
    multi_hint = (
        f"\nIMPORTANT: You are seeing {n} related images. Treat them as parts of "
        "ONE record (front+back of an ID, multi-page receipt, customer file with "
        "supporting docs) and merge fields into a single result. If the images are "
        "clearly UNRELATED documents, return "
        '{"document_type": "mixed", "layout": "mixed", "documents": [{...per-image...}]} '
        "— but ALWAYS return a JSON OBJECT at the top level, never a bare array.\n"
    ) if n > 1 else ""
    prompt = (
        "You are a document data-extraction system. Read these document images "
        "like an expert and produce a RICH, INTERPRETED structured result."
        + multi_hint +
        "Identify document_type and pick a layout label: 'form', 'table', "
        "'narrative', 'mixed', or 'prescription'.\n\n"
        "Output shape rules (same as single-image):\n"
        "- prescription → {document_type, layout, patient: {...}, "
        "medications: [{name, drug_class, form, dosage, duration, confidence}], "
        "as_needed?, phone_numbers?, notes?}\n"
        "- invoice/receipt with line items → {document_type, layout, header, "
        "line_items: {columns, rows}, totals}\n"
        "- contract → {document_type, layout, header, clauses: [{title, text, "
        "confidence}], totals}\n"
        "- table → {document_type, layout: 'table', table: {columns, rows}}\n"
        "- narrative → {document_type, layout: 'narrative', fields: {full_text: "
        "{value, confidence}}}\n"
        "- form/ID/card → {document_type, layout: 'form', fields: {<name>: "
        "{value, confidence}}}\n\n"
        f"LANGUAGE: {lang_instr}\n\n"
        "Return ONLY valid JSON, no other text, no markdown fences."
        + CALIBRATION
    )
    result = _run_multi(files, prompt, hard)
    result = _ensure_dict_result(result)
    return _postprocess_field_names(result, output_lang)


# Path-B prompt fragment — when `with_layout=True`, we also ask the model for
# `_layout_html` (a self-contained <html> document visually replicating the
# source layout, with the extracted VALUES filled in). Token cost: ~1500-3000
# additional output tokens. We bill 3 extra credits to cover the spend with margin.
_VISUAL_LAYOUT_INSTRUCTION = """

ALSO emit a `_layout_html` field at the TOP LEVEL of the JSON response. Its
value is a complete <!DOCTYPE html>...</html> string that VISUALLY REPRODUCES
the document layout you see in the source image, with the extracted VALUES
populated. Requirements:

  1. Self-contained — embed all CSS in a single <style> block. Use system fonts
     ('Cairo', 'Helvetica', sans-serif). NO external resources, NO scripts, NO
     base64 images.
  2. Match the source — keep the same overall structure: header position,
     logo placement (use the company name in styled text where the logo was),
     table columns in the same order, footer position. Match colors approximately
     (teal/blue/red/etc.) using hex values. Use <table> for tabular data.
  3. Direction-aware — set <html dir="rtl"> for Arabic-primary documents,
     "ltr" for Latin-primary. Mirror layout accordingly.
  4. Fillable — the values shown MUST be the same ones in `fields`/`header`/
     `line_items`/etc. — never the original raw text from the source.
  5. Bounded — keep the entire HTML under 8000 characters. Skip elaborate
     SVG illustrations; a clean readable reproduction beats a flashy mess.
  6. A4-printable — use `@page { size: A4; margin: 18mm; }` so the page
     prints cleanly without overflowing.

Return the HTML as a SINGLE STRING (escape internal `"` as `\\"` and newlines
as `\\n` so it stays a valid JSON string value).
"""


def extract_auto(image_bytes: bytes, media_type: str, hard: bool = True,
                 output_lang: str = "preserve", mode: str = "explicit",
                 with_layout: bool = False) -> dict:
    """Detect the document type, infer a layout shape, and extract fields.

    output_lang: 'preserve' (default — same as doc), 'ar', or 'en'.

    Output shapes are layout-specific so the UI can render rich, native-looking
    results instead of a generic field/value/confidence list:
      - prescription: {document_type, layout, patient: {...}, medications: [{name,
        drug_class, form, dosage, duration?, confidence}], as_needed?: [...],
        phone_numbers?: [...], notes?: [...]}
      - invoice/receipt with line items: {document_type, layout, header: {...},
        line_items: {columns, rows}, totals: {...}}
      - generic form/ID/card: {document_type, layout, fields: {name: {value, confidence}}}
      - narrative: {document_type, layout: "narrative", fields: {full_text: {value, confidence}}}
      - table: {document_type, layout: "table", table: {columns, rows}}
    """
    lang_instr = _LANG_INSTRUCTION.get(output_lang, _LANG_INSTRUCTION["preserve"])
    prompt = (
        "You are a document data-extraction system. Read this document like an "
        "expert (pharmacist for prescriptions, accountant for invoices, legal "
        "reviewer for contracts) and produce a RICH, INTERPRETED structured result.\n\n"
        "STEP 1 — identify the document_type (passport, national_id, invoice, "
        "receipt, contract, prescription, business_card, bank_statement, letter, etc.).\n"
        "STEP 2 — pick a layout label: 'form' (labeled fields), 'table' (homogeneous "
        "rows only), 'narrative' (prose), 'mixed' (header + line items / sections), "
        "or 'prescription' (specifically a medical prescription).\n"
        "STEP 3 — emit the OUTPUT SHAPE that matches the layout:\n\n"
        "── If PRESCRIPTION (روشتة) ──\n"
        "Return this richer shape — DO NOT flatten the medications into numbered fields:\n"
        '{\n'
        '  "document_type": "prescription",\n'
        '  "layout": "prescription",\n'
        '  "patient": {\n'
        '    "doctor": {"value": "...", "confidence": 0-1},\n'
        '    "specialty": {"value": "...", "confidence": 0-1},\n'
        '    "patient_name": {"value": "...", "confidence": 0-1},\n'
        '    "date": {"value": "...", "confidence": 0-1},\n'
        '    "diagnosis": {"value": "...", "confidence": 0-1},\n'
        '    "age": {"value": "...", "confidence": 0-1},\n'
        '    "weight": {"value": "...", "confidence": 0-1},\n'
        '    "temperature": {"value": "...", "confidence": 0-1}\n'
        '  },\n'
        '  "medications": [\n'
        '    {"name": "Newclav 457", "drug_class": "أموكسيسيلين/كلافولانيك", '
        '"form": "معلّق", "dosage": "4 مل كل 12 ساعة", "duration": "5 أيام", "confidence": 0.9}\n'
        '  ],\n'
        '  "as_needed": [{"name": "Cetal", "confidence": 0.8}],\n'
        '  "phone_numbers": ["01..."],\n'
        '  "notes": ["..."]\n'
        '}\n'
        "Drug enrichment: identify the active ingredient/class for each medication "
        "(e.g. Newclav→أموكسيسيلين/كلافولانيك, Amrizole→ميترونيدازول, Rhinopro→مضاد هيستامين). "
        "Recognize formulation (معلّق/شراب/نقط/أقراص/كبسولات). Interpret the handwritten "
        "dose into a clear instruction. 'Temp' is body temperature in Celsius — a lone '7' "
        "almost certainly means 37. Known Egyptian drugs to prefer if handwriting is close: "
        "Newclav, Augmentin, Hibiotic, Curam, Amrizole, Flagyl, Rhinopro, Telfast, Zyrtec, "
        "Allergyl, Histop, Nasostop, Otrivin, Ventolin, Farcolin, Brufen, Cetal, Abimol, "
        "Paramol, Zithromax, Klacid, Zisrocin.\n\n"
        "── If INVOICE/RECEIPT with line items ──\n"
        '{\n'
        '  "document_type": "invoice",\n'
        '  "layout": "mixed",\n'
        '  "header": {"seller": {"value": "", "confidence": 0}, "buyer": {...}, '
        '"invoice_number": {...}, "date": {...}},\n'
        '  "line_items": {"columns": ["الصنف", "الكمية", "السعر", "الإجمالي"], '
        '"rows": [["...", "...", "...", "..."], ...]},\n'
        '  "totals": {"subtotal": {...}, "tax": {...}, "total": {...}}\n'
        '}\n\n'
        "── If CONTRACT with clauses ──\n"
        '{\n'
        '  "document_type": "contract",\n'
        '  "layout": "mixed",\n'
        '  "header": {"parties": {...}, "subject": {...}, "date": {...}},\n'
        '  "clauses": [{"title": "...", "text": "...", "confidence": 0-1}],\n'
        '  "totals": {"contract_value": {...}, "duration": {...}}\n'
        '}\n\n'
        "── If TABLE document ──\n"
        '{"document_type": "table", "layout": "table", '
        '"table": {"columns": [...], "rows": [[...], ...]}}\n\n'
        "── If FREEFORM NARRATIVE (letter, note, paragraph) ──\n"
        '{"document_type": "letter", "layout": "narrative", '
        '"fields": {"full_text": {"value": "complete transcription", "confidence": 0-1}}}\n\n'
        "── Else (passport, national_id, business_card, simple form) ──\n"
        '{"document_type": "<type>", "layout": "form", '
        '"fields": {"<field name>": {"value": <value>, "confidence": <0-1>}, ...}}\n\n'
        f"LANGUAGE: {lang_instr}\n\n"
        "Return ONLY valid JSON, no other text, no markdown fences."
        + CALIBRATION
        + (_VISUAL_LAYOUT_INSTRUCTION if with_layout else "")
    )
    hard = _resolve_hard(mode, hard, image_bytes, media_type)
    result = _run(image_bytes, media_type, prompt, hard)
    result = _ensure_dict_result(result)
    return _postprocess_field_names(result, output_lang)


def extract_schema(image_bytes: bytes, media_type: str, target_schema: dict,
                   hard: bool = True, hint: str = "", output_lang: str = "preserve",
                   mode: str = "explicit") -> dict:
    """Extract a caller-defined set of fields.

    target_schema: {field_name: human description}
    hint: optional domain context prepended to the prompt (e.g. a prescription drug list).
    output_lang: 'preserve' (default), 'ar', or 'en' — controls value language.
    Returns: {field_name: {"value": ..., "confidence": 0-1}, ...}
    """
    field_list = "\n".join(f"- {k}: {v}" for k, v in target_schema.items())
    # Schema mode: caller fixed the field names, so we only translate VALUES, not keys.
    value_lang_instr = {
        "preserve": "Keep every value EXACTLY in the document's original language and script.",
        "ar": "Return every VALUE in Arabic. Translate from original language if needed. "
              "Preserve proper nouns (names, brands, IDs) in their original spelling.",
        "en": "Return every VALUE in English. Translate from original language if needed. "
              "Preserve proper nouns (names, brands, IDs) in their original spelling.",
    }.get(output_lang, _LANG_INSTRUCTION["preserve"])
    prompt = (
        (hint.strip() + "\n\n" if hint else "")
        + "Extract the following fields from this document. "
        "The document may be in Arabic, English, or handwritten. "
        f"{value_lang_instr} "
        "Return ONLY valid JSON, no other text. "
        "For each field, return an object with 'value' and 'confidence' (0-1). "
        "If a field is not present, set its value to null."
        + CALIBRATION + "\n\n"
        f"Fields:\n{field_list}"
    )
    return _run(image_bytes, media_type, prompt, hard)


# ---------------------------------------------------------------------------
# Expert extraction — domain-aware, validation-rich, structured-output
# ---------------------------------------------------------------------------
#
# This is the "cognitive" path used by tools whose catalog config supplies an
# expert_role + cognitive_brief. The prompt is structured into:
#
#   1. PERSONA          (who you are when reading this doc)
#   2. CONTEXT          (domain conventions that matter)
#   3. REQUIRED FIELDS  (the caller's schema — value + confidence each)
#   4. DERIVATIONS      (what to COMPUTE beyond the raw fields)
#   5. VALIDATIONS      (what to verify and flag)
#   6. OUTPUT SHAPE     (the rich JSON envelope to emit)
#
# Output envelope is consistent across all expert tools so the UI renderer and
# the per-doc-type exporters in exports.py can dispatch cleanly:
#
#   {
#     "document_type": "<type>",
#     "layout": "form" | "mixed" | "table" | "narrative" | "prescription",
#     "fields": { <name>: {"value", "confidence"}, ... },   # always present
#     "line_items": {"columns": [...], "rows": [[...]]},     # optional, mixed
#     "totals":     { <name>: {"value", "confidence"}, ... },# optional, mixed
#     "clauses":    [{"title", "text", "confidence"}, ...],  # optional, mixed
#     "validations":[{"check", "ok", "detail"}, ...],        # ALWAYS — even if empty
#     "derived":    { <name>: <computed value>, ... },       # ALWAYS — even if empty
#     "summary":    "one-sentence document summary"          # ALWAYS — written for the user
#   }


def extract_expert(image_bytes: bytes, media_type: str, *,
                   expert_role: str,
                   cognitive_brief: str,
                   schema: dict,
                   hard: bool = True,
                   output_lang: str = "preserve",
                   document_type_hint: str = "") -> dict:
    """Domain-aware extraction. The cognitive_brief should describe the
    document context, what to derive, and what to validate — see the docstring
    above for the output envelope."""
    field_list = "\n".join(f"- {k}: {v}" for k, v in schema.items())
    value_lang_instr = {
        "preserve": "Keep every value EXACTLY in the document's original language and script.",
        "ar": "Return every VALUE in Arabic. Translate from original language if needed. "
              "Preserve proper nouns (names, brands, IDs) in their original spelling.",
        "en": "Return every VALUE in English. Translate from original language if needed. "
              "Preserve proper nouns (names, brands, IDs) in their original spelling.",
    }.get(output_lang, _LANG_INSTRUCTION["preserve"])

    doc_hint = f' (document_type: "{document_type_hint}")' if document_type_hint else ""

    prompt = f"""[PERSONA]
You are {expert_role}. Read this document the way that expert would —
notice domain conventions, spot inconsistencies, compute what isn't stated
explicitly. Don't just copy text; UNDERSTAND it.

[CONTEXT & GUIDELINES]
{cognitive_brief.strip()}

[REQUIRED FIELDS]
Extract these exactly{doc_hint}, returning each as {{value, confidence}}:
{field_list}
If a required field is genuinely absent, set value=null and confidence=0.

[OUTPUT ENVELOPE — return ONE JSON OBJECT, nothing else]
{{
  "document_type": "<short type id matching the document>",
  "layout": "form" | "mixed" | "table" | "narrative",
  "fields": {{
    "<field_name>": {{"value": ..., "confidence": 0.0-1.0}}
    // every required field above, plus any other notable header data you find
  }},
  "line_items": {{"columns": [...], "rows": [[...], ...]}}, // include ONLY if the doc has tabular rows (invoice line items, bank txns, payment schedule)
  "totals":     {{"<name>": {{"value": ..., "confidence": ...}}, ...}}, // include ONLY if the doc has totals/sums
  "clauses":    [{{"title": "...", "text": "...", "confidence": ...}}, ...], // include ONLY if the doc is a contract/agreement with named clauses
  "validations": [
    {{"check": "short_name", "ok": true|false, "detail": "what you verified, in the document's language or English"}}
    // include EVERY validation from [CONTEXT & GUIDELINES] above — passing OR failing — so the user sees what was checked
  ],
  "derived": {{
    "<computed_name>": <value or short string>
    // every derivation listed in [CONTEXT & GUIDELINES] — computed values, decoded data, flags
  }},
  "summary": "one-sentence plain-language summary of what this document is and what's noteworthy"
}}

LANGUAGE: {value_lang_instr}

{CALIBRATION}

Return ONLY the JSON object. No markdown fences, no commentary."""

    hard = _resolve_hard(mode, hard, image_bytes, media_type, doctype_hint=hint)
    result = _run(image_bytes, media_type, prompt, hard)
    result = _ensure_dict_result(result)
    return _postprocess_field_names(result, output_lang)
