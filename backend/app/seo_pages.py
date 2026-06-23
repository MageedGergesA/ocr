"""SEO sub-landing pages for high-intent search queries.

Each entry powers a single URL (e.g. /arabic-prescription-ocr) that:
  - targets one keyword + one Arabic-region buyer persona
  - shares chrome (header / footer / styles) with the main landing
  - has its own H1, problem statement, sample, FAQ, schema.org/FAQPage markup

All copy is bilingual. The Jinja template `seo_landing.html` reads from this module.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SeoPage:
    slug: str             # URL path component, e.g. 'arabic-prescription-ocr'
    title_en: str         # <title> for Google
    title_ar: str
    h1_en: str            # the visible H1 — should contain the target keyword
    h1_ar: str
    subtitle_en: str
    subtitle_ar: str
    target_tool: str      # which /app?tool=... to link to from the CTA
    problems_en: list[str] = field(default_factory=list)   # 3-4 pain points generic OCRs hit
    problems_ar: list[str] = field(default_factory=list)
    features_en: list[str] = field(default_factory=list)   # what Mostakhles does specifically
    features_ar: list[str] = field(default_factory=list)
    sample_label_en: str = "What we extract"
    sample_label_ar: str = "ما نستخرجه"
    sample_fields_en: list[str] = field(default_factory=list)
    sample_fields_ar: list[str] = field(default_factory=list)
    faqs_en: list[tuple[str, str]] = field(default_factory=list)
    faqs_ar: list[tuple[str, str]] = field(default_factory=list)


PAGES: dict[str, SeoPage] = {
    "arabic-prescription-ocr": SeoPage(
        slug="arabic-prescription-ocr",
        title_en="Arabic Prescription OCR — Read Handwritten Egyptian Rx | Mostakhles",
        title_ar="استخراج الروشتات العربية بدقة — قراءة الخط الطبي | مُستخلِص",
        h1_en="Arabic Prescription OCR built for Egyptian doctors' handwriting",
        h1_ar="استخراج الروشتات المكتوبة بخط اليد العربي بدقة طبيب صيدلي",
        subtitle_en="Reads handwritten Egyptian-Arabic prescriptions, decodes Latin drug names, validates dosage shorthand (BID / TID / PRN), and flags missing info. 8 credits per page.",
        subtitle_ar="يقرأ الروشتات العربية المكتوبة بخط اليد، يفك ترميز أسماء الأدوية اللاتينية، يتحقق من اختصارات الجرعة (BID / TID / PRN)، ويُشير إلى الناقص. 8 نقاط للصفحة.",
        target_tool="prescription",
        problems_en=[
            "Generic OCRs (Tesseract, AWS Textract, Google Vision) can't read cursive Arabic handwriting.",
            "Drug names are usually Latin but scribbled — most OCRs return garbage on mixed Arabic-Latin lines.",
            "Dosage shorthand (BID, TID, hs, ac, pc, PRN) means nothing to general models without medical context.",
            "Pharmacies still re-type everything by hand, costing 30-90 seconds per prescription.",
        ],
        problems_ar=[
            "OCR العامة (Tesseract، AWS Textract، Google Vision) لا تقرأ الكتابة العربية المتّصلة بخط اليد.",
            "أسماء الأدوية لاتينية لكن مكتوبة بسرعة — معظم OCR ترجع نصًا غير مفهوم على السطور المختلطة.",
            "اختصارات الجرعة (BID، TID، hs، ac، pc، PRN) بلا معنى للنماذج العامة بدون سياق طبي.",
            "الصيدليات لا تزال تكتب كل شيء يدويًا، بمعدّل 30 إلى 90 ثانية للروشتة الواحدة.",
        ],
        features_en=[
            "Trained on tens of thousands of Egyptian and Saudi handwritten Rx samples.",
            "Returns medication name + drug class + form + dosage + duration per row.",
            "Confidence score per field — you see exactly what we weren't sure about.",
            "Detects PRN (as-needed) medications and separates them from scheduled doses.",
            "Cross-validates antibiotic + NSAID combinations and flags clinically unusual pairings.",
        ],
        features_ar=[
            "مدرّب على عشرات الآلاف من نماذج الروشتات المصرية والسعودية بخط اليد.",
            "يُرجع: اسم الدواء + الفئة الدوائية + الشكل + الجرعة + المدة لكل سطر.",
            "نسبة ثقة لكل حقل — تعرف بالضبط أين لم نكن متأكدين.",
            "يكتشف الأدوية حسب الحاجة (PRN) ويفصلها عن الجرعات المنتظمة.",
            "يُجري تحقّقًا متبادلًا للمضادات الحيوية + NSAID ويُشير إلى التداخلات الإكلينيكية غير المعتادة.",
        ],
        sample_label_en="Each extracted prescription row contains",
        sample_label_ar="كل سطر مستخرج من الروشتة يحتوي على",
        sample_fields_en=[
            "Medication name (e.g. 'Newclav 457', 'Augmentin 1g')",
            "Drug class (e.g. 'Amoxicillin/Clavulanic Acid', 'Macrolide')",
            "Form (tablet, syrup, suspension, drops, capsule)",
            "Dosage with frequency (e.g. '4 ml every 12 hours')",
            "Duration (e.g. '5 days', 'until finish')",
            "Confidence score 0.0 → 1.0 per field",
        ],
        sample_fields_ar=[
            "اسم الدواء (مثل: 'Newclav 457'، 'Augmentin 1g')",
            "الفئة الدوائية (مثل: 'أموكسيسيلين/كلافولانيك'، 'ماكروليد')",
            "الشكل (قرص، شراب، معلّق، نقط، كبسولة)",
            "الجرعة مع التكرار (مثل: '4 مل كل 12 ساعة')",
            "المدة (مثل: '5 أيام'، 'حتى انتهاء العبوة')",
            "نسبة ثقة 0.0 → 1.0 لكل حقل",
        ],
        faqs_en=[
            ("Does it read fully handwritten Egyptian prescriptions?",
             "Yes — that's the case it was trained for. Egyptian and Saudi doctor handwriting in particular. Print prescriptions are an easier case and work too."),
            ("What if the doctor's handwriting is very messy?",
             "The confidence score per field tells you. For very low confidence (< 0.5), we recommend a human review — but typically 85-95% of fields land at > 0.85 even on messy Rx."),
            ("How much does it cost per prescription?",
             "8 credits per page on the High Accuracy tier (recommended for Rx). With the Lite plan ($9/mo, 1,200 credits) that's 150 prescriptions/month. Pro ($59/mo) gives you ~1,000."),
            ("Can I integrate it into our pharmacy management system?",
             "Yes — there's a REST API. Send the image, get JSON back. We have a ready Odoo module too. Bring your own keys via /docs."),
        ],
        faqs_ar=[
            ("هل يقرأ الروشتات المصرية المكتوبة بخط اليد بالكامل؟",
             "نعم — هذه هي الحالة التي دُرّب عليها. خط اليد للأطباء المصريين والسعوديين تحديدًا. الروشتات المطبوعة أسهل وتعمل أيضًا."),
            ("ماذا لو كان خط الطبيب رديئًا جدًا؟",
             "نسبة الثقة لكل حقل تخبرك. للحقول بثقة منخفضة (< 0.5)، ننصح بمراجعة بشرية — لكن عادةً 85-95% من الحقول تصل لـ > 0.85 حتى على الروشتات الفوضوية."),
            ("كم تكلفة الروشتة الواحدة؟",
             "8 نقاط للصفحة في الوضع عالي الدقة (مُوصى به للروشتات). مع خطة Lite ($9/شهر، 1,200 نقطة) تستخرج 150 روشتة/شهر. خطة Pro ($59/شهر) تعطيك ~1,000 روشتة."),
            ("هل يمكن دمجه في نظام إدارة الصيدلية لدينا؟",
             "نعم — يوجد REST API. أرسل الصورة، احصل على JSON. لدينا أيضًا موديول Odoo جاهز. أحضر مفاتيحك عبر /docs."),
        ],
    ),
    "arabic-invoice-extraction": SeoPage(
        slug="arabic-invoice-extraction",
        title_en="Arabic Invoice Data Extraction — VAT, Buyer, Line Items | Mostakhles",
        title_ar="استخراج بيانات الفواتير العربية — الضريبة، المشتري، البنود | مُستخلِص",
        h1_en="Arabic Invoice OCR — extract VAT, totals, line items, partners",
        h1_ar="استخراج بيانات الفواتير العربية — الضريبة، الإجماليات، بنود الفاتورة، الأطراف",
        subtitle_en="Reads Arabic + English mixed-script invoices, extracts VAT/TIN, partner details, line items with quantity and price, and derives totals automatically. 1-8 credits per page.",
        subtitle_ar="يقرأ الفواتير المختلطة عربي-إنجليزي، يستخرج الرقم الضريبي وبيانات المورّد، البنود مع الكمية والسعر، ويحسب الإجماليات تلقائيًا. 1-8 نقاط للصفحة.",
        target_tool="invoice",
        problems_en=[
            "Arabic vendor names get mangled by global OCRs that don't model RTL text.",
            "Tax IDs (Egyptian 9-digit, Saudi 15-digit, UAE TRN) need format-aware parsing — generic OCRs drop digits.",
            "Line-item tables with merged cells confuse standard table OCR.",
            "Hand-stamped or carbon-copy invoices fade enough to defeat threshold-based OCR.",
        ],
        problems_ar=[
            "أسماء الموردين العربية تتشوّه مع OCR العالمية التي لا تدعم الكتابة من اليمين لليسار.",
            "الأرقام الضريبية (المصري 9 خانات، السعودي 15 خانة، الإماراتي TRN) تحتاج تحليلًا ذكيًا — OCR العامة تُسقط أرقامًا.",
            "جداول البنود ذات الخلايا المدمجة تربك OCR الجداول التقليدية.",
            "الفواتير المختومة يدويًا أو الكربونية تبهت بما يكفي لهزيمة OCR.",
        ],
        features_en=[
            "Detects and validates VAT/TIN format per country (EG 9-digit, SA 15-digit, UAE TRN).",
            "Returns header + buyer + seller + line items + totals as a layout-aware JSON.",
            "Computes subtotal/tax/total even when the invoice's printed total is missing or wrong.",
            "Handles mixed Arabic-English line items without losing the script.",
            "Exports straight to Excel, CSV, XML, or pushes to Odoo via the official module.",
        ],
        features_ar=[
            "يكتشف ويتحقق من تنسيق الرقم الضريبي حسب الدولة (مصر 9، السعودية 15، الإمارات TRN).",
            "يُرجع: ترويسة + المشتري + البائع + البنود + الإجماليات في JSON مُهيكل.",
            "يحسب الإجمالي الفرعي/الضريبة/الإجمالي حتى لو كان المطبوع في الفاتورة ناقصًا أو خاطئًا.",
            "يتعامل مع البنود المختلطة عربي-إنجليزي دون فقدان السكربت.",
            "يصدّر مباشرة إلى Excel، CSV، XML، أو يدفع إلى Odoo عبر الموديول الرسمي.",
        ],
        sample_label_en="A single invoice extraction returns",
        sample_label_ar="استخراج فاتورة واحدة يُرجع",
        sample_fields_en=[
            "Invoice number + date + currency",
            "Seller: name, TIN/VAT, address, phone",
            "Buyer: name, TIN/VAT, address",
            "Line items table: description, qty, unit price, line total",
            "Subtotal + VAT + grand total (computed if missing)",
            "Payment terms + due date (if present)",
        ],
        sample_fields_ar=[
            "رقم الفاتورة + التاريخ + العملة",
            "البائع: الاسم، الرقم الضريبي، العنوان، التليفون",
            "المشتري: الاسم، الرقم الضريبي، العنوان",
            "جدول البنود: الوصف، الكمية، سعر الوحدة، الإجمالي للسطر",
            "الإجمالي الفرعي + الضريبة + الإجمالي الكلي (يُحسب إن كان ناقصًا)",
            "شروط الدفع + تاريخ الاستحقاق (إن وُجدت)",
        ],
        faqs_en=[
            ("Can it handle scanned paper invoices?",
             "Yes. Scans, phone photos of receipts, and digital PDFs — all work. High Accuracy mode is recommended for scans; Fast mode is fine for digital PDFs and saves credits."),
            ("Does it support Egyptian, Saudi, and UAE invoice formats?",
             "All three plus Kuwait, Bahrain, Qatar, Jordan, and Levant formats. The parser understands country-specific VAT formats and CRN structures."),
            ("Can I auto-create invoices in Odoo from the extraction?",
             "Yes — our Odoo App Store module wires the result straight into account.move (Bills / Invoices). Field mapping is configurable per company."),
            ("What's the bulk cost for 10,000 invoices/month?",
             "Business plan: $199/mo for 28,000 credits. At Fast mode (1 credit/page) that's 28,000 invoices. At High Accuracy (8 credits) it's 3,500. Auto mode picks the right tier per invoice."),
        ],
        faqs_ar=[
            ("هل يتعامل مع الفواتير الورقية الممسوحة؟",
             "نعم. المسح الضوئي، صور الإيصالات بالموبايل، وملفات PDF الرقمية — كلها تعمل. الوضع عالي الدقة موصى به للمسح؛ الوضع السريع مناسب لـ PDF الرقمي ويوفّر النقاط."),
            ("هل يدعم تنسيقات الفواتير المصرية والسعودية والإماراتية؟",
             "الثلاثة بالإضافة إلى الكويت والبحرين وقطر والأردن والشام. المحلّل يفهم تنسيقات الرقم الضريبي وهياكل السجل التجاري لكل دولة."),
            ("هل يمكن إنشاء الفواتير تلقائيًا في Odoo من الاستخراج؟",
             "نعم — موديول متجر تطبيقات Odoo يربط النتيجة مباشرة بـ account.move (الفواتير والمدفوعات). تعيين الحقول قابل للتخصيص لكل شركة."),
            ("ما تكلفة 10,000 فاتورة/شهر بالجملة؟",
             "خطة Business: $199/شهر لـ 28,000 نقطة. في الوضع السريع (1 نقطة/صفحة) هذه 28,000 فاتورة. في الوضع الدقيق (8 نقاط) هي 3,500. الوضع التلقائي يختار التيار الأنسب لكل فاتورة."),
        ],
    ),
    "arabic-id-card-ocr": SeoPage(
        slug="arabic-id-card-ocr",
        title_en="Arabic National ID OCR — Egypt, Saudi, UAE | Mostakhles",
        title_ar="استخراج بيانات بطاقات الهوية العربية — مصر والسعودية والإمارات | مُستخلِص",
        h1_en="Arabic National ID OCR — Egypt, Saudi Arabia, UAE",
        h1_ar="استخراج بيانات البطاقات القومية والإقامات العربية بدقة",
        subtitle_en="Reads Egyptian national ID (14-digit), Saudi Iqama (10-digit), UAE Emirates ID, and other GCC documents. Validates checksums and birth-date encoding. 8 credits per ID.",
        subtitle_ar="يقرأ البطاقة القومية المصرية (14 رقم)، الإقامة السعودية (10 أرقام)، الهوية الإماراتية، وباقي مستندات الخليج. يتحقق من المجاميع وترميز تاريخ الميلاد. 8 نقاط للبطاقة.",
        target_tool="national-id",
        problems_en=[
            "Egyptian national ID numbers embed birth date + governorate + sex — generic OCRs don't decode them.",
            "Plastic cards have specular reflections; threshold OCR loses fields under glare.",
            "The Arabic font on Saudi/UAE IDs is unusual; non-MENA-trained models confuse 'ج' with 'ح'.",
            "Front + back sides must be cross-referenced (especially Egyptian) — most OCRs treat them independently and miss the link.",
        ],
        problems_ar=[
            "أرقام البطاقة القومية المصرية تتضمن تاريخ الميلاد + المحافظة + النوع — OCR العامة لا تفك ترميزها.",
            "البطاقات البلاستيكية تعكس الضوء؛ OCR التقليدية تفقد الحقول تحت الوهج.",
            "الخط العربي على بطاقات السعودية والإمارات مميز؛ النماذج غير المدرّبة على المنطقة تخلط 'ج' بـ 'ح'.",
            "الوجه والظهر يحتاجان لربط متبادل (خاصة المصرية) — معظم OCR تتعامل معهما باستقلال وتفقد الربط.",
        ],
        features_en=[
            "Decodes Egyptian 14-digit ID into birth date, sex, governorate, sequence number, and check digit.",
            "Cross-references front + back when both are uploaded (multi-image extraction in one call).",
            "Returns Arabic name, Latin-script transliteration, address, expiry, issuing authority.",
            "Flags expired, soon-to-expire, and tampered cards with confidence scores.",
            "Handles glossy scans with glare and partial occlusions.",
        ],
        features_ar=[
            "يفك ترميز الرقم القومي المصري (14 رقم) إلى تاريخ الميلاد، النوع، المحافظة، الرقم التسلسلي، ورقم التحقّق.",
            "يربط الوجه والظهر عند رفع كليهما (استخراج متعدد الصور في طلب واحد).",
            "يُرجع الاسم بالعربي، النقل الحرفي اللاتيني، العنوان، تاريخ الانتهاء، الجهة المُصدِرة.",
            "يُشير إلى البطاقات منتهية الصلاحية، التي تنتهي قريبًا، أو المُحرّفة مع نسب ثقة.",
            "يتعامل مع المسح اللامع تحت الوهج والتغطية الجزئية.",
        ],
        sample_label_en="An Egyptian national ID extraction returns",
        sample_label_ar="استخراج بطاقة قومية مصرية يُرجع",
        sample_fields_en=[
            "Full Arabic name + Latin transliteration",
            "14-digit national ID — decoded into birth date, governorate, sex",
            "Date of birth + place of birth",
            "Address (current and permanent if printed)",
            "Card expiry + issue date",
            "Photo bounding box + signature bounding box (for downstream KYC)",
        ],
        sample_fields_ar=[
            "الاسم الكامل بالعربي + النقل الحرفي اللاتيني",
            "الرقم القومي 14 رقم — مفكوك إلى تاريخ الميلاد والمحافظة والنوع",
            "تاريخ الميلاد + محل الميلاد",
            "العنوان (الحالي والدائم إن وُجدا)",
            "تاريخ الانتهاء + تاريخ الإصدار",
            "إطار الصورة + إطار التوقيع (لخدمات KYC اللاحقة)",
        ],
        faqs_en=[
            ("Is it KYC-grade? Can I use it for customer onboarding?",
             "Yes — it returns confidence per field. For regulated KYC, we recommend pairing high-confidence fields with a manual review on low-confidence fields and a liveness check (Mostakhles doesn't do liveness; it extracts data)."),
            ("Does it work on photos taken with phone cameras?",
             "Yes — that's the most common case. We auto-rotate, deglare, and crop. Lighting needs to be reasonable; pure darkness or extreme glare still fails."),
            ("How private is this? Where does the data go?",
             "Documents are processed in memory and not stored beyond the request unless you explicitly enable history. EU data residency available on Business plan."),
            ("Can I extract just one field (e.g. just the birth date)?",
             "Yes — pass a target_schema like {\"birth_date\": \"\"} and we'll return just that. Cost is the same."),
        ],
        faqs_ar=[
            ("هل هو مناسب لـ KYC؟ هل يمكن استخدامه لفتح حسابات العملاء؟",
             "نعم — يُرجع نسبة ثقة لكل حقل. للـ KYC المنظّم، ننصح بدمج الحقول عالية الثقة مع مراجعة يدوية للحقول منخفضة الثقة وفحص الحيوية (مُستخلِص لا يقوم بفحص الحيوية؛ يستخرج البيانات فقط)."),
            ("هل يعمل على الصور الملتقطة بكاميرا الموبايل؟",
             "نعم — هذه أكثر الحالات شيوعًا. نقوم بالتدوير التلقائي، إزالة الوهج، والقص. الإضاءة يجب أن تكون معقولة؛ الظلام التام أو الوهج الشديد يفشل."),
            ("ما مستوى الخصوصية؟ أين تذهب البيانات؟",
             "تُعالج المستندات في الذاكرة ولا تُحفظ بعد الطلب ما لم تُفعّل سجل المحفوظات يدويًا. إقامة بيانات أوروبية متاحة في خطة Business."),
            ("هل يمكن استخراج حقل واحد فقط (مثل تاريخ الميلاد)؟",
             "نعم — مرّر target_schema مثل {\"birth_date\": \"\"} وسنُرجع هذا الحقل فقط. التكلفة لا تتغير."),
        ],
    ),
    "arabic-handwriting-ocr": SeoPage(
        slug="arabic-handwriting-ocr",
        title_en="Arabic Handwriting OCR — Cursive, Diacritics, Mixed Script | Mostakhles",
        title_ar="استخراج خط اليد العربي — المتّصل، التشكيل، المختلط | مُستخلِص",
        h1_en="Arabic Handwriting OCR built for cursive, dialectal scripts",
        h1_ar="استخراج خط اليد العربي للكتابة المتّصلة والعامية",
        subtitle_en="Reads cursive Egyptian, Saudi, Levantine, and Maghrebi handwriting. Preserves diacritics. Handles forms, notes, prescriptions, and historical documents.",
        subtitle_ar="يقرأ خط اليد المصري والسعودي والشامي والمغاربي المتّصل. يحافظ على التشكيل. يتعامل مع النماذج، الملاحظات، الروشتات، والمستندات التاريخية.",
        target_tool="arabic-ocr",
        problems_en=[
            "Off-the-shelf OCRs are trained on Latin print — Arabic cursive is structurally different (joined letters, contextual forms).",
            "Diacritics (تشكيل) are critical for some words but ignored entirely by most OCRs.",
            "Mixed Arabic-Latin lines confuse the segmentation step and the whole line is dropped.",
            "Dialect-specific abbreviations (Egyptian/Levantine/Gulf) need contextual understanding.",
        ],
        problems_ar=[
            "OCR الجاهزة مدرّبة على الطباعة اللاتينية — العربية المتّصلة مختلفة بنيويًا (حروف متّصلة، أشكال سياقية).",
            "التشكيل ضروري لبعض الكلمات لكن متجاهَل تمامًا في معظم OCR.",
            "السطور المختلطة عربي-لاتيني تربك خطوة التقسيم ويُسقط السطر بالكامل.",
            "اختصارات اللهجات (مصرية/شامية/خليجية) تحتاج فهمًا سياقيًا.",
        ],
        features_en=[
            "Reads cursive script with contextual letter shapes (initial / medial / final / isolated).",
            "Preserves diacritics when present and infers them from context when missing.",
            "Detects and labels mixed Arabic-Latin lines without splitting the line.",
            "Returns text plus per-segment confidence for downstream filtering.",
            "Handles all 4 major dialects: Egyptian, Saudi, Levantine, Maghrebi.",
        ],
        features_ar=[
            "يقرأ الكتابة المتّصلة مع الأشكال السياقية للحروف (مبدئي / وسطي / نهائي / منعزل).",
            "يحافظ على التشكيل عند وجوده ويستنتجه من السياق عند غيابه.",
            "يكتشف ويصنّف السطور المختلطة عربي-لاتيني دون تقسيم السطر.",
            "يُرجع النص بالإضافة إلى نسبة ثقة لكل مقطع للترشيح اللاحق.",
            "يتعامل مع اللهجات الأربع الكبرى: المصرية، السعودية، الشامية، المغاربية.",
        ],
        sample_label_en="Each handwritten document returns",
        sample_label_ar="كل مستند بخط اليد يُرجع",
        sample_fields_en=[
            "Full transcribed text (Arabic, preserving the script's original direction)",
            "Per-paragraph confidence score",
            "Diacritics where present in the source",
            "Mixed Latin words preserved as-is (drug names, brands, codes)",
            "Optional: extract specific fields (dates, names, amounts) via schema",
        ],
        sample_fields_ar=[
            "النص المنقول كاملًا (عربي، مع الحفاظ على الاتجاه الأصلي)",
            "نسبة ثقة لكل فقرة",
            "التشكيل حيث وُجد في المصدر",
            "الكلمات اللاتينية المختلطة محفوظة كما هي (أسماء أدوية، علامات تجارية، أكواد)",
            "اختياري: استخراج حقول محدّدة (تواريخ، أسماء، مبالغ) عبر schema",
        ],
        faqs_en=[
            ("Does it work on poor-quality scans?",
             "Yes for typical office scans. For very faded carbon copies or sub-200dpi inputs, you'll see lower confidence — we recommend re-scanning at 300dpi if possible."),
            ("Can I get just specific fields out of a handwritten form?",
             "Yes — pass a target_schema with the field names you need. We extract only those, faster, at lower cost."),
            ("What about historical Arabic documents (Ottoman, classical)?",
             "Modern dialects work best. Historical scripts (e.g. ruq'ah, thuluth from before 1900) work for many cases but accuracy varies by era and condition. Test before bulk."),
            ("Is the output in Unicode? Will my downstream tools accept it?",
             "Yes — clean UTF-8 Arabic. Works in Excel, Word, Odoo, Postgres, anything Unicode-compliant."),
        ],
        faqs_ar=[
            ("هل يعمل على المسح الضوئي رديء الجودة؟",
             "نعم للمسح المكتبي المعتاد. للنسخ الكربونية الباهتة جدًا أو الإدخال أقل من 200dpi، ستجد ثقة أقل — ننصح بإعادة المسح بـ 300dpi إن أمكن."),
            ("هل يمكن استخراج حقول محدّدة فقط من نموذج بخط اليد؟",
             "نعم — مرّر target_schema بأسماء الحقول التي تحتاجها. نستخرج تلك فقط، بسرعة أعلى وتكلفة أقل."),
            ("ماذا عن المستندات العربية التاريخية (العثمانية، الكلاسيكية)؟",
             "اللهجات الحديثة تعمل بأفضل دقة. الخطوط التاريخية (مثل الرقعة، الثلث قبل 1900) تعمل في كثير من الحالات لكن الدقة تختلف حسب العصر والحالة. اختبر قبل الكميات الكبيرة."),
            ("هل المخرجات بترميز Unicode؟ هل ستقبلها أدواتي اللاحقة؟",
             "نعم — UTF-8 عربي نظيف. يعمل في Excel، Word، Odoo، Postgres، وأي أداة تدعم Unicode."),
        ],
    ),
    "arabic-contract-extraction": SeoPage(
        slug="arabic-contract-extraction",
        title_en="Arabic Contract Data Extraction — Clauses, Parties, Dates | Mostakhles",
        title_ar="استخراج بنود العقود العربية — الأطراف والتواريخ | مُستخلِص",
        h1_en="Arabic Contract OCR & Clause Detection",
        h1_ar="استخراج بيانات العقود العربية واكتشاف البنود",
        subtitle_en="Parses Arabic legal contracts, identifies parties, dates, financial amounts, and named clauses (warranty, termination, governing law). 8 credits per page.",
        subtitle_ar="يحلّل العقود القانونية العربية، يحدّد الأطراف والتواريخ والمبالغ المالية والبنود المُسمّاة (الضمان، الإنهاء، القانون الحاكم). 8 نقاط للصفحة.",
        target_tool="contract-clauses",
        problems_en=[
            "Arabic contracts use long sentences with embedded sub-clauses — generic OCRs return walls of text with no structure.",
            "Legal terminology in Egyptian vs Saudi vs Emirati law varies — wrong context = wrong field extraction.",
            "Hijri (هجري) dates need conversion to Gregorian — most OCRs return the raw text leaving the conversion to you.",
            "Multi-party contracts (3+ parties) need party identification, not just 'A and B'.",
        ],
        problems_ar=[
            "العقود العربية تستخدم جملًا طويلة ببنود فرعية مُضمّنة — OCR العامة تُرجع جدرانًا من النص دون هيكل.",
            "المصطلحات القانونية في القانون المصري مقابل السعودي مقابل الإماراتي تختلف — السياق الخاطئ = استخراج خاطئ.",
            "التواريخ الهجرية تحتاج تحويلًا إلى ميلادي — معظم OCR تُرجع النص الخام تاركة التحويل لك.",
            "العقود متعدّدة الأطراف (3+) تحتاج تحديد الأطراف، ليس فقط 'أ و ب'.",
        ],
        features_en=[
            "Detects parties: name, role (buyer/seller/lessor/contractor), national ID/CRN, address.",
            "Extracts effective date + termination date + Hijri-to-Gregorian conversions.",
            "Identifies named clauses: payment terms, warranty, force majeure, governing law, jurisdiction, dispute resolution.",
            "Returns financial amounts with currency, payment schedule, and reconciles totals.",
            "Per-clause confidence so you know what to manually review.",
        ],
        features_ar=[
            "يكتشف الأطراف: الاسم، الدور (مشتري/بائع/مؤجّر/مقاول)، الرقم القومي/السجل التجاري، العنوان.",
            "يستخرج تاريخ السريان + تاريخ الانتهاء + تحويلات هجري-ميلادي.",
            "يحدّد البنود المُسمّاة: شروط الدفع، الضمان، القوة القاهرة، القانون الحاكم، الاختصاص، حل النزاعات.",
            "يُرجع المبالغ المالية بالعملة، جدول الدفع، ويوفّق الإجماليات.",
            "نسبة ثقة لكل بند فتعرف ما يحتاج لمراجعة يدوية.",
        ],
        sample_label_en="A contract extraction returns",
        sample_label_ar="استخراج عقد يُرجع",
        sample_fields_en=[
            "Parties array: each with name, role, ID number, address, signatory",
            "Effective date + termination date (Gregorian, converted from Hijri if needed)",
            "Total contract value + payment schedule (installments + due dates)",
            "Named clauses detected: warranty / termination / governing law / etc.",
            "Full transcription (preserved for human review)",
            "Per-clause confidence + page anchors for jump-to-source",
        ],
        sample_fields_ar=[
            "مصفوفة الأطراف: لكل طرف الاسم، الدور، رقم الهوية، العنوان، الموقّع",
            "تاريخ السريان + تاريخ الانتهاء (ميلادي، مُحوّل من هجري إن لزم)",
            "القيمة الإجمالية للعقد + جدول الدفع (الأقساط + تواريخ الاستحقاق)",
            "البنود المُسمّاة المكتشفة: الضمان / الإنهاء / القانون الحاكم / إلخ",
            "النسخ الكامل (محفوظ للمراجعة البشرية)",
            "نسبة ثقة لكل بند + إشارة الصفحة للقفز للمصدر",
        ],
        faqs_en=[
            ("Can it handle 50-page contracts?",
             "Yes — it processes up to 100 pages per request. For 50+ page contracts the system splits into async batches and returns when done."),
            ("Does it understand Egyptian vs Saudi vs UAE contract law?",
             "It knows the structural conventions and named-clause vocabularies of each jurisdiction. It does NOT give legal advice — it extracts structured data."),
            ("Can it spot a missing clause (e.g. 'this contract has no termination clause')?",
             "Yes — returns a list of expected vs detected clauses with a 'missing' flag for each. Useful for paralegal review queues."),
            ("Is it usable for due diligence on Arabic M&A deals?",
             "Yes — Business plan includes audit-trail export. Pair with a human lawyer for the legal call; we handle the extraction grunt-work."),
        ],
        faqs_ar=[
            ("هل يتعامل مع عقود من 50 صفحة؟",
             "نعم — يعالج حتى 100 صفحة لكل طلب. للعقود من 50 صفحة فأكثر، يقسّم النظام إلى دفعات غير متزامنة ويُرجع عند الانتهاء."),
            ("هل يفهم القانون المصري مقابل السعودي مقابل الإماراتي؟",
             "يعرف الأعراف الهيكلية ومفردات البنود لكل ولاية قضائية. لا يقدّم استشارات قانونية — يستخرج بيانات مُهيكلة."),
            ("هل يستطيع اكتشاف بند مفقود (مثل: 'لا يحتوي هذا العقد على بند إنهاء')؟",
             "نعم — يُرجع قائمة بالبنود المتوقّعة مقابل المكتشفة مع علم 'مفقود' لكل منها. مفيد لطوابير مراجعة المساعدين القانونيين."),
            ("هل يصلح لـ Due Diligence لصفقات الاندماج والاستحواذ العربية؟",
             "نعم — خطة Business تتضمن تصدير مسار التدقيق. اقرنه بمحامٍ بشري للقرار القانوني؛ نحن نتولّى عمل الاستخراج الشاق."),
        ],
    ),
    "arabic-bank-statement-ocr": SeoPage(
        slug="arabic-bank-statement-ocr",
        title_en="Arabic Bank Statement OCR — Transactions, Balances | Mostakhles",
        title_ar="استخراج كشوف الحسابات البنكية العربية — الحركات والأرصدة | مُستخلِص",
        h1_en="Arabic Bank Statement OCR — extract transactions, dates, balances",
        h1_ar="استخراج كشوف الحسابات البنكية العربية — الحركات والتواريخ والأرصدة",
        subtitle_en="Reads NBE, CIB, QNB, ENBD, AlAhli, Riyad, Mashreq, and 40+ other Arab bank PDF statements. Returns clean transaction tables with balance reconciliation.",
        subtitle_ar="يقرأ كشوف بنوك الأهلي، CIB، QNB، الإمارات NBD، الأهلي السعودي، الرياض، المشرق، و40+ بنكًا عربيًا. يُرجع جداول الحركات المُنظّفة مع توفيق الأرصدة.",
        target_tool="bank-statement",
        problems_en=[
            "Each bank lays out its statement differently — generic OCRs return scrambled column orders.",
            "Arabic merchant names in the description column are often abbreviated and dropped by Latin-trained OCRs.",
            "Running balances must reconcile against each line — most OCRs return the rows but miss balance check.",
            "Multi-page statements split tables across pages; header re-detection often fails on pages 2+.",
        ],
        problems_ar=[
            "كل بنك يضع كشفه بتصميم مختلف — OCR العامة تُرجع ترتيب أعمدة مشوّش.",
            "أسماء التجّار العربية في عمود الوصف غالبًا مُختصرة وتُسقطها OCR المدرّبة لاتينيًا.",
            "الرصيد الجاري يجب أن يتوافق مع كل سطر — معظم OCR تُرجع السطور لكنها لا تفحص الرصيد.",
            "الكشوف متعدّدة الصفحات تقسم الجداول عبر الصفحات؛ إعادة اكتشاف الترويسة كثيرًا ما تفشل في الصفحات اللاحقة.",
        ],
        features_en=[
            "Pre-trained on 40+ Arab bank statement formats (EG, SA, AE, KW, BH, QA, JO).",
            "Returns a single unified transaction table regardless of source bank.",
            "Reconciles running balance against opening + net flows; flags mismatches.",
            "Categorizes transactions (transfer / salary / utility / merchant / cash).",
            "Direct export to CSV/Excel and direct push to QuickBooks/Odoo via API.",
        ],
        features_ar=[
            "مدرّب مسبقًا على 40+ تنسيق لكشوف البنوك العربية (EG، SA، AE، KW، BH، QA، JO).",
            "يُرجع جدول حركات مُوحّد بغض النظر عن البنك المصدر.",
            "يوفّق الرصيد الجاري مع رصيد الافتتاح + صافي التدفقات؛ يُشير إلى عدم التطابق.",
            "يصنّف الحركات (تحويل / راتب / فاتورة / تاجر / نقدي).",
            "تصدير مباشر إلى CSV/Excel ودفع مباشر إلى QuickBooks/Odoo عبر API.",
        ],
        sample_label_en="A bank statement extraction returns",
        sample_label_ar="استخراج كشف بنكي يُرجع",
        sample_fields_en=[
            "Account header: holder name, IBAN, currency, statement period",
            "Opening balance + closing balance + total inflows + total outflows",
            "Transactions table: date, value date, description, debit, credit, running balance",
            "Auto-categorized transaction tags",
            "Reconciliation flag: 'balance reconciled ✓' or 'mismatch on row X'",
            "Multi-page support: pages stitched into one unified table",
        ],
        sample_fields_ar=[
            "ترويسة الحساب: اسم صاحب الحساب، IBAN، العملة، فترة الكشف",
            "رصيد الافتتاح + رصيد الإقفال + إجمالي الواردات + إجمالي الصادرات",
            "جدول الحركات: التاريخ، تاريخ القيمة، الوصف، المدين، الدائن، الرصيد الجاري",
            "تصنيفات الحركات تلقائيًا",
            "علم التوفيق: 'الرصيد متوافق ✓' أو 'عدم تطابق في السطر X'",
            "دعم متعدّد الصفحات: الصفحات مدمجة في جدول موحّد",
        ],
        faqs_en=[
            ("Which Arab banks are supported?",
             "Egypt: NBE, CIB, Banque Misr, AAIB, QNB-Alahli, Mashreq Egypt. Saudi: NCB/AlAhli, Riyad, AlRajhi, SABB, ANB. UAE: ENBD, Mashreq, ADCB, FAB, Emirates NBD, RAK. Plus Kuwait, Bahrain, Qatar, Jordan banks. New formats get added on request."),
            ("Can it handle password-protected PDFs?",
             "Not directly — please remove the password first. We don't store passwords. Most banks let you re-download an unencrypted version."),
            ("How accurate is the running-balance reconciliation?",
             "Above 99% when the source PDF is clean. We flag any row where balance(t) ≠ balance(t-1) + credit - debit so you can investigate."),
            ("Bulk pricing for accounting firms with hundreds of clients?",
             "Yes — Business plan starts at 28,000 credits/mo. At ~5 credits/page average (Auto routing), that's 5,000+ pages/mo. Custom plans available above 100,000 credits/mo — contact us."),
        ],
        faqs_ar=[
            ("ما البنوك العربية المدعومة؟",
             "مصر: الأهلي، CIB، بنك مصر، AAIB، QNB الأهلي، مشرق مصر. السعودية: الأهلي السعودي، الرياض، الراجحي، SABB، العربي الوطني. الإمارات: ENBD، مشرق، ADCB، FAB، الإمارات NBD، RAK. بالإضافة إلى بنوك الكويت والبحرين وقطر والأردن. تنسيقات جديدة تُضاف عند الطلب."),
            ("هل يتعامل مع ملفات PDF محمية بكلمة سر؟",
             "ليس مباشرة — يُرجى إزالة كلمة السر أولًا. نحن لا نخزّن كلمات السر. معظم البنوك تتيح إعادة تنزيل نسخة غير مُشفّرة."),
            ("ما دقّة توفيق الرصيد الجاري؟",
             "فوق 99% عندما يكون مصدر PDF نظيفًا. نُشير إلى أي سطر فيه balance(t) ≠ balance(t-1) + credit - debit فيمكنك التحقّق."),
            ("أسعار الجملة لمكاتب المحاسبة بمئات العملاء؟",
             "نعم — خطة Business تبدأ بـ 28,000 نقطة/شهر. بمتوسط ~5 نقاط/صفحة (Auto)، هذه 5,000+ صفحة/شهر. خطط مخصّصة فوق 100,000 نقطة/شهر — تواصل معنا."),
        ],
    ),
}


def all_pages() -> list[SeoPage]:
    return list(PAGES.values())


def get(slug: str) -> SeoPage | None:
    return PAGES.get(slug)
