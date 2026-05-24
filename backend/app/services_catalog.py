"""Catalog of OCR services. Each is a thin config over the same extraction engine.

kind:
  text            -> plain-text output (run_text with `prompt`)
  fields          -> structured fields from a fixed `schema` (extract_schema)
  table           -> tabular data to Excel/CSV (run_table)
  searchable_pdf  -> image + invisible text layer (image inputs)
"""

SERVICES = {
    "arabic-ocr": {
        "title": "استخراج النص (OCR عربي)",
        "desc": "حوّل أي صورة أو PDF إلى نص قابل للنسخ — عربي أو إنجليزي.",
        "icon": "🔤", "kind": "text", "hard": False, "free": True,
        "prompt": (
            "Transcribe ALL text in this document exactly as written, preserving line "
            "breaks and natural reading order. The text may be Arabic or English. "
            "Return ONLY the transcribed text, with no commentary."
        ),
    },
    "handwriting": {
        "title": "تحويل الخط اليدوي إلى نص",
        "desc": "اقرأ المستندات المكتوبة بخط اليد بالعربية وحوّلها إلى نص رقمي.",
        "icon": "✍️", "kind": "text", "hard": True, "free": True,
        "prompt": (
            "This document is handwritten. Read it carefully, letter by letter, and "
            "transcribe ALL of its text exactly, preserving line breaks. It may be "
            "Arabic or English. Return ONLY the transcribed text, no commentary."
        ),
    },
    "translate": {
        "title": "ترجمة المستندات",
        "desc": "اقرأ مستندًا بالعربية واحصل على ترجمته الإنجليزية فورًا.",
        "icon": "🌐", "kind": "text", "hard": False, "free": False,
        "prompt": (
            "Read all the text in this document and translate it into clear, natural "
            "English. Preserve structure (lines, lists). Return ONLY the English "
            "translation, no commentary."
        ),
    },
    "summarize": {
        "title": "تلخيص المستندات",
        "desc": "احصل على ملخّص موجز لأهم نقاط أي مستند طويل.",
        "icon": "📝", "kind": "text", "hard": False, "free": False,
        "prompt": (
            "Read this document and write a concise summary of its key points, in the "
            "document's main language. Use short bullet points. Return ONLY the summary."
        ),
    },
    "table-excel": {
        "title": "استخراج الجداول إلى Excel",
        "desc": "حوّل الجداول في الفواتير والكشوف إلى ملف Excel منظّم.",
        "icon": "📊", "kind": "table", "hard": True, "free": False,
    },
    "egyptian-id": {
        "title": "قارئ بطاقة الرقم القومي",
        "desc": "استخرج بيانات بطاقة الرقم القومي المصرية تلقائيًا.",
        "icon": "🪪", "kind": "fields", "hard": True, "free": False,
        "schema": {
            "الاسم": "full name on the card",
            "الرقم_القومي": "14-digit national ID number",
            "العنوان": "address",
            "تاريخ_الميلاد": "date of birth",
            "تاريخ_الإصدار": "issue date",
            "تاريخ_الانتهاء": "expiry date",
            "الوظيفة": "occupation if present",
        },
    },
    "passport": {
        "title": "قارئ جواز السفر",
        "desc": "استخرج بيانات جواز السفر بما في ذلك خانة القراءة الآلية (MRZ).",
        "icon": "🛂", "kind": "fields", "hard": True, "free": False,
        "schema": {
            "full_name": "full name",
            "passport_number": "passport number",
            "nationality": "nationality",
            "date_of_birth": "date of birth",
            "place_of_birth": "place of birth",
            "sex": "sex (M/F)",
            "issue_date": "issue date",
            "expiry_date": "expiry date",
        },
    },
    "commercial-register": {
        "title": "قارئ السجل التجاري",
        "desc": "استخرج بيانات السجل التجاري للشركات تلقائيًا.",
        "icon": "🏢", "kind": "fields", "hard": True, "free": False,
        "schema": {
            "اسم_الشركة": "company name",
            "رقم_السجل_التجاري": "commercial register number",
            "النشاط": "business activity",
            "العنوان": "address",
            "رأس_المال": "capital",
            "تاريخ_القيد": "registration date",
        },
    },
    "tax-card": {
        "title": "قارئ البطاقة الضريبية",
        "desc": "استخرج بيانات البطاقة الضريبية والرقم الضريبي.",
        "icon": "🧾", "kind": "fields", "hard": True, "free": False,
        "schema": {
            "الاسم": "taxpayer name",
            "رقم_التسجيل_الضريبي": "tax registration number",
            "النشاط": "activity",
            "العنوان": "address",
            "المأمورية": "tax office",
        },
    },
    "searchable-pdf": {
        "title": "PDF قابل للبحث",
        "desc": "حوّل صورة ممسوحة إلى PDF يمكن البحث في نصّه ونسخه.",
        "icon": "🔎", "kind": "searchable_pdf", "hard": False, "free": False,
    },
}
