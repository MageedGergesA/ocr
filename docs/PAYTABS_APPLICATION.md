# PayTabs — Egyptian merchant application checklist

Pragmatic guide for submitting the Mostakhles merchant application at
**paytabs.com**. Based on standard payment-processor due-diligence patterns
for Egyptian SaaS — verify each field against PayTabs' actual portal at
submission time since UI labels move.

## At a glance

| | |
|---|---|
| **Application URL** | https://paytabs.com/en/egypt → "Get Started" |
| **Time to gather docs** | ~2 hours if you're organized, ~1 day from scratch |
| **Time to submit application** | ~30 minutes once docs are ready |
| **Onboarding duration** | **2-4 weeks** (back-and-forth on compliance questions is normal) |
| **Sandbox access** | Available **immediately after submission** — you can start integrating before approval lands |
| **Cost** | Free signup, no setup fee. Fees are 2.5-2.85% per transaction (negotiable above $10K/mo) |

---

## Phase 1 — Before you apply: gather these documents

Get all of these into one folder before opening the application form. Half the
delays in payment-processor onboarding are "we asked for X three weeks ago,
still waiting" — pre-gathering kills that.

### Required for any Egyptian merchant

- [ ] **Commercial Register (السجل التجاري)** — issued by the Egyptian General Authority for Investment. PDF scan, both sides if multi-page. Must show:
  - Business name (exact match to bank account name)
  - Business activity (must permit "software services" or "online services")
  - Issue date < 6 months old (or recent renewal stamp)
- [ ] **Tax Card (البطاقة الضريبية)** — Egyptian Tax Authority. Must show:
  - Tax registration number
  - Business name (matches commercial register)
  - Active status, not suspended
- [ ] **National ID (الرقم القومي)** of the authorized signatory (the person submitting). Front + back, clear scan.
- [ ] **Bank account statement** — last 3-6 months from your Egyptian business bank account. Same business name as commercial register. PayTabs will settle into this account.
- [ ] **Bank certificate (شهادة بنكية)** — one-page letter from your bank confirming the account is open in the business name, with IBAN. Most CIB / NBE / HSBC branches issue this same-day for ~50 EGP.

### Often requested (have ready, may not need)

- [ ] **Articles of Association (عقد التأسيس)** if you're an LLC. Skip if you're a sole proprietorship.
- [ ] **Authorization letter** if the signer isn't the owner of record. Notarized.
- [ ] **VAT registration certificate** if your annual revenue exceeds 500K EGP.
- [ ] **Recent utility bill** at the business address (proof of physical presence). Less than 3 months old.

### Mostakhles-specific (have ready in case asked)

- [ ] **Domain ownership proof** — screenshot of your mostakhles.ai WHOIS record OR a registrar dashboard screenshot showing your name + domain.
- [ ] **Live website URL** — https://mostakhles.ai with pricing page and terms of service publicly accessible. PayTabs WILL visit your /pricing and /legal pages.
- [ ] **Privacy policy + Terms of Service** — must be at stable URLs (you have `/privacy` and `/legal#terms`). They'll check these.
- [ ] **Refund policy** — must be clearly stated somewhere (FAQ on `/pricing` is enough). PayTabs requires it.

---

## Phase 2 — The application form (likely fields + suggested answers)

These are the typical sections in PayTabs' merchant onboarding. Specific labels
may have moved; treat as a guide.

### Section A — Business information

| Field | What to enter |
|---|---|
| Business legal name | **Exact name on commercial register** (Arabic + English transliteration if applicable) |
| Trade name / brand | `Mostakhles` |
| Commercial register no. | From the register PDF |
| Tax registration no. | From the tax card |
| Business type | `LLC` / `Sole proprietorship` (whichever matches your registration) |
| Year established | From the register issue date |
| Country | Egypt |
| Business address | Your registered address (matches utility bill if requested) |
| Phone | A real Egyptian number you'll answer when PayTabs calls |
| Email | `support@mostakhles.ai` (NOT a personal Gmail — they take this less seriously) |
| Website URL | `https://mostakhles.ai` |
| Anticipated monthly volume | Realistic estimate. **Don't lie low** — say $2,000-5,000 USD/month for an early SaaS. They scale fees based on this. |
| Average transaction size | $59 USD (your Pro plan) |

### Section B — Business activity / Merchant Category Code (MCC)

This is **the single most important field** to get right. The wrong MCC can
get your account suspended later when transactions don't match the code.

| Field | What to enter |
|---|---|
| Business category | `Information technology` / `Software` |
| Sub-category | `Software as a Service (SaaS)` or `Computer software stores` |
| MCC code (if asked) | **`5734`** (Computer Software Stores) OR **`5045`** (Computer Software / Programming Services). 5734 is the standard for SaaS subscriptions. |
| Business activity description | See template below |

**Suggested business description (paste this, tweak as needed):**

> Mostakhles is a software-as-a-service platform that uses AI to extract
> structured data from Arabic business documents — invoices, national IDs,
> prescriptions, contracts, and handwritten records. Customers are
> businesses (clinics, accountants, lawyers, Odoo integrators) across the
> MENA region who subscribe to monthly plans (USD 9 to USD 199) to process
> documents via our web application and REST API. Founded in Egypt, serving
> Egyptian and regional businesses. All transactions are recurring software
> subscriptions billed monthly.

The "all transactions are recurring software subscriptions billed monthly"
sentence is **critical** — it tells PayTabs to enable the `RecurringBilling`
endpoint on your account, which is the whole reason we're picking PayTabs
over Paymob.

### Section C — Settlement bank details

| Field | What to enter |
|---|---|
| Bank name | CIB / NBE / Banque Misr / HSBC Egypt (whichever holds your business account) |
| Account holder name | **Exact match to commercial register name** — they will reject otherwise |
| Account number | From bank certificate |
| IBAN | From bank certificate |
| Currency | EGP (default) — note PayTabs can settle USD into an Egyptian USD account if your bank supports it; ask their sales rep about enabling this AFTER initial approval |

### Section D — Online presence / due diligence

| Field | What to enter |
|---|---|
| Production website | `https://mostakhles.ai` |
| Test / staging URL | Leave blank or use a tunneled localhost during integration |
| Logo upload | Square PNG, 256×256 or 512×512. Use `/static/img/icon.png` from your codebase or the favicon. |
| Product screenshots | 2-3 screenshots showing the pricing page + a real extraction result. Use the ones you have. |
| Refund / cancellation policy URL | `https://mostakhles.ai/legal#refund` (make sure this anchor exists) |
| Privacy policy URL | `https://mostakhles.ai/privacy` |
| Terms of service URL | `https://mostakhles.ai/legal#terms` |

### Section E — Integration / technical contact

| Field | What to enter |
|---|---|
| Integration method | `Custom API integration` (we have services/paytabs.py planned) |
| Technical contact name | Your name |
| Technical contact email | A real email you check daily — they send sandbox creds here |
| Integration URLs (callback / webhook) | Initially leave as `https://mostakhles.ai/billing/paytabs/webhook` even if the route isn't live yet — they only validate the URL is reachable post-integration |
| Languages supported on checkout | English + Arabic |
| Required payment methods at launch | Tick: **Visa, Mastercard, Mada, Meeza, Apple Pay, KNET**. Skip Vodafone Cash + valU for v1 (you can enable them later via the merchant dashboard once approved). |
| Recurring billing? | **YES — critical to tick this.** |

---

## Phase 3 — After submission: what to expect

### Day 1
- **Auto email**: "Your application is received." Sometimes immediate sandbox credentials arrive in this email — if so, start integrating right away (see Phase 4 below).
- If no sandbox creds: reply to the email and ask explicitly for "sandbox merchant ID and server key for parallel integration work." Most reps will issue them within 24-48 hours.

### Days 2-7
- **Compliance officer reaches out** by email or WhatsApp. They'll ask 3-5 questions:
  - "Confirm your business volume estimate" — restate it, don't change
  - "Provide proof of refund policy" — link to your `/pricing#faq` refund answer
  - "Provide proof of address" — utility bill OR Egypt Post address verification letter
  - "Confirm the website is live" — they visit, screenshot, log
  - Possibly: "Provide 3 months of competitive payment processor statements" — only if you've been live elsewhere. If launching fresh, say "first-time merchant, no prior processor history."

- **Respond within 24 hours of each question.** Slow responses are the #1 cause of 4-6-week timelines.

### Days 7-14
- **Risk review.** Internal. They evaluate MCC + volume + website + refund policy. SaaS subscriptions with clear pricing pages pass this 95%+ of the time.

### Days 14-21
- **Approval letter arrives** with live merchant ID, server key, and merchant dashboard credentials.
- **You're cleared to process real transactions** once you swap sandbox creds for live in your env vars.

### If 21 days pass with no movement
- Email your compliance contact directly with the subject line `"Application [reference number] — status check"`.
- If still nothing, escalate to `support@paytabs.com` cc'ing the original contact.
- After 30 days with no response, consider it a soft rejection and reapply with a different bank account (sometimes the bank verification is what's stuck).

---

## Phase 4 — Parallel integration during onboarding

This is the underrated trick: **start building the integration immediately
once sandbox creds arrive** (Day 1-2), don't wait for full approval.

### Workflow

1. **Get sandbox merchant ID + server key** from PayTabs welcome email
2. **Set in `.env`**:
   ```
   PAYTABS_PROFILE_ID=<sandbox profile id>
   PAYTABS_SERVER_KEY=<sandbox server key>
   PAYTABS_BASE_URL=https://secure-egypt.paytabs.com  # or whatever PayTabs assigns
   PAYTABS_REGION=EGY
   ```
3. **Build `services/paytabs.py`** mirroring the PayPal pattern (auth + create + verify_webhook + cancel)
4. **Build `services/paytabs_mock.py`** for local dev so you're not hitting their sandbox on every code change
5. **Build `/billing/paytabs/checkout` + `/billing/paytabs/webhook`**
6. **Add PayTabs tile to `templates/checkout.html`** alongside Paymob + PayPal
7. **Test against sandbox** end-to-end: subscribe a test user → see the iframe → enter test card `4111 1111 1111 1111` → confirm webhook fires → confirm Subscription row written
8. **When live approval arrives**: swap PAYTABS_SERVER_KEY for the live one, swap PAYTABS_BASE_URL if different, done.

The whole code integration is ~3-4 hours of work — about half is spent reading
their docs and the other half copying the PayPal pattern.

---

## Common rejection causes (avoid these)

| Cause | How to avoid |
|---|---|
| **Commercial register doesn't list "software" or "online services" as a permitted activity** | Get an updated register before applying. Cost ~500 EGP, takes 1 week. |
| **Bank account name doesn't EXACTLY match commercial register** | They will reject. Verify before applying. Use the exact Arabic name. |
| **Website doesn't have pricing / refund / privacy at stable URLs** | Make sure `/pricing`, `/privacy`, `/legal#terms`, and a refund clause are all live BEFORE applying. They check. |
| **MCC mismatch** (e.g. you ticked "physical retail" by accident) | Use `5734` or `5045` for SaaS. Re-read Section B above. |
| **Volume estimate seems unrealistic** | Don't say "$50,000/month" if you have 0 customers. Say `$2,000-5,000/month` and grow from there. They can re-rate you later. |
| **No HTTPS on website** | Get a Let's Encrypt cert before applying. Free, 5 minutes. |
| **Sandbox callback URL returns 500** | Even before approval, hit the URL yourself and confirm it returns 200 / proper HTTP — they auto-validate. |

---

## Post-approval checklist (Day 21-ish)

Once you have live credentials in hand:

- [ ] Copy live `PAYTABS_PROFILE_ID` + `PAYTABS_SERVER_KEY` into production `.env`
- [ ] Update `PAYTABS_BASE_URL` if different from sandbox (often it is)
- [ ] Run a test charge of EGP 5 against your own card to verify settlement flow end-to-end
- [ ] Wait 2-3 business days, confirm the EGP 5 lands in your bank account
- [ ] **Switch the PayTabs tile on `/billing/checkout` from grey "Coming soon" → live**
- [ ] Email your first 3 Egyptian customers (if any exist) offering them to switch from Paymob to PayTabs
- [ ] Start the 30-day soak clock for Paymob deprecation (see `BILLING_ROADMAP.md` → Phase 4)

---

## Hand-off to me

When you hit each of these milestones, ping me and I'll do the next step:

| You did | I do next |
|---|---|
| **Got sandbox credentials** | Build `services/paytabs.py` + mock + checkout endpoint + webhook handler + tile on `/billing/checkout` |
| **Got live credentials** | Help you swap env vars + run the test charge + flip the tile from "Coming soon" → live |
| **Hit 30 days of clean PayTabs runtime, zero active Paymob subs** | Delete Paymob code (task #143), update BILLING_ROADMAP.md changelog |

---

## Honest caveats

I'm working from standard payment-processor onboarding patterns and PayTabs'
publicly-documented stance. Specific things I'm guessing at:

- **Exact form labels** (PayTabs may have moved UI since I last looked)
- **Whether MCC 5734 vs 5045 is preferred** for Egyptian SaaS (both work; verify with your rep)
- **Whether their compliance officer uses WhatsApp** (varies; standard email works too)
- **Whether sandbox creds arrive Day 1 or Day 7** (varies; ask explicitly)

If anything in the actual portal differs from what's above, treat the
**Phase 1 documents list and Section B business description as the
load-bearing parts** — those are right regardless of which form field they
sit in. Update this checklist after your actual submission so future-you
(or whoever takes over billing later) has the real flow documented.
