# Copyright 2026 Mageed Gerges <mageed.gerges28@gmail.com>
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)
"""Generate branded placeholder PNGs for the Odoo Apps Store submission.

Run once to seed banner.png + screenshot_1..4.png with respectable-looking
mockups. Before final submission, REPLACE these with real screenshots from
a running Odoo 19 instance — see SCREENSHOTS.md for what to capture.

Usage:
    cd .../mostakhles_connector/static/description/
    python generate_placeholders.py
"""
from __future__ import annotations

import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

# Brand palette — matches the SaaS site
INK = (15, 23, 42)          # slate-900
MINT = (15, 118, 110)       # brand teal
MINT_LIGHT = (94, 234, 212) # teal-300
CARD = (255, 255, 255)
PAGE = (250, 251, 252)
LINE = (226, 232, 240)      # slate-200
MUTED = (100, 116, 139)     # slate-500


def _font(size: int, bold: bool = False):
    """Try several common system font paths; fall back to default bitmap."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _watermark(draw, w, h):
    """Tiny 'PLACEHOLDER — replace before submission' stripe in the corner."""
    f = _font(14)
    text = "PLACEHOLDER — replace with real screenshot before Apps Store submission"
    draw.rectangle((0, h - 28, w, h), fill=(255, 251, 235))
    draw.text((16, h - 22), text, font=f, fill=(180, 83, 9))


# -- 1. Banner (1280x720, social-share preview) --------------------------

def banner():
    w, h = 1280, 720
    img = Image.new("RGB", (w, h), MINT)
    d = ImageDraw.Draw(img)

    # Background gradient feel — diagonal lighter band
    for y in range(h):
        shade = int(15 + 40 * (y / h))
        d.line((0, y, w, y), fill=(15, 118 - shade // 6, 110 - shade // 4))

    # Big M logo block
    d.rounded_rectangle((80, 140, 280, 340), radius=24, fill=(255, 255, 255))
    f_logo = _font(140, bold=True)
    d.text((132, 158), "M", font=f_logo, fill=MINT)

    f_title = _font(76, bold=True)
    f_sub = _font(34)
    d.text((340, 200), "Mostakhles", font=f_title, fill=(255, 255, 255))
    d.text((342, 296), "Arabic Document AI for Odoo", font=f_sub, fill=(209, 250, 229))

    f_strap = _font(28)
    d.multiline_text(
        (80, 480),
        "Invoices · National IDs · Prescriptions · Contracts · Handwriting\n"
        "Bilingual EN/AR · Cognitive extraction · Auto field-mapping",
        font=f_strap, fill=(209, 250, 229), spacing=14)

    _watermark(d, w, h)
    img.save(os.path.join(HERE, "banner.png"), optimize=True)


# -- Generic Odoo-like form chrome for screenshots -----------------------

def _form_chrome(d, w, h, title: str, breadcrumb: str):
    # Top app bar (Odoo plum)
    d.rectangle((0, 0, w, 56), fill=(113, 75, 103))
    f = _font(22, bold=True)
    d.text((24, 14), "odoo", font=f, fill=(255, 255, 255))
    f2 = _font(16)
    d.text((110, 18), breadcrumb, font=f2, fill=(220, 200, 215))
    # Page surface
    d.rectangle((0, 56, w, h), fill=PAGE)
    # Card surface
    d.rounded_rectangle((24, 80, w - 24, h - 24), radius=10,
                        outline=LINE, width=1, fill=CARD)
    # Card title
    f_title = _font(26, bold=True)
    d.text((48, 100), title, font=f_title, fill=INK)


def _row(d, x, y, w, label, value, conf=None):
    f_label = _font(13, bold=True)
    f_value = _font(16)
    d.text((x, y), label.upper(), font=f_label, fill=MUTED)
    d.text((x, y + 20), value, font=f_value, fill=INK)
    if conf is not None:
        f_conf = _font(12, bold=True)
        col = MINT if conf >= 90 else (180, 83, 9)
        d.rounded_rectangle((x + w - 80, y + 22, x + w - 16, y + 46),
                            radius=10,
                            fill=(15, 118, 110, 30) if conf >= 90
                            else (245, 158, 11, 30))
        d.text((x + w - 70, y + 26), f"{conf}%", font=f_conf, fill=col)
    d.line((x, y + 56, x + w - 16, y + 56), fill=LINE, width=1)


# -- 2. Extract wizard, doc picker step ----------------------------------

def screenshot_1():
    w, h = 1280, 800
    img = Image.new("RGB", (w, h), PAGE)
    d = ImageDraw.Draw(img)
    _form_chrome(d, w, h, "Extract with Mostakhles", "Invoicing › Vendor Bills › Extract")

    # Big drop zone
    d.rounded_rectangle((96, 200, w - 96, 560), radius=14,
                        outline=(15, 118, 110), width=2,
                        fill=(240, 253, 250))
    f = _font(48, bold=True)
    d.text((w // 2 - 240, 280), "Drop a document here", font=f, fill=MINT)
    f2 = _font(22)
    d.text((w // 2 - 280, 360), "PDF · JPG · PNG · up to 20 MB", font=f2, fill=MUTED)
    # Button
    d.rounded_rectangle((w // 2 - 110, 430, w // 2 + 110, 490),
                        radius=10, fill=MINT)
    f3 = _font(20, bold=True)
    d.text((w // 2 - 80, 446), "Choose a file", font=f3, fill=(255, 255, 255))

    # Doctype dropdown row
    f4 = _font(15, bold=True)
    d.text((96, 600), "DOCUMENT TYPE", font=f4, fill=MUTED)
    d.rounded_rectangle((96, 624, 600, 668), radius=8,
                        outline=LINE, width=1, fill=CARD)
    f5 = _font(16)
    d.text((112, 636), "Auto-detect", font=f5, fill=INK)
    d.text((570, 636), "▾", font=f5, fill=MUTED)

    _watermark(d, w, h)
    img.save(os.path.join(HERE, "screenshot_1.png"), optimize=True)


# -- 3. Extract wizard, results step -------------------------------------

def screenshot_2():
    w, h = 1280, 800
    img = Image.new("RGB", (w, h), PAGE)
    d = ImageDraw.Draw(img)
    _form_chrome(d, w, h, "Extraction Results — INV-2026-0042", "Invoicing › Vendor Bills")

    # Confidence summary banner
    d.rounded_rectangle((48, 148, w - 48, 200), radius=10,
                        outline=(15, 118, 110), width=1,
                        fill=(240, 253, 250))
    f = _font(16, bold=True)
    d.text((68, 165), "Extracted 17 / 17 fields", font=f, fill=INK)
    f2 = _font(13, bold=True)
    d.rounded_rectangle((290, 162, 380, 188), radius=12,
                        fill=(16, 185, 129, 50))
    d.text((298, 168), "15 HIGH", font=f2, fill=(4, 120, 87))
    d.rounded_rectangle((392, 162, 482, 188), radius=12,
                        fill=(245, 158, 11, 50))
    d.text((400, 168), "2 REVIEW", font=f2, fill=(180, 83, 9))

    # Fields list
    rows = [
        ("Supplier (AR)", "شركة الألمنيوم المصرية", 98),
        ("Supplier (EN)", "Egyptian Aluminum Co.", 96),
        ("Tax ID", "219-487-303  ✓ checksum valid", 99),
        ("Invoice No.", "INV-2026-0042", 99),
        ("Issue Date", "2026-06-14", 100),
        ("Line Items", "3 rows · subtotal reconciles", 97),
        ("Subtotal", "EGP 23,300", 81),
        ("Total", "EGP 26,600", 99),
    ]
    y = 232
    for label, value, conf in rows:
        _row(d, 64, y, w - 128, label, value, conf)
        y += 64

    _watermark(d, w, h)
    img.save(os.path.join(HERE, "screenshot_2.png"), optimize=True)


# -- 4. Settings page ----------------------------------------------------

def screenshot_3():
    w, h = 1280, 800
    img = Image.new("RGB", (w, h), PAGE)
    d = ImageDraw.Draw(img)
    _form_chrome(d, w, h, "Mostakhles", "Settings › Mostakhles")

    f = _font(15, bold=True)
    f2 = _font(16)

    # API key row
    d.text((64, 168), "API KEY", font=f, fill=MUTED)
    d.rounded_rectangle((64, 196, w - 64, 250), radius=8,
                        outline=LINE, width=1, fill=CARD)
    d.text((80, 212), "mst_live_•••••••••••••••••••••••••••••••",
           font=f2, fill=INK)

    # Base URL
    d.text((64, 290), "API BASE URL (advanced)", font=f, fill=MUTED)
    d.rounded_rectangle((64, 318, w - 64, 372), radius=8,
                        outline=LINE, width=1, fill=CARD)
    d.text((80, 334), "https://api.mostakhles.ai", font=f2, fill=INK)

    # Default mode
    d.text((64, 412), "DEFAULT EXTRACTION MODE", font=f, fill=MUTED)
    d.rounded_rectangle((64, 440, 360, 494), radius=8,
                        outline=LINE, width=1, fill=CARD)
    d.text((80, 456), "Precise (Arabic + handwriting)", font=f2, fill=INK)
    d.text((330, 456), "▾", font=f2, fill=MUTED)

    # Quota / status panel
    d.rounded_rectangle((64, 550, w - 64, 680), radius=10,
                        outline=(15, 118, 110), width=1,
                        fill=(240, 253, 250))
    f3 = _font(18, bold=True)
    d.text((84, 572), "Account on Pro plan — 8,500 credits / month",
           font=f3, fill=INK)
    f4 = _font(15)
    d.text((84, 612), "Used this period:  2,847 / 8,500  (33%)",
           font=f4, fill=(15, 118, 110))
    # Progress bar
    d.rounded_rectangle((84, 645, w - 84, 660), radius=8, fill=LINE)
    bar_w = int((w - 168) * 0.33)
    d.rounded_rectangle((84, 645, 84 + bar_w, 660), radius=8, fill=MINT)

    _watermark(d, w, h)
    img.save(os.path.join(HERE, "screenshot_3.png"), optimize=True)


# -- 5. Field mapping ----------------------------------------------------

def screenshot_4():
    w, h = 1280, 800
    img = Image.new("RGB", (w, h), PAGE)
    d = ImageDraw.Draw(img)
    _form_chrome(d, w, h, "Field Mapping — Tax Invoice → account.move",
                 "Settings › Mostakhles › Field mappings")

    f = _font(14, bold=True)
    f2 = _font(15)

    # Two-column header
    d.text((64, 168), "MOSTAKHLES FIELD", font=f, fill=MUTED)
    d.text((660, 168), "ODOO FIELD", font=f, fill=MUTED)
    d.line((64, 192, w - 64, 192), fill=LINE, width=1)

    rows = [
        ("supplier_ar", "partner_id.name_ar"),
        ("supplier_en", "partner_id.name"),
        ("tax_id", "partner_id.vat"),
        ("invoice_no", "ref"),
        ("issue_date", "invoice_date"),
        ("currency", "currency_id"),
        ("subtotal", "amount_untaxed"),
        ("total", "amount_total"),
        ("line_items[*].desc_ar", "invoice_line_ids.name"),
        ("line_items[*].qty", "invoice_line_ids.quantity"),
        ("line_items[*].price", "invoice_line_ids.price_unit"),
    ]
    y = 208
    for src, dest in rows:
        d.text((80, y), src, font=f2, fill=INK)
        # Arrow
        d.text((520, y), "→", font=f2, fill=MINT)
        d.text((676, y), dest, font=f2, fill=INK)
        d.line((64, y + 32, w - 64, y + 32), fill=LINE, width=1)
        y += 44

    _watermark(d, w, h)
    img.save(os.path.join(HERE, "screenshot_4.png"), optimize=True)


def main():
    print("Generating banner.png + screenshot_1..4.png …")
    banner()
    screenshot_1()
    screenshot_2()
    screenshot_3()
    screenshot_4()
    print("Done. Replace with real Odoo screenshots before Apps Store submission.")


if __name__ == "__main__":
    main()
