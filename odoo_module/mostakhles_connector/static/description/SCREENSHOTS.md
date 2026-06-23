# Screenshot guide — replace placeholders before Apps Store submission

The 5 PNGs in this directory (`banner.png` + `screenshot_1..4.png`) are
generated placeholder mockups (see `generate_placeholders.py`). They render
respectably on the listing page but each carries a yellow "PLACEHOLDER"
stripe at the bottom — you MUST replace them with real screenshots from a
running Odoo 19 instance before submitting to apps.odoo.com.

## What to capture

| File | Resolution | Subject |
|---|---|---|
| `banner.png` | 1280×720 | Mostakhles logo + tagline. Use the SaaS site's home hero or design something equivalent. Social-share preview. |
| `screenshot_1.png` | 1280×800 | The Extract wizard's **upload step**: form view with the drop-zone, document-type dropdown set to "Auto-detect", a "Choose file" button visible. |
| `screenshot_2.png` | 1280×800 | The Extract wizard's **results step**: 17/17 fields extracted, confidence pills (high/review), 8+ field rows showing supplier name in Arabic, tax ID with ✓ checksum, amounts, dates. |
| `screenshot_3.png` | 1280×800 | The **Settings page** (Settings → Mostakhles): API key field (masked), base URL field, default mode dropdown, current-plan quota bar. |
| `screenshot_4.png` | 1280×800 | The **Field mapping** wizard: two-column list mapping `mostakhles_field → odoo_field` for a Tax Invoice → account.move pairing, 10+ rows visible. |

## How to capture

1. Spin up a fresh Odoo 19 instance (Docker is easiest):
   ```bash
   docker run -p 8069:8069 -v $(pwd):/mnt/extra-addons odoo:19
   ```
2. Install the `mostakhles_connector` module from Apps.
3. Configure a sandbox API key under Settings → Mostakhles.
4. Capture each screenshot using your OS screenshot tool. Crop to the
   browser viewport only — no chrome, no taskbar.
5. Save as PNG at the exact resolutions in the table above.
6. Drop the file into `static/description/` with the matching filename
   (overwrite the placeholder).

## Pre-submission checklist

- [ ] All 5 files are real captures (yellow PLACEHOLDER stripe is gone)
- [ ] No personal data in the screenshots (mask API keys, use test
      partners, redact email addresses)
- [ ] No "Demo" or "Test" labels visible
- [ ] Browser zoom is 100% — UI elements aren't blurry or oversized
- [ ] File sizes under 1 MB each (PNG, optimized — use ImageOptim or
      `pngcrush` if needed)

## After replacement

Delete or `.gitignore` `generate_placeholders.py` if you don't want it
shipped in the published version on Odoo Apps. Apps Store moderators don't
mind it being present, but it's dead code post-submission.
