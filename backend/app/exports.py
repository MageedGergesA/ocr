"""Export extracted rows to CSV / Excel / Word / PDF (Arabic-safe).

Each exporter takes `rows` = [{"page", "field", "value", "confidence"}, ...]
and returns (bytes, media_type, filename).
"""
import csv
import io

ARABIC_FONT = "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf"


def _conf_str(conf) -> str:
    return f"{round(conf * 100)}%" if isinstance(conf, (int, float)) else ""


def to_csv(rows, title="extraction"):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["page", "field", "value", "confidence"])
    for r in rows:
        w.writerow([r.get("page"), r.get("field"), r.get("value"), _conf_str(r.get("confidence"))])
    data = ("﻿" + buf.getvalue()).encode("utf-8")  # BOM so Excel reads Arabic
    return data, "text/csv; charset=utf-8", f"{title}.csv"


def to_xlsx(rows, title="extraction"):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Extraction"
    ws.sheet_view.rightToLeft = True
    ws.append(["صفحة", "الحقل", "القيمة", "الثقة"])
    for r in rows:
        val = "" if r.get("value") is None else str(r.get("value"))
        ws.append([r.get("page"), r.get("field"), val, _conf_str(r.get("confidence"))])
    buf = io.BytesIO()
    wb.save(buf)
    return (buf.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            f"{title}.xlsx")


def to_docx(rows, title="extraction"):
    from docx import Document

    doc = Document()
    doc.add_heading("نتيجة الاستخراج", level=1)
    table = doc.add_table(rows=1, cols=4)
    table.style = "Table Grid"
    hdr = table.rows[0].cells
    hdr[0].text, hdr[1].text, hdr[2].text, hdr[3].text = "صفحة", "الحقل", "القيمة", "الثقة"
    for r in rows:
        c = table.add_row().cells
        c[0].text = str(r.get("page", ""))
        c[1].text = str(r.get("field", ""))
        c[2].text = "" if r.get("value") is None else str(r.get("value"))
        c[3].text = _conf_str(r.get("confidence"))
    buf = io.BytesIO()
    doc.save(buf)
    return (buf.getvalue(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            f"{title}.docx")


_FONT_READY = False


def _ar(text):
    """Shape + reorder Arabic so it renders correctly in PDF."""
    import arabic_reshaper
    from bidi.algorithm import get_display
    return get_display(arabic_reshaper.reshape("" if text is None else str(text)))


def to_pdf(rows, title="extraction"):
    global _FONT_READY
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    if not _FONT_READY:
        pdfmetrics.registerFont(TTFont("Naskh", ARABIC_FONT))
        _FONT_READY = True

    head = ParagraphStyle("h", fontName="Naskh", fontSize=15, alignment=2)
    cell = ParagraphStyle("c", fontName="Naskh", fontSize=10, alignment=2, wordWrap="RTL", leading=14)

    def P(text):
        return Paragraph(_ar(text), cell)

    # Columns reversed for RTL reading: confidence | value | field | page
    table_data = [[P("الثقة"), P("القيمة"), P("الحقل"), P("صفحة")]]
    for r in rows:
        table_data.append([
            P(_conf_str(r.get("confidence"))), P(r.get("value")),
            P(r.get("field")), P(r.get("page")),
        ])

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=title)
    table = Table(table_data, colWidths=[55, 215, 140, 45])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563eb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f8fb")]),
    ]))
    doc.build([Paragraph(_ar("نتيجة الاستخراج — مُستخلِص"), head), Spacer(1, 12), table])
    return buf.getvalue(), "application/pdf", f"{title}.pdf"


EXPORTERS = {"csv": to_csv, "xlsx": to_xlsx, "docx": to_docx, "pdf": to_pdf}


# ---- Table exports (columns + rows) ----

def table_to_xlsx(columns, rows, title="table"):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.sheet_view.rightToLeft = True
    if columns:
        ws.append([str(c) for c in columns])
    for r in rows:
        ws.append([("" if c is None else str(c)) for c in r])
    buf = io.BytesIO()
    wb.save(buf)
    return (buf.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            f"{title}.xlsx")


def table_to_csv(columns, rows, title="table"):
    buf = io.StringIO()
    w = csv.writer(buf)
    if columns:
        w.writerow(columns)
    for r in rows:
        w.writerow(r)
    return ("﻿" + buf.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", f"{title}.csv"


# ---- Plain text -> Word / PDF ----

def text_to_docx(text, title="document"):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()
    for line in str(text).split("\n"):
        p = doc.add_paragraph(line)
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    buf = io.BytesIO()
    doc.save(buf)
    return (buf.getvalue(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            f"{title}.docx")


def text_to_pdf(text, title="document"):
    global _FONT_READY
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    if not _FONT_READY:
        pdfmetrics.registerFont(TTFont("Naskh", ARABIC_FONT))
        _FONT_READY = True
    style = ParagraphStyle("p", fontName="Naskh", fontSize=12, alignment=2, wordWrap="RTL", leading=18)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=title)
    flow = []
    for line in str(text).split("\n"):
        flow.append(Paragraph(_ar(line) if line.strip() else "&nbsp;", style))
    doc.build(flow or [Spacer(1, 12)])
    return buf.getvalue(), "application/pdf", f"{title}.pdf"


# ---- Searchable PDF (image + invisible text layer) ----

def image_to_searchable_pdf(image_bytes, text, title="searchable"):
    global _FONT_READY
    from PIL import Image
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    if not _FONT_READY:
        pdfmetrics.registerFont(TTFont("Naskh", ARABIC_FONT))
        _FONT_READY = True

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size
    png = io.BytesIO()
    img.save(png, format="PNG")
    png.seek(0)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(w, h))
    c.drawImage(ImageReader(png), 0, 0, width=w, height=h)
    to = c.beginText(4, h - 14)
    to.setFont("Naskh", 10)
    to.setTextRenderMode(3)  # invisible but selectable/searchable
    for line in str(text).split("\n"):
        to.textLine(_ar(line))
    c.drawText(to)
    c.showPage()
    c.save()
    return buf.getvalue(), "application/pdf", f"{title}.pdf"
