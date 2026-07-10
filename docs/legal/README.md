# Legal pages — integration & publishing notes

Four drafts live in this folder. They are **drafts only** — nothing here is
published, signed, or live. Read the "Before you publish" checklist and get a local
Egyptian lawyer to review the flagged clauses first.

| File | Publishes at (recommended) | Status |
|---|---|---|
| `privacy.md` | `/privacy` | Draft — **replaces** the fabricated claims in the current `privacy.html` |
| `terms.md`   | `/terms`   | Draft — extends the thin `_TERMS_HTML_EN/_AR` currently in `main.py` |
| `cookies.md` | `/cookies` | Draft — new page (no existing route) |
| `dpa.md`     | `/dpa`     | Draft — new page (no existing route) |

## Where the pages should live

There are two front-end surfaces in this project:

1. **The FastAPI backend** (`/home/mageed/doc_ai_saas/backend/app`) already serves
   server-rendered, **bilingual (AR/EN)** pages and **already owns `/privacy` and
   `/terms`** (see `main.py`, `templates/privacy.html`, `templates/legal.html`). It
   is SEO-indexable and language-aware.
2. **The React marketing homepage** (`/home/mageed/Downloads/Premium SaaS Website UI
   Design`, `src/app/pages/Home.tsx`) is a SPA with only two routes: `/` and `/app`
   (`src/app/routes.ts`). Its footer renders the four legal links as dead `#`
   anchors (`Home.tsx` ~line 895: `["Privacy","Terms","Cookie Policy","DPA"]` →
   `href="#"`).

**Recommendation: serve all four legal pages from the FastAPI backend, not as React
routes.** Reasons: legal pages must be bilingual (the backend already does AR/EN via
`legal.html`), must be crawlable/linkable, and change rarely — server-rendered pages
are the right tool. Building four React pages would duplicate the bilingual plumbing
the backend already has, and would leave the backend's own `/privacy` and `/terms`
inconsistent with the SPA.

### Backend wiring (recommended path)

- **`/privacy`** — update the existing `templates/privacy.html` to match
  `privacy.md` (this is not optional — see "Contradictions" below).
- **`/terms`** — replace the short `_TERMS_HTML_EN` / `_TERMS_HTML_AR` strings in
  `main.py` (~lines 427–455) with the fuller content from `terms.md`, rendered
  through the existing `legal.html` template, exactly as the current `/terms` route
  already does.
- **`/cookies`** and **`/dpa`** — add two new routes mirroring the `/terms` pattern:

  ```python
  @app.get("/cookies", response_class=HTMLResponse)
  def cookies_page(request: Request):
      lang = i18n.resolve_lang(request, None)
      title = "Cookie Policy" if lang == "en" else "سياسة ملفات تعريف الارتباط"
      body = _COOKIES_HTML_EN if lang == "en" else _COOKIES_HTML_AR
      return templates.TemplateResponse(request, "legal.html",
                                        _ctx(request, title=title, body=body))

  @app.get("/dpa", response_class=HTMLResponse)
  def dpa_page(request: Request):
      lang = i18n.resolve_lang(request, None)
      title = "Data Processing Addendum" if lang == "en" else "ملحق معالجة البيانات"
      body = _DPA_HTML_EN if lang == "en" else _DPA_HTML_AR
      return templates.TemplateResponse(request, "legal.html",
                                        _ctx(request, title=title, body=body))
  ```

  Convert each markdown body to the simple `<h2>/<p>/<ul>` HTML the `legal.html`
  template expects (same shape as the existing `_TERMS_HTML_*`).
- Add `/cookies` and `/dpa` to the `urls` list in the `sitemap_xml` route so they
  are indexed.
- Also update the backend footer partial `templates/_lpfooter.html` (and
  `privacy.html`'s inline footer, ~lines 167–173) to add **Cookie Policy** and
  **DPA** links alongside Privacy/Terms.

### Wiring the React footer

In `src/app/pages/Home.tsx` (~line 895), the four links are hard-coded with
`href="#"`. Point them at the backend pages with **plain anchors** (a full-page
navigation, because these leave the SPA), not react-router `<Link>`:

```tsx
{[
  ["Privacy", "/privacy"],
  ["Terms", "/terms"],
  ["Cookie Policy", "/cookies"],
  ["DPA", "/dpa"],
].map(([l, href]) => (
  <a key={l} href={href} className="text-xs text-muted-foreground hover:text-foreground transition-colors font-medium">{l}</a>
))}
```

This works cleanly **if the React app and the FastAPI backend are served on the same
origin** (recommended for `mostakhles.ai`). If they are on different origins during
development, use absolute URLs to the backend host. Do **not** use react-router
`<Link>` here — there are no React routes for these pages and you want a real
navigation to the server-rendered page.

> If you would rather keep everything inside the SPA, the alternative is to add four
> React routes in `routes.ts` and render the markdown client-side — but then you must
> re-implement AR/EN and reconcile with the backend's existing `/privacy` and
> `/terms`. Not recommended.

## Contradictions found with existing pages (must fix before publish)

The current `templates/privacy.html` (dated 2026-06-13) contains claims that **the
just-scrubbed homepage explicitly disavows** and that the code does not support.
These must be removed/corrected so the legal pages and the homepage tell the same
honest story:

1. **"MENA data residency" / named data centres (Riyadh, Dubai, Cairo) / "No
   customer data leaves the MENA region."** Not grounded in code; the homepage makes
   no residency claim. Document content is in fact sent to Google (Gemini) for
   inference. **Remove.**
2. **"Encrypted at rest (AES-256)."** Not grounded; the honest posture is "source
   documents are not stored by default." **Remove** the at-rest guarantee.
3. **"Documents stored encrypted; auto-deleted after retention window (default 30
   days)" and the per-plan retention tiers (Free/Lite 30d, Pro 90d, Business
   365d).** This **contradicts "not stored by default"** and describes a
   configurable retention feature the product does not have. **Replace** with the
   accurate model: source files transient; extraction *results* kept in history
   until the user deletes them.
4. **Compliance shield badges "KSA PDPL / UAE PDPL / Egypt PDPL Law 151 /
   GDPR-aligned."** These read as certification/compliance claims; the homepage
   explicitly avoids claiming certification or formal compliance. **Reword** to "we
   handle data in line with the principles of…" or drop the badges.
5. **Google (Gemini) is not disclosed as the AI sub-processor** in the current
   privacy page. The homepage discloses it; the privacy page must too. **Add.**
6. **Sub-processors Sentry, Cloudflare Turnstile, and the Google Fonts third-party
   request** are not disclosed anywhere yet. The drafts here add them. **Add.**

The `terms.md` draft is a superset of the existing `_TERMS_HTML_*` and does not
contradict it — it adds governing law, liability, IP, no-SLA, and the "not an
official Odoo partner" clause.

## Before you publish — placeholder checklist

Fill every one of these (they appear as `[[FOUNDER TO CONFIRM: …]]` in the drafts):

- [ ] **Legal entity name** (Egypt registration in progress — do not invent)
- [ ] **Registered address**
- [ ] **Commercial registration / tax card reference** (once issued)
- [ ] **Governing law** (e.g. Arab Republic of Egypt) — decide after registration
- [ ] **Venue / competent courts** (e.g. Cairo)
- [ ] **Effective date** (same date across all four docs)
- [ ] **Privacy contact email** (e.g. `privacy@mostakhles.ai` — NOT a personal Gmail)
- [ ] **Legal / support contact email** (e.g. `legal@` / `support@mostakhles.ai`)
- [ ] **Security contact email** for breach reports (e.g. `security@mostakhles.ai`)
- [ ] **DPO / responsible contact person** name
- [ ] **Hosting / VPS provider name & region** (Privacy §6, DPA Annex II & III)
- [ ] **Transactional email / SMTP provider** name (sub-processor list)
- [ ] **Gemini processing region** (DPA Annex III) — confirm from Google config
- [ ] **Sentry region / whether self-hosted** (DPA Annex III)
- [ ] **Free-tier liability cap** figure (Terms §13)
- [ ] **DPA signatory name / title** (DPA §13)
- [ ] Decide whether to **self-host Google Fonts** to drop that third-party request
- [ ] Decide whether any **EU customers** need an explicit transfer mechanism (DPA §5)

## Lawyer-review flags (do not ship without local review)

- **Limitation of liability** (Terms §13) and **warranty "as-is" disclaimer**
  (Terms §12): enforceability of caps/disclaimers under the Egyptian Civil Code and
  the final governing law needs a qualified lawyer.
- **DPA liability cross-reference** (DPA §11) — confirm the Terms' cap validly
  extends to the DPA.
- **Special-category (health) data** handling for prescriptions (DPA Annex I) —
  confirm the lawful-basis wording is adequate for the target markets.
- **International transfer mechanism** (DPA §5) if EU users are onboarded.
- **Consumer-protection carve-outs** for the UAE/KSA/Egypt if you sell to consumers
  rather than only businesses.

## Note on bilingual publishing

The drafts are authoritative in **English** with a short Arabic summary line each.
The backend serves AR/EN, so before go-live you should commission a **faithful
Arabic translation** (not a divergent rewrite) of each page and wire it into the
`legal.html` / `privacy.html` bilingual flow. Keep one canonical version — state in
each page which language governs if there is a conflict.
