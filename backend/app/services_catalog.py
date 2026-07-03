"""Catalog of OCR services. Each is a thin config over the same extraction engine.

kind:
  text            -> plain-text output (run_text with `prompt`)
  fields          -> structured fields from a fixed `schema` (extract_schema)
  table           -> tabular data to Excel/CSV (run_table)
  searchable_pdf  -> image + invisible text layer (image inputs)

category groups services on the /tools hub: ocr | parsers | realestate
"""

SERVICES = {
    # ---------------- OCR & AI ----------------
    "arabic-ocr": {
        "title": "استخراج النص (OCR عربي)",
        "title_en": "Arabic text extraction (OCR)",
        "category": "ocr", "icon": "scan-text",
        "desc": "حوّل أي صورة أو PDF إلى نص قابل للنسخ — عربي أو إنجليزي.",
        "desc_en": "Turn any image or PDF into copyable text — Arabic or English.",
        "kind": "text", "hard": True, "free": True,
        "prompt": ("Transcribe ALL text in this document exactly as written, preserving line "
                   "breaks and natural reading order. It may be Arabic or English. "
                   "Return ONLY the transcribed text, no commentary."),
    },
    "handwriting": {
        "title": "تحويل الخط اليدوي إلى نص",
        "title_en": "Handwriting to text",
        "category": "ocr", "icon": "pen-line",
        "desc": "اقرأ المستندات المكتوبة بخط اليد بالعربية وحوّلها إلى نص رقمي.",
        "desc_en": "Read Arabic handwritten documents and turn them into digital text.",
        "kind": "text", "hard": True, "free": True,
        "prompt": ("This document is handwritten. Read it carefully, letter by letter, and "
                   "transcribe ALL its text exactly, preserving line breaks. Arabic or English. "
                   "Return ONLY the transcribed text, no commentary."),
    },
    "translate": {
        "title": "ترجمة المستندات",
        "title_en": "Document translation",
        "category": "ocr", "icon": "languages",
        "desc": "اقرأ مستندًا بالعربية واحصل على ترجمته الإنجليزية فورًا.",
        "desc_en": "Read an Arabic document and get an instant English translation.",
        "kind": "text", "hard": True, "free": False,
        "prompt": ("Read all the text in this document and translate it into clear, natural "
                   "English, preserving structure. Return ONLY the English translation."),
    },
    "summarize": {
        "title": "تلخيص المستندات",
        "title_en": "Document summarization",
        "category": "ocr", "icon": "align-left",
        "desc": "احصل على ملخّص موجز لأهم نقاط أي مستند طويل.",
        "desc_en": "Get a concise summary of the key points of any long document.",
        "kind": "text", "hard": True, "free": False,
        "prompt": ("Read this document and write a concise bullet-point summary of its key "
                   "points, in the document's main language. Return ONLY the summary."),
    },
    "entity-detection": {
        "title": "كشف الكيانات",
        "title_en": "Entity detection",
        "category": "ocr", "icon": "scan-search",
        "desc": "استخرج الأسماء والبريد والهواتف والتواريخ والمبالغ من أي مستند دفعة واحدة.",
        "desc_en": "Extract names, emails, phones, dates and amounts from any document in one shot.",
        "kind": "fields", "hard": False, "free": False,
        "schema": {
            "الأسماء": "all person and company names found, comma-separated",
            "البريد_الإلكتروني": "all email addresses, comma-separated",
            "أرقام_الهاتف": "all phone numbers, comma-separated",
            "التواريخ": "all dates found, comma-separated",
            "المبالغ_والإجماليات": "all monetary amounts/totals with currency",
            "الأرقام_الضريبية": "any tax/VAT/registration numbers",
        },
    },
    "auto-classify": {
        "title": "تصنيف ووسم المستند",
        "title_en": "Auto-classify & tag",
        "category": "ocr", "icon": "tags",
        "desc": "تعرّف على نوع المستند ولغته وأضف وسومًا وملخصًا تلقائيًا.",
        "desc_en": "Detect the document type, language, and add tags and a summary automatically.",
        "kind": "fields", "hard": False, "free": False,
        "schema": {
            "نوع_المستند": "the document type",
            "اللغة": "main language of the document",
            "الوسوم": "3-6 short descriptive tags, comma-separated",
            "ملخص": "one-sentence summary of the document",
        },
    },
    "validate": {
        "title": "التحقق من البيانات",
        "title_en": "Data validation",
        "category": "ocr", "icon": "badge-check",
        "desc": "افحص المستند واكتشف التناقضات والأخطاء والتواريخ المنتهية والمبالغ غير المتطابقة.",
        "desc_en": "Audit a document for inconsistencies, errors, expired dates and mismatched totals.",
        "kind": "text", "hard": True, "free": False,
        "prompt": ("Carefully check this document for problems: inconsistent or wrong totals, "
                   "expired or invalid dates, missing required fields, contradictory or suspicious "
                   "values. Return a concise report listing any issues found, or confirm it looks "
                   "consistent. Reply in the document's language."),
    },
    "table-excel": {
        "title": "استخراج الجداول إلى Excel",
        "title_en": "Tables to Excel",
        "category": "ocr", "icon": "table",
        "desc": "حوّل الجداول في الفواتير والكشوف إلى ملف Excel منظّم.",
        "desc_en": "Turn tables from invoices and statements into structured Excel files.",
        "kind": "table", "hard": True, "free": False,
    },
    "searchable-pdf": {
        "title": "PDF قابل للبحث",
        "title_en": "Searchable PDF",
        "category": "ocr", "icon": "file-search",
        "desc": "حوّل صورة ممسوحة إلى PDF يمكن البحث في نصّه ونسخه.",
        "desc_en": "Turn a scanned image into a PDF whose text can be searched and copied.",
        "kind": "searchable_pdf", "hard": True, "free": False,
    },
    # ---------------- New free utility tools (Wave 15A.2) ----------------
    "language-detect": {
        "title": "كشف اللغة",
        "title_en": "Language detection",
        "category": "ocr", "icon": "languages",
        "desc": "حدّد اللغة الأساسية في المستند ونسبة كل لغة عند التداخل — سريع ومجاني.",
        "desc_en": "Identify the primary language of a document and the ratio when mixed — fast and free.",
        "kind": "text", "hard": False, "free": True,
        "prompt": ("Identify the language(s) used in this document. Reply with a one-line "
                   "summary like: 'Primary: Arabic (Egyptian dialect, 92%) · Secondary: Latin "
                   "drug names (8%)'. If only one language, just name it and confidence. "
                   "Return ONLY that one-line summary."),
    },
    "doc-quality-check": {
        "title": "فحص جودة المستند",
        "title_en": "Document quality check",
        "category": "ocr", "icon": "check-circle",
        "desc": "افحص جودة المسح قبل الدفع: الإضاءة، الدقّة، الميلان، الوهج. مجاني.",
        "desc_en": "Check scan quality before paying: lighting, resolution, tilt, glare. Free.",
        "kind": "text", "hard": False, "free": True,
        "prompt": ("You are a document-imaging quality auditor. Review this document image and "
                   "produce a SHORT quality report in 4-6 bullet points covering: lighting, "
                   "focus/blur, tilt/rotation, glare/shadows, contrast, and OCR-readiness. End "
                   "with a single-line verdict: 'READY for OCR ✓' or 'RE-SCAN recommended — "
                   "specifically: <reason>'. Reply in the user's language (Arabic or English). "
                   "Return ONLY the report, no preamble."),
    },
    "redact-pii": {
        "title": "إخفاء البيانات الشخصية",
        "title_en": "Redact PII",
        "category": "ocr", "icon": "shield",
        "desc": "ابحث عن البيانات الشخصية (أسماء، أرقام، عناوين) واقترح صياغة بدون كشفها — مجاني.",
        "desc_en": "Find personal data (names, IDs, addresses) and suggest a redacted rewrite — free.",
        "kind": "text", "hard": False, "free": True,
        "prompt": ("This document may contain personal data (PII). Re-emit the document text "
                   "with PII REDACTED: replace each personal item with a placeholder like "
                   "[NAME], [ID], [PHONE], [EMAIL], [ADDRESS], [DATE], or [AMOUNT]. Keep "
                   "everything else verbatim so the structure stays readable. Reply in the "
                   "document's original language. Return ONLY the redacted text."),
    },

    # ---------------- Document parsers ----------------
    "invoice": {
        "title": "قارئ الفواتير",
        "title_en": "Invoice reader",
        "category": "parsers", "icon": "receipt-text",
        "desc": "استخرج بيانات الفاتورة: البائع، المشتري، الضريبة، الإجمالي.",
        "desc_en": "Extract invoice data: seller, buyer, tax, total.",
        "kind": "fields", "hard": True, "free": False,
        "expert_role": "an Egyptian-licensed accountant reviewing this tax invoice",
        "cognitive_brief": """
Egyptian/GCC tax invoices follow ETA/ZATCA formats. Conventions to watch:
- VAT in Egypt is typically 14% (general) or 5% (essentials), some items exempt.
- Saudi VAT is 15%, UAE VAT is 5%.
- Tax ID format (EG): ###-###-### or 9 contiguous digits; (SA) 15 digits starting with 3.
- Common currencies: EGP, SAR, AED, USD. If you see "ج.م" or "L.E." → EGP.
- Buyer often labelled العميل/المُشترى, seller as المُورِّد/البائع.
- Identifiers (invoice number, tax ID, LPO/PO number) must be transcribed VERBATIM,
  digit-for-digit, keeping the original separators exactly as printed. Do NOT insert,
  remove, or re-group hyphens/spaces (e.g. "INV-2026-0847" stays "INV-2026-0847",
  never "INV-2026-08-47"). If a digit is unclear, lower the confidence — do not guess a separator.

BEYOND THE REQUIRED FIELDS, extract:
- line_items: every visible row as columns=[الصنف, الكمية, سعر الوحدة, الإجمالي] and rows=[[...], ...]
- totals: subtotal, tax, grand_total — each as {value, confidence} (these go in the "totals" key of the envelope, NOT "fields")

DERIVE (compute these even if not stated, put in "derived"):
- currency: ISO 4217 code (EGP/SAR/AED/USD/…)
- tax_rate_pct: tax / subtotal × 100, rounded to 1 decimal
- computed_subtotal: sum of line_items totals
- computed_tax: subtotal × (tax_rate_pct/100)
- computed_grand_total: subtotal + tax
- line_item_count: number of rows

VALIDATE (every check goes in "validations", ok=true even when passing):
- subtotal_matches: does computed_subtotal equal the stated subtotal? (1 EGP tolerance)
- total_matches: does subtotal + tax equal the stated grand_total? (1 EGP tolerance)
- tax_rate_known: is tax_rate_pct in {0, 5, 14, 15} ± 0.5? (Egyptian/GCC standard rates)
- tax_id_format: does the tax ID match a known country format?
- date_sanity: is the invoice date not in the future?
""",
        "schema": {
            "اسم_البائع": "seller/vendor name", "اسم_المشتري": "buyer/customer name",
            "رقم_الفاتورة": "invoice number", "التاريخ": "invoice date",
            "تاريخ_الاستحقاق": "due date", "الرقم_الضريبي": "tax/VAT number",
            "العملة": "currency", "الإجمالي_قبل_الضريبة": "subtotal before tax",
            "الضريبة": "tax/VAT amount", "الإجمالي": "grand total",
        },
    },
    "egyptian-id": {
        "title": "قارئ بطاقة الرقم القومي",
        "title_en": "Egyptian National ID reader",
        "category": "parsers", "icon": "id-card",
        "desc": "استخرج بيانات بطاقة الرقم القومي المصرية تلقائيًا.",
        "desc_en": "Automatically extract data from an Egyptian national ID card.",
        "kind": "fields", "hard": False, "free": False,
        "expert_role": "an Egyptian civil-registry officer reading a National ID card",
        "cognitive_brief": """
The Egyptian National ID is 14 digits with embedded data:
  Position 1     = century-of-birth digit  (2 = 1900s, 3 = 2000s)
  Positions 2-3  = year of birth (YY)
  Positions 4-5  = month of birth (MM)
  Positions 6-7  = day of birth (DD)
  Positions 8-9  = governorate code (01=Cairo, 02=Alexandria, 11=Damietta, 12=Daqahlia, 13=Sharqia, 14=Qaliubiya, 21=Giza, 22=Beni Suef, …)
  Positions 10-12= sequence number
  Position 13    = gender (ODD = male, EVEN = female)
  Position 14    = checksum

DERIVE (compute from the 14 digits, put in "derived"):
- birthdate_from_id: full ISO date YYYY-MM-DD reconstructed from digits 1-7
- gender_from_id: "male" or "female" from digit 13
- governorate_from_id: name in Arabic AND English from digits 8-9
- age_years: today's year minus birth year (rough)
- days_until_expiry: signed integer (negative = already expired)

VALIDATE (every check in "validations"):
- id_length: exactly 14 digits
- id_first_digit: must be 2 or 3
- id_date_valid: digits 1-7 decode to a real calendar date
- name_matches_card: extracted name matches the typed name field on card
- not_expired: expiry date is in the future (if expiry was extracted)
- birthdate_matches: extracted birthdate field equals birthdate_from_id

The card may have a photo, signature, governorate seal, and finger-printed
"إصدار" (issue) date stamped on the back. Don't confuse issue with expiry.
""",
        "schema": {
            "الاسم": "full name", "الرقم_القومي": "14-digit national ID number",
            "العنوان": "address", "تاريخ_الميلاد": "date of birth",
            "تاريخ_الإصدار": "issue date", "تاريخ_الانتهاء": "expiry date",
            "الوظيفة": "occupation if present",
        },
    },
    "passport": {
        "title": "قارئ جواز السفر",
        "title_en": "Passport reader",
        "category": "parsers", "icon": "book-user",
        "desc": "استخرج بيانات جواز السفر بما في ذلك خانة القراءة الآلية (MRZ).",
        "desc_en": "Extract passport data including the machine-readable zone (MRZ).",
        "kind": "fields", "hard": False, "free": False,
        "expert_role": "an immigration officer who reads passports daily and knows the ICAO 9303 MRZ standard",
        "cognitive_brief": """
Every modern passport's bottom carries a two-line MRZ (Machine-Readable Zone) in
OCR-B font. Format (Type 3 — passports): 44 chars × 2 lines.
  Line 1: P<{ISSUER_CODE}{SURNAME}<<{GIVEN_NAMES}
  Line 2: {PASSPORT_NO}{check}{NATIONALITY}{YYMMDD_BIRTH}{check}{SEX}{YYMMDD_EXPIRY}{check}{PERSONAL_NO}{check}{composite_check}

Country codes are 3 letters: EGY=Egypt, SAU=Saudi, ARE=UAE, USA=US, GBR=UK.
'<' fills empty positions and acts as a separator.

DERIVE (put in "derived"):
- mrz_line_1, mrz_line_2: the raw OCR-read MRZ strings if visible
- birthdate_iso_from_mrz: YYYY-MM-DD reconstructed from MRZ (century inferred — values >25 = 19xx, ≤25 = 20xx, typical heuristic)
- expiry_iso_from_mrz: same conversion for expiry
- nationality_full: country name in English+Arabic from the 3-letter code
- issuer_full: same for issuer code
- days_until_expiry: integer (negative = expired)

VALIDATE (every check in "validations"):
- mrz_present: did you see the two-line MRZ?
- mrz_length_ok: each MRZ line is 44 chars
- name_matches: visual name above MRZ equals the MRZ-decoded name
- dob_matches: visual date_of_birth equals MRZ-decoded birthdate
- passport_number_matches: visual number equals MRZ field
- not_expired: expiry is in the future
- valid_6_months: expiry is ≥6 months out (Schengen / many countries require this)

If a field appears ONLY in the MRZ and not in the visual zone, that's a defect — note it.
""",
        "schema": {
            "full_name": "full name", "passport_number": "passport number",
            "nationality": "nationality", "date_of_birth": "date of birth",
            "place_of_birth": "place of birth", "sex": "sex (M/F)",
            "issue_date": "issue date", "expiry_date": "expiry date",
        },
    },
    "commercial-register": {
        "title": "قارئ السجل التجاري",
        "title_en": "Commercial-register reader",
        "category": "parsers", "icon": "building-2",
        "desc": "استخرج بيانات السجل التجاري للشركات تلقائيًا.",
        "desc_en": "Automatically extract company commercial-register data.",
        "kind": "fields", "hard": True, "free": False,
        "schema": {
            "اسم_الشركة": "company name", "رقم_السجل_التجاري": "commercial register number",
            "النشاط": "business activity", "العنوان": "address",
            "رأس_المال": "capital", "تاريخ_القيد": "registration date",
        },
    },
    "tax-card": {
        "title": "قارئ البطاقة الضريبية",
        "title_en": "Tax card reader",
        "category": "parsers", "icon": "badge-percent",
        "desc": "استخرج بيانات البطاقة الضريبية والرقم الضريبي.",
        "desc_en": "Extract tax-card details and the tax registration number.",
        "kind": "fields", "hard": False, "free": False,
        "schema": {
            "الاسم": "taxpayer name", "رقم_التسجيل_الضريبي": "tax registration number",
            "النشاط": "activity", "العنوان": "address", "المأمورية": "tax office",
        },
    },
    "business-card": {
        "title": "ماسح بطاقات العمل",
        "title_en": "Business-card scanner",
        "category": "parsers", "icon": "contact-round",
        "desc": "حوّل بطاقة العمل إلى جهة اتصال منظّمة.",
        "desc_en": "Turn a business card into a structured contact.",
        "kind": "fields", "hard": False, "free": False,
        "schema": {
            "الاسم": "person name", "المسمى_الوظيفي": "job title", "الشركة": "company",
            "الهاتف": "phone numbers", "البريد_الإلكتروني": "email",
            "الموقع_الإلكتروني": "website", "العنوان": "address",
        },
    },
    "utility-bill": {
        "title": "قارئ فواتير المرافق",
        "title_en": "Utility-bill reader",
        "category": "parsers", "icon": "lightbulb",
        "desc": "استخرج بيانات فواتير الكهرباء والمياه والغاز.",
        "desc_en": "Extract data from electricity, water and gas bills.",
        "kind": "fields", "hard": False, "free": False,
        "schema": {
            "اسم_المشترك": "subscriber name", "رقم_الحساب": "account number",
            "رقم_العداد": "meter number", "نوع_الخدمة": "service type (electricity/water/gas)",
            "قيمة_الفاتورة": "bill amount", "تاريخ_الإصدار": "issue date",
            "تاريخ_الاستحقاق": "due date", "الاستهلاك": "consumption",
        },
    },
    "bank-statement": {
        "title": "قارئ كشف الحساب البنكي",
        "title_en": "Bank-statement reader",
        "category": "parsers", "icon": "landmark",
        "desc": "استخرج بيانات كشف الحساب البنكي وأرصدته.",
        "desc_en": "Extract bank-statement data and balances.",
        "kind": "fields", "hard": True, "free": False,
        "expert_role": "a corporate-banking analyst auditing a customer's account statement",
        "cognitive_brief": """
A bank statement has a HEADER (account info + period + balances) and a
TRANSACTIONS table (date, description, debit/credit, running balance).

Beyond the required header fields, EXTRACT the full transaction table as
line_items with columns=[التاريخ, البيان, مدين, دائن, الرصيد] and rows=[[...], ...].
Include EVERY transaction visible, in chronological order.

DERIVE (put in "derived"):
- transaction_count: number of rows in line_items
- detected_currency: from any balance or transaction value (EGP/SAR/AED/USD)
- iban_country: first 2 letters of IBAN (EG/SA/AE/US) if IBAN present
- iban_valid: simple mod-97 check on the IBAN (true/false)
- computed_total_deposits: sum of all credit (دائن) values across line_items
- computed_total_withdrawals: sum of all debit (مدين) values
- computed_closing_balance: opening_balance + deposits - withdrawals
- largest_credit: max single credit amount across transactions
- largest_debit: max single debit amount across transactions
- avg_monthly_balance: rough avg of running-balance column

VALIDATE (every check in "validations"):
- iban_format_ok: IBAN length matches country standard (EG=29, SA=24, AE=23)
- deposits_match: computed_total_deposits ≈ stated إجمالي_الإيداعات (1 unit tolerance)
- withdrawals_match: same for withdrawals
- closing_balance_matches: computed_closing_balance ≈ stated closing balance
- transactions_in_period: every transaction date falls within the stated period
- no_duplicate_dates_amounts: flag identical (date, amount, description) rows as possible double-posting
""",
        "schema": {
            "اسم_صاحب_الحساب": "account holder name", "رقم_الحساب": "account number",
            "IBAN": "IBAN if present", "اسم_البنك": "bank name", "الفترة": "statement period",
            "الرصيد_الافتتاحي": "opening balance", "الرصيد_الختامي": "closing balance",
            "إجمالي_الإيداعات": "total deposits", "إجمالي_السحوبات": "total withdrawals",
        },
    },
    "prescription": {
        "title": "قارئ الروشتات الطبية",
        "title_en": "Medical-prescription reader",
        "category": "parsers", "icon": "pill",
        "desc": "حوّل الروشتة الطبية (حتى المكتوبة بخط اليد) إلى بيانات منظّمة وأدوية مُفسّرة.",
        "desc_en": "Turn a medical prescription (even handwritten) into structured data with parsed medications.",
        "kind": "prescription", "hard": True, "free": False,
        # The existing extract_prescription path already produces a rich shape
        # (patient + medications[]); these notes layer in extra validation and
        # interaction-checking when the expert path is selected.
        "expert_role": "a clinical pharmacist reading an Egyptian doctor's handwritten prescription (روشتة)",
        "cognitive_brief": """
Common Egyptian Rx conventions:
- 'R/' starts the medicine list.
- 'D.G' = diagnosis. 'Age' = years. 'Wt' = weight in kg. 'Temp' = °C (normal 36-41; lone '7' usually means 37).
- Dosage shorthand: BID = twice daily, TID = three times, QID = four, PRN = as needed,
  OD = once daily, hs = at bedtime, ac = before meals, pc = after meals.

Known Egyptian drugs (prefer if handwriting is close):
Newclav, Augmentin, Hibiotic, Curam, Amrizole, Flagyl, Rhinopro, Telfast, Zyrtec,
Allergyl, Histop, Nasostop, Otrivin, Sinucare, Ventolin, Farcolin, Brufen, Cetal,
Abimol, Paramol, Zithromax, Klacid, Zisrocin, Voltaren, Nexium, Concor, Norvasc.

DERIVE (put in "derived"):
- medication_count: how many distinct medicines on the list
- has_handwritten_dose: any medication with confidence < 0.7 due to handwriting
- antibiotic_present: any medicine that's an antibiotic (penicillin, cephalosporin, macrolide…)
- nsaid_present: ibuprofen, diclofenac, ketoprofen, naproxen, brufen, voltaren
- duration_days_total: longest duration field across all medicines

VALIDATE (put in "validations"):
- has_patient_name: patient name extracted
- has_doctor_name: doctor name/signature extracted
- has_date: date extracted and in the past
- medication_dosages_present: every medication has a dosage AND duration
- temp_sanity: if temperature present, must be 30 ≤ temp ≤ 42 °C
- age_sanity: if age present, must be 0 ≤ age ≤ 120 years
- pediatric_dose_warning: if age < 12 years AND a typically-adult dose seen (e.g. >500mg of amoxicillin), flag it
- antibiotic_duration: if antibiotic_present, full duration should be ≥ 5 days (typical course)

NEVER inflate confidence on unclear handwriting. If you can't read it, set confidence ≤ 0.5.
""",
        "hint": (
            "This is a handwritten Egyptian medical prescription (روشتة). "
            "If a handwritten drug name is close to a known Egyptian drug, prefer its correct spelling: "
            "Newclav, Augmentin, Hibiotic, Curam, Amrizole, Flagyl, Rhinopro, Telfast, Zyrtec, Allergyl, "
            "Histop, Nasostop, Otrivin, Sinucare, Ventolin, Farcolin, Brufen, Cetal, Abimol, Paramol, "
            "Zithromax, Klacid, Zisrocin. "
            "'Temp' is body temperature in Celsius (normally 36-41); a lone '7' almost certainly means 37. "
            "'Age' is in years, 'Wt' is weight in kg, 'D.G' is the diagnosis, and 'R/' begins the medicines. "
            "Never inflate confidence on unclear handwriting."
        ),
        "schema": {
            "اسم_المريض": "patient name", "اسم_الطبيب": "doctor name", "التاريخ": "date",
            "الأدوية": "list of medicines", "الجرعات": "dosages",
            "التعليمات": "instructions", "التشخيص": "diagnosis if present",
        },
    },
    "shipping-label": {
        "title": "قارئ بوالص الشحن",
        "title_en": "Shipping-label reader",
        "category": "parsers", "icon": "package",
        "desc": "استخرج بيانات الشحنة من بوليصة الشحن.",
        "desc_en": "Extract shipment data from a shipping label.",
        "kind": "fields", "hard": True, "free": False,
        "schema": {
            "المرسل": "sender", "المستلم": "recipient", "عنوان_التسليم": "delivery address",
            "رقم_الشحنة": "shipment number", "شركة_الشحن": "carrier",
            "الوزن": "weight", "رقم_التتبع": "tracking number",
        },
    },

    # ---------------- Real estate ----------------
    "sale-contract": {
        "title": "عقد بيع عقار",
        "title_en": "Property sale contract",
        "category": "realestate", "icon": "home",
        "desc": "استخرج بيانات عقد بيع العقار: الأطراف، الوحدة، السعر، السداد.",
        "desc_en": "Extract property sale-contract data: parties, unit, price, payment.",
        "kind": "fields", "hard": True, "free": False,
        "schema": {
            "البائع": "seller", "المشتري": "buyer", "وصف_العقار": "property description",
            "رقم_الوحدة": "unit number", "المساحة": "area", "سعر_البيع": "sale price",
            "طريقة_السداد": "payment method/plan", "تاريخ_العقد": "contract date",
        },
    },
    "lease-contract": {
        "title": "عقد إيجار",
        "title_en": "Lease contract",
        "category": "realestate", "icon": "scroll-text",
        "desc": "استخرج بيانات عقد الإيجار: المؤجر، المستأجر، المدة، القيمة.",
        "desc_en": "Extract lease-contract data: landlord, tenant, term, rent.",
        "kind": "fields", "hard": True, "free": False,
        "schema": {
            "المؤجر": "landlord", "المستأجر": "tenant", "وصف_العقار": "property",
            "مدة_الإيجار": "lease term", "قيمة_الإيجار": "rent amount",
            "الدفعة_المقدمة": "deposit/advance", "تاريخ_البداية": "start date",
            "تاريخ_النهاية": "end date",
        },
    },
    "ownership-doc": {
        "title": "وثيقة ملكية",
        "title_en": "Property-ownership document",
        "category": "realestate", "icon": "scroll",
        "desc": "استخرج بيانات وثيقة/سند ملكية العقار.",
        "desc_en": "Extract data from a property-ownership document/title.",
        "kind": "fields", "hard": True, "free": False,
        "schema": {
            "اسم_المالك": "owner name", "رقم_الوثيقة": "document number",
            "وصف_العقار": "property description", "المساحة": "area",
            "الموقع": "location", "تاريخ_التسجيل": "registration date",
        },
    },
    "tenant-data": {
        "title": "بيانات المستأجر",
        "title_en": "Tenant data",
        "category": "realestate", "icon": "user",
        "desc": "استخرج بيانات المستأجر لملء نظام إدارة العقارات.",
        "desc_en": "Extract tenant data to populate a property-management system.",
        "kind": "fields", "hard": False, "free": False,
        "schema": {
            "اسم_المستأجر": "tenant name", "رقم_الهوية": "ID number", "الهاتف": "phone",
            "رقم_الوحدة": "unit number", "قيمة_الإيجار": "rent",
            "تاريخ_بداية_العقد": "contract start", "تاريخ_نهاية_العقد": "contract end",
        },
    },
    "unit-data": {
        "title": "بيانات الوحدة العقارية",
        "title_en": "Property-unit data",
        "category": "realestate", "icon": "building",
        "desc": "استخرج مواصفات الوحدة العقارية من كتيّب أو عرض.",
        "desc_en": "Extract property-unit specs from a brochure or listing.",
        "kind": "fields", "hard": True, "free": False,
        "schema": {
            "رقم_الوحدة": "unit number", "النوع": "type", "المساحة": "area",
            "الطابق": "floor", "عدد_الغرف": "number of rooms",
            "السعر": "price", "الحالة": "status (available/sold/reserved)",
        },
    },
    "payment-schedule": {
        "title": "جدول السداد",
        "title_en": "Payment schedule",
        "category": "realestate", "icon": "calendar-clock",
        "desc": "استخرج جدول الأقساط والدفعات إلى Excel.",
        "desc_en": "Extract an installment / payment schedule to Excel.",
        "kind": "table", "hard": True, "free": False,
    },
    "contract-clauses": {
        "title": "تحليل بنود العقد",
        "title_en": "Contract-clause analysis",
        "category": "realestate", "icon": "scale",
        "desc": "اكتشف ولخّص بنود العقد: الأطراف، المدة، السداد، الغرامات، الإنهاء.",
        "desc_en": "Surface and summarize the contract clauses: parties, term, payment, penalties, termination.",
        "kind": "fields", "hard": True, "free": False,
        "expert_role": "a corporate lawyer reviewing an Arabic real-estate / commercial contract for risk",
        "cognitive_brief": """
Arabic contracts typically open with البسملة, then identify الأطراف (parties),
موضوع العقد (subject), then numbered clauses (بند الأول، الثاني، ...), then
التوقيعات at the bottom.

BEYOND the required fields, identify the full CLAUSE TABLE and emit it in the
"clauses" key of the envelope (NOT as a flat field). Each clause should be:
  {"title": "بند الدفع", "text": "<the full clause text>", "confidence": 0-1, "risk": "low|medium|high"}

DERIVE (put in "derived"):
- party_count: how many distinct parties
- clause_count: how many numbered clauses you identified
- contract_value_numeric: pure number from "القيمة" (currency in separate field)
- duration_months: term/duration converted to months (1 year → 12)
- has_arbitration: boolean — does any clause name a specific court or arbitration forum?
- has_force_majeure: boolean — clause covers force majeure (قوة قاهرة)?
- has_confidentiality: boolean — confidentiality / NDA clause present?
- has_auto_renewal: boolean — does it auto-renew silently?
- highest_risk_clauses: array of titles flagged as 'high' risk

VALIDATE (every check in "validations"):
- parties_count_ge_2: at least 2 parties named
- has_subject: subject/purpose clause present
- has_term: duration/term specified
- has_payment_terms: payment schedule defined
- has_signatures: at least the count_of_parties signatures visible
- governing_law_stated: does the contract specify governing law (e.g. القانون المصري)?
- effective_date_present: does it state when the contract begins?

For risk grading: clauses with one-sided indemnity, broad confidentiality with
no exit, unlimited liability, or unfair termination = high. Standard mutual
obligations = low.
""",
        "schema": {
            "الأطراف": "the contracting parties", "موضوع_العقد": "subject/purpose",
            "المدة": "term/duration", "القيمة": "contract value", "شروط_الدفع": "payment terms",
            "الغرامات": "penalties / late fees", "شروط_الإنهاء": "termination conditions",
            "التوقيعات": "who signed / whether signed",
        },
    },

    "tax-card": {
        # promoted to expert — Egyptian VAT-registration card is short but verifiable
        "title": "قارئ البطاقة الضريبية",
        "title_en": "Tax card reader",
        "category": "parsers", "icon": "badge-percent",
        "desc": "استخرج بيانات البطاقة الضريبية والرقم الضريبي.",
        "desc_en": "Extract tax-card details and the tax registration number.",
        "kind": "fields", "hard": False, "free": False,
        "expert_role": "an Egyptian tax-authority officer authenticating a البطاقة الضريبية",
        "cognitive_brief": """
The Egyptian tax card (البطاقة الضريبية) shows: taxpayer name, tax registration
number, activity, address, and the issuing tax office (المأمورية).

Egyptian tax IDs are 9 digits, often shown as ###-###-### (e.g. 304-221-119).

DERIVE (put in "derived"):
- tax_id_digits_only: the 9-digit number without dashes
- tax_id_format_canonical: rendered as ###-###-### regardless of source format
- activity_category: short label categorizing the activity (e.g. "خدمات استشارية", "تجارة تجزئة", "تصنيع")

VALIDATE:
- tax_id_length: exactly 9 digits after stripping non-digits
- tax_id_visible: was the tax ID legibly extracted with confidence ≥ 0.8?
- maamoreya_named: was a specific tax office mentioned?
- address_present: physical address line was extracted
""",
        "schema": {
            "الاسم": "taxpayer name", "رقم_التسجيل_الضريبي": "tax registration number",
            "النشاط": "activity", "العنوان": "address", "المأمورية": "tax office",
        },
    },
}

# Hub display order + labels for the category groups
CATEGORIES = [
    ("ocr", "التعرّف الضوئي والذكاء"),
    ("parsers", "قارئات المستندات"),
    ("realestate", "العقارات"),
]

CATEGORIES_EN = [
    ("ocr", "OCR & AI"),
    ("parsers", "Document parsers"),
    ("realestate", "Real estate"),
]


def localized(lang: str):
    """Return (services, categories) with English labels swapped in when lang=='en'.
    Falls back to Arabic for any service missing an EN translation."""
    if lang == "en":
        svc = {}
        for slug, s in SERVICES.items():
            svc[slug] = {
                **s,
                "title": s.get("title_en", s["title"]),
                "desc": s.get("desc_en", s["desc"]),
            }
        return svc, CATEGORIES_EN
    return SERVICES, CATEGORIES
