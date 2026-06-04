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

    # ---------------- Document parsers ----------------
    "invoice": {
        "title": "قارئ الفواتير",
        "title_en": "Invoice reader",
        "category": "parsers", "icon": "receipt-text",
        "desc": "استخرج بيانات الفاتورة: البائع، المشتري، الضريبة، الإجمالي.",
        "desc_en": "Extract invoice data: seller, buyer, tax, total.",
        "kind": "fields", "hard": True, "free": False,
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
        "schema": {
            "الأطراف": "the contracting parties", "موضوع_العقد": "subject/purpose",
            "المدة": "term/duration", "القيمة": "contract value", "شروط_الدفع": "payment terms",
            "الغرامات": "penalties / late fees", "شروط_الإنهاء": "termination conditions",
            "التوقيعات": "who signed / whether signed",
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
