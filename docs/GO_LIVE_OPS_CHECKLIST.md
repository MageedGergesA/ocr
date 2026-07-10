# Mostakhles — Ops & Legal Go-Live Checklist Set
**Prepared 2026-07-03 · owner: Mageed · burn target <$15/mo · one launch plan @ ~999 EGP/mo**

Format per item: **What → Where → Lead time → Cost → Blocks first revenue? (Y/N)**

> Boundary note: no account was created, no KYC entered, no payment made, no terms accepted.
> Every "apply/submit/sign" step is for Mageed to execute. Where it says "needs a real
> accountant/lawyer," treat that as a hard flag — Egyptian tax registration and VAT posture
> carry real penalties (see §2).

---

## 1. DOMAIN & EMAIL — *fastest unblock, start today*

| # | What → Where | Lead time | Cost | Blocks rev? |
|---|---|---|---|---|
| 1.1 | **Buy `mostakhles.ai`.** `.ai` is premium (~$70–90/yr, no cheap promos). Best value: **Porkbun** (~$72/yr, free WHOIS privacy + SSL) or **Cloudflare Registrar** (at-cost, but move DNS to Cloudflare first; verify they sell `.ai`). Avoid GoDaddy (high renewal). → registrar site | 15 min; live in minutes | **~$72–90/yr** (~$6–7.5/mo amortized, fits budget) | N (customer #1 pays by Instapay) |
| 1.2 | **DNS + TLS via Cloudflare** (free universal SSL) even if registered at Porkbun. → Cloudflare dashboard | 1 hr incl. propagation | $0 | N |
| 1.3 | **Professional mailbox** `info@`/`mageed@mostakhles.ai`. Cheapest: **Zoho Mail** (free tier) or **Porkbun email** (~$24/yr). Avoid Google Workspace at launch. → Zoho signup | 30–60 min | $0 (Zoho free) | N |
| 1.4 | **SPF, DKIM, DMARC** so signup/verification/receipt mail isn't spam-foldered. Three DNS TXT records: SPF (`v=spf1 include:zoho.com ~all`), DKIM (key from mail console), DMARC (`v=DMARC1; p=none; rua=mailto:dmarc@mostakhles.ai` — start `p=none`, tighten later). → Cloudflare DNS + mail console | 30 min + ≤24 hr propagation | $0 | N, but do before sending any transactional mail |
| 1.5 | **Transactional email sender** for signup/verification. Free tiers: **Brevo** (300/day) or **Resend** (3k/mo). Add their SPF/DKIM. → provider signup | 30 min | $0 | N |

*Verify-on-page:* `.ai` price drifts monthly; Zoho free-tier caps change.

---

## 2. EGYPTIAN ENTITY & TAX POSTURE — *the critical-path, longest-lead item*

**Gates real, scalable revenue. Engage a licensed Egyptian accountant here — this cannot be templated.**

| # | What → Where | Lead time | Cost | Blocks rev? |
|---|---|---|---|---|
| 2.1 | **Decide entity form (DECISION).** (a) Sole proprietorship / منشأة فردية — simplest, personal liability, personal income-tax brackets; (b) OPC/LLC — limited liability, GAFI + min-capital paperwork. For pre-revenue solo SaaS, **sole proprietorship is the minimal compliant start**; convert later. → decision then accountant | Decision: now | — | Y (indirectly) |
| 2.2 | **Commercial Registration (السجل التجاري)** at Commercial Registry / GAFI one-stop. Needed for business bank account + Paymob merchant. → GAFI (or online) | **1–3 weeks** | ~1–2k EGP fees + accountant | Y |
| 2.3 | **Tax Card (البطاقة الضريبية) + register with ETA** → gives your Tax Registration Number (TRN) for every invoice. → eta.gov.eg via accountant | **1–3 weeks** after commercial reg | Accountant fee + nominal gov fee | Y |
| 2.4 | **VAT threshold trigger.** Egypt cut the mandatory VAT/e-invoicing registration threshold **500k → EGP 250,000/yr** (Resolution 281/2025). Below 250k you need not register/charge 14% VAT. **Cross EGP 250k gross → must register + join ETA e-invoicing.** At 999 EGP/mo, 250k ≈ **~21 active subscribers.** → monitor monthly | Registration 1–2 wks when triggered | 14% VAT + monthly filing | N at launch; Y past ~21 customers |
| 2.5 | **ETA e-invoicing enrolment** (e-signature/e-seal token). Mandatory for VAT-registered; above-threshold deadline was 31 Mar 2026 (penalties EGP 20k + 1k/day). Defer while sub-threshold; wire Odoo's ETA connector later. → ETA portal + accountant + USB token | 2–4 wks incl. token | Token (hundreds–low-thousands EGP) + accountant | N at launch; Y at VAT registration |
| 2.6 | **Bookkeeping baseline** — keep every Instapay/bank receipt + issued invoice from customer #1; income tax applies to net profit regardless. → accountant | Ongoing | Part of retainer | N |

**Self-serve vs professional:**
- *Self-serve OK:* monitoring the 250k threshold, keeping receipts, invoicing customer #1.
- *MUST use licensed accountant:* entity registration, tax card, VAT decision/timing, ETA enrolment, and whether to fold Mostakhles under the existing consulting tax file. **Get a one-time consult now, even pre-revenue, to choose the entity form correctly.**

*Verify-on-page:* the 250k threshold is recent — have the accountant confirm it's in force for this case.

---

## 3. PAYMENT / MERCHANT ONBOARDING — *sequence strictly by lead time*

**Order: (a) manual bridge TODAY → (b) Paymob in parallel with entity docs → (c) Fawry only if Paymob stalls → (d) PayTabs Phase 2 → (e) PayPal international-only.**

### (a) Manual Instapay / bank-transfer bridge — set up TODAY, zero lead time
| # | What → Where | Lead time | Cost | Blocks rev? |
|---|---|---|---|---|
| 3.1 | **Enable Instapay on your bank app**; note Instapay handle + IBAN. How customer #1 pays 999 EGP with zero gateway KYC. → bank app / InstaPay | Same day | $0 | **The ONLY thing that must work for dollar #1 — Y** |
| 3.2 | **Numbered invoice + receipt flow.** Generate invoice from Odoo → customer pays Instapay → send receipt → flip account active. Keep invoice + confirmation for books. → Odoo / PDF | 1 hr | $0 | Y |
| 3.3 | **In-app "pay by transfer" page** (bilingual): Instapay handle + "email the screenshot, we activate within X hours." Fine for customers 1–10. → web app | 1 hr | $0 | Y |

### (b) Paymob — Egypt primary gateway (cards, wallets, Instapay-in)
| # | What → Where | Lead time | Cost | Blocks rev? |
|---|---|---|---|---|
| 3.4 | **Apply for Paymob merchant.** Typical docs: Commercial Register, Tax Card, owner National ID, business bank account. Review ~**3 business days** after complete docs (real gate is having §2 docs first). → egypt.paymob.com | ~3 business days *after* entity docs | No/low setup + per-txn MDR | N for #1 (bridge covers it); Y for scaling |
| 3.5 | **Enable** cards + wallets + Instapay-in. EGP card billing via Paymob sidesteps the USD-decline problem — right primary rail. → Paymob dashboard | included | MDR per txn | N |

### (c) Fawry — Egypt fallback
| # | What → Where | Lead time | Cost | Blocks rev? |
|---|---|---|---|---|
| 3.6 | Pursue only if Paymob stalls or you want cash/kiosk points. Similar KYC. → fawry.com merchant | days–weeks | per-txn | N — backup, don't run two onboardings at once |

### (d) PayTabs — Gulf (SAR/AED, mada) — **Phase 2, defer**
| # | What → Where | Lead time | Cost | Blocks rev? |
|---|---|---|---|---|
| 3.7 | **Do NOT onboard now** (needs Gulf presence / heavier cross-border setup). Revisit when paying UAE/KSA customers ask for local currency. Code is provider-agnostic — later config, not a rebuild. → paytabs.com (Phase 2) | Weeks | — | N |

### (e) PayPal — international only
| # | What → Where | Lead time | Cost | Blocks rev? |
|---|---|---|---|---|
| 3.8 | Optional "pay in USD" button for diaspora/international only (EG cards decline on USD). Live creds only with a real PayPal business account. → paypal.com business | Days when needed | per-txn | N |

*Verify-on-page:* Paymob's exact doc list + MDR drift. Never collect card data yourself — let the gateway host it.

---

## 4. LEGAL DOCS — *ready-to-use starters (lawyer-review flagged)*

Honest, non-over-promising starters. **A lawyer must review before scaling past the first handful of customers or taking Gulf/EU users** (UAE PDPL, KSA PDPL, EU GDPR). Launch customer #1 on these.

> **Arabic note:** publish an Arabic version alongside English (Arabic-first users). Keep in sync. Recommend: **the Arabic version governs for customers in Egypt.**

### (a) Terms of Service — starter
> **Terms of Service — Mostakhles** · Last updated: [DATE]
> 1. **Service.** Mostakhles ("we") provides Arabic-first document data-extraction software on a subscription basis. By using the Service you agree to these Terms.
> 2. **Subscription & billing.** Offered at [999 EGP/month] via the methods shown at checkout (bank transfer/Instapay, or card where available). Renews monthly until cancelled. Fees non-refundable except where required by law.
> 3. **Your content.** You retain all rights to documents you upload; you grant us a limited licence to process them solely to provide the Service.
> 4. **Acceptable use.** No unlawful content; no use that violates any law or third-party right.
> 5. **AI-generated output.** Results are produced by automated AI and may contain errors. **You are responsible for reviewing output before relying on it.** Not a substitute for professional, legal, or accounting judgment.
> 6. **Availability.** Provided "as is" and "as available"; no guarantee of uninterrupted operation.
> 7. **Liability.** To the maximum permitted by law, total liability is limited to fees paid in the preceding [3] months.
> 8. **No partnership claims.** Mostakhles is independent and **not an official Odoo partner** or affiliated with Odoo S.A.
> 9. **Termination.** Either party may cancel; access ends at the close of the paid period.
> 10. **Governing law.** Laws of the Arab Republic of Egypt. *(Arabic version governs for customers in Egypt.)*
> Contact: info@mostakhles.ai
>
> ⚠️ *Lawyer must review clauses 5, 7, 10 before scaling or onboarding Gulf/EU customers.*

### (b) Privacy Policy — starter
> **Privacy Policy — Mostakhles** · Last updated: [DATE]
> 1. **What we collect.** Account data (name, email, business details), payment reference data (we do **not** store full card numbers — handled by our payment provider), and the **documents you upload**.
> 2. **How we use uploaded documents.** Only to extract the data you request and return results.
> 3. **Third-party AI sub-processor.** Document content is sent to **Google Gemini** to perform extraction, under its own terms; **we do not use your documents to train our own models.**
> 4. **Retention.** Uploaded documents and results retained for **[e.g. 30 days]** then **deleted**. Account/billing records kept while active and as required by Egyptian tax law. *(Set the exact number and honour it technically.)*
> 5. **Sharing.** We do not sell your data; shared only with sub-processors needed to run the Service (AI, payment, email/hosting).
> 6. **Security.** Industry-standard measures (TLS, access controls). **We do not hold SOC 2 or ISO certifications and do not claim them.**
> 7. **Your rights.** Request access/correction/deletion via info@mostakhles.ai.
> 8. **Support.** Arabic and English.
> Contact: info@mostakhles.ai
>
> ⚠️ *Lawyer must review before onboarding UAE/KSA/EU users — cross-border transfer to the AI provider triggers extra disclosure/consent duties. Confirm the retention number matches what the code actually does.*

### (c) One-line data-handling statement (signup + upload screen)
> **EN:** "Documents you upload are processed by a third-party AI provider (Google Gemini) solely to extract your requested data, are stored for [30] days and then deleted, are never used to train our models, and are supported in Arabic and English."
>
> **AR:** «تتم معالجة المستندات التي ترفعها عبر مزود ذكاء اصطناعي خارجي (Google Gemini) لاستخراج البيانات المطلوبة فقط، وتُحفظ لمدة [٣٠] يومًا ثم تُحذف، ولا تُستخدم لتدريب نماذجنا، والدعم متاح بالعربية والإنجليزية.»

Honesty guardrails baked in: no SOC2/ISO claim, no Odoo-partner claim, explicit "AI can be wrong," named sub-processor. Don't add trust badges you can't back.

---

## 5. ODOO APPS STORE LISTING COMPLIANCE — *the free lead-gen module*

| # | What → Where | Lead time | Cost | Blocks rev? |
|---|---|---|---|---|
| 5.1 | **License = LGPL-3** for the free module (standard permissive Odoo free-app license; lets others install/depend freely). **OPL-1 only for paid/proprietary modules.** Your IP is the SaaS backend, not the thin connector. → `"license": "LGPL-3"` in `__manifest__.py` | 5 min | $0 | N |
| 5.2 | **"Not an official Odoo partner" wording.** No "Odoo" in the app *name*, no Odoo logos, no implied endorsement. Safe: "Mostakhles — Arabic Document AI (connector)". Description may factually say "integrates with Odoo" + a line "…is an independent product and is not an official Odoo partner." → manifest + copy | 15 min | $0 | N |
| 5.3 | **Listing metadata:** technical name, version matching supported series (19.0), category, summary, author, license, full description. Support services not required for free apps. → apps.odoo.com/apps/upload | 30 min | $0 | N |
| 5.4 | **Minimal assets:** bilingual keyword title ("Arabic Document AI / استخراج بيانات المستندات"), a main banner screenshot (~560px) + 2–3 feature screenshots (real UI), description with CTA to mostakhles.ai. → prepare PNGs | 2–3 hrs | $0 | N |
| 5.5 | **Submit for review.** Odoo staff review before go-live; SLA unpublished, commonly several days–~2 weeks. Submit early. Questions: apps@odoo.com. → apps.odoo.com upload | several days–2 wks (verify) | $0 | N (marketing channel, not a payment gate) |

*Verify-on-page:* exact listing fields + current review SLA at apps.odoo.com vendor guidelines.

---

## CRITICAL-PATH SUMMARY

**Single longest-lead blocker → the Egyptian entity chain (§2): commercial registration → tax card/TRN → (later) VAT/ETA e-invoicing.** 3–6+ weeks of government + accountant time; everything that *scales* (Paymob KYC, compliant B2B invoicing) waits on it. Cannot be improvised. **Start this week even though dollar #1 doesn't need it.**

**Revenue #1 isn't blocked by that:** the manual Instapay bridge (§3.1–3.3) collects from customer #1 today, zero KYC. Strategy: *earn manually now, build compliant rails in parallel.*

### Start THIS WEEK (longest lead first)
1. **Book a licensed-accountant consult** + begin **commercial registration + tax card** (§2). ← longest lead.
2. **Buy `mostakhles.ai` + DNS/TLS + SPF/DKIM/DMARC + Zoho mailbox** (§1). ← fastest unblock, same-day.
3. **Enable Instapay + manual invoice/receipt + in-app "pay by transfer"** (§3.1–3.3). ← the dollar-#1 unblock.
4. **Prep + submit the Odoo Apps Store listing** (§5). ← review latency, submit early.

*(Paymob application starts the moment the commercial register + tax card exist — a 3-day review, not a bottleneck.)*

---

## FOUNDER DECISION LIST — *only Mageed can decide*

| Decision | Recommendation | Tradeoff |
|---|---|---|
| **Entity: sole prop vs OPC/LLC** | Sole proprietorship now, convert later | Simpler/cheaper/folds into personal tax file — but personal liability + personal-bracket income tax. Confirm with accountant. |
| **Register separately vs under existing consulting tax file** | Fold under existing activity if commercial-reg codes allow "software services" | Folding = less admin, one return; separate = cleaner books if you spin out the SaaS. Accountant-dependent. |
| **First provider after manual bridge: Paymob vs Fawry** | Paymob | EGP card+wallet+Instapay rail solves USD-decline, ~3-day review. Fawry's edge is offline cash — only if SMBs pay cash or Paymob stalls. Don't run both. |
| **Data retention window (must match code)** | 30 days then hard-delete | Longer = convenience but more exposure/storage; shorter = leaner/safer but no re-download. Code must actually delete on schedule — the policy is a promise. |
| **Governing version: Arabic or English** | Arabic governs for Egyptian customers | Matches market/courts; revisit with lawyer if chasing Gulf/international. |
| **When to trigger VAT registration** | Register as you approach EGP 250k/yr (~21 subs), not after | Early = 14% VAT + monthly filing drag; late = EGP 20k + 1k/day penalties. Decide with accountant before ~18 customers. |

---

*Sources: Porkbun .ai pricing · Egypt e-invoicing/VAT 250k threshold (Resolution 281/2025) · ETA official (eta.gov.eg) · Paymob onboarding docs (~3-day review) · Odoo licenses (19.0) · Odoo Apps vendor guidelines. Provider prices, the 250k threshold's in-force status, Paymob's exact doc list, and Odoo's review SLA all drift — verify on each provider's live page. Not legal/accounting advice; §2 and §4 review-flags are real.*
