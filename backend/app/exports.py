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
