# Mostakhles billing roadmap

Decision log + provider comparison for the Mostakhles SaaS billing stack.
Captured 2026-06 to avoid re-litigating the same trade-offs every quarter.

This document answers:
- **Which payment providers ship today** (built + planned)
- **Which providers we evaluated and parked, and why**
- **The triggers for adding the next one** (don't add provider N+1 prematurely)
- **The Egyptian-founder onboarding realities** that constrain our options

---

## TL;DR

**Strategy (revised 2026-06-21):** **PayTabs replaces Paymob** as the MENA acquirer.
PayTabs is a clean superset of Paymob for our needs — same Egyptian payment methods
(Meeza, Vodafone Cash, Fawry, valU), PLUS native subscriptions, PLUS multi-currency
settlement, PLUS Saudi/Gulf coverage (Mada, KNET, STC Pay, Apple Pay), with a
better API and lower fees. No reason to maintain two integrations long-term.

| Phase | Stack | Trigger to advance |
|---|---|---|
| **Phase 1 — TODAY** | Paymob + PayPal (Paymob = bridge, kept until PayTabs is approved + tested) | Default. Ship the launch. |
| **Phase 2 — PayTabs onboarding (parallel)** | Apply to PayTabs now. Build code alongside Paymob. Run both. | Application submitted same day Paymob production go-live ships |
| **Phase 3 — PayTabs live + 30-day soak** | Paymob + PayTabs + PayPal. Both MENA tiles on `/billing/checkout`. | PayTabs has processed real money for 30 days without operational fires |
| **Phase 4 — Deprecate Paymob** | **PayTabs + PayPal only.** Delete Paymob code, env vars, mock. Keep historical `PaymentEvent.provider='paymob'` rows for audit. | Phase 3 trigger fires |
| **Phase 5 — $5K MRR** | + **Paddle** (5% fee, MoR, zero entity setup) | When > 30% of paid customers are non-MENA and we want clean global VAT/tax |
| **Phase 6 — $20K MRR, ≥25% Gulf** | UAE entity (RAK ICC) + **Stripe** (for international polish + lower PayPal-replacement fees) | When Gulf revenue justifies $2.5K/yr entity overhead |

**Why we don't delete Paymob today** (despite the plan being "PayTabs replaces it"):
PayTabs merchant onboarding takes 2-4 weeks of KYC paperwork. If we strip Paymob
out of the codebase today and PayTabs gets stuck on a missing document, we ship
the SaaS launch with **no Egyptian payment processor at all**. Paymob is the
bridge. We delete it only after PayTabs has 30 days of clean production runtime.

**Single most important rule**: don't add provider N+1 until provider N is generating revenue. Every new provider is +1 webhook handler, +1 mock, +1 set of merchant credentials to rotate, +1 cron-renewal branch.

---

## Currently shipped in the codebase

### Paymob (Egyptian acquirer) — ⚠️ TRANSITIONAL, will be deprecated for PayTabs

| | |
|---|---|
| **Code** | `services/paymob.py` (client) + `services/paymob_mock.py` (local mock) |
| **Webhook** | `POST /billing/paymob/callback` with HMAC SHA-512 verification |
| **Checkout** | `POST /billing/paymob/checkout` mints iframe URL |
| **Idempotency** | `UNIQUE(provider='paymob', external_id)` on `PaymentEvent` |
| **Renewal** | Manual via `cron_renewals.py` (Paymob has no native recurring API — we extend `current_period_end` ourselves on each `PAYMENT.SALE.COMPLETED`-equivalent webhook). **This pain is exactly why we're moving to PayTabs.** |
| **Status** | **Code complete. Production merchant credentials not yet active** (currently returns `403 incorrect credentials`). |
| **Deprecation plan** | Keep running through Phase 1-3. Delete in Phase 4 once PayTabs has 30 days of clean production. Historical `PaymentEvent.provider='paymob'` rows stay in DB for audit (no migration needed). |

### PayPal Subscriptions (international fiat)

| | |
|---|---|
| **Code** | `services/paypal.py` (client) + `services/paypal_mock.py` |
| **Endpoints** | `POST /billing/paypal/checkout` · `GET /billing/paypal/return` · `POST /billing/paypal/webhook` |
| **Webhook** | Signature verification via PayPal's `/v1/notifications/verify-webhook-signature` |
| **Events handled** | `BILLING.SUBSCRIPTION.ACTIVATED`, `.CANCELLED`, `.SUSPENDED`, `.EXPIRED`, `PAYMENT.SALE.COMPLETED`, `.PAYMENT.FAILED` |
| **Status** | **Code complete. Plan IDs and live client/secret not yet configured** (`PAYPAL_PLAN_ID_PRO` etc. empty). |

### Renewal cron (provider-agnostic)

| | |
|---|---|
| **Code** | `app/jobs/cron_renewals.py` |
| **What it does** | Sends 7-day reminder emails; downgrades expired-cancelled subs to `free` |
| **Idempotency** | One reminder per (sub, period) via `PaymentEvent` log |
| **Triggers** | Designed to run via systemd timer or `cron.d` daily |

### Cancel / manage subscription

| | |
|---|---|
| **Endpoint** | `POST /billing/cancel` |
| **UI** | `templates/account.html` — Manage Subscription card |
| **Behaviour** | Calls `paypal.cancel_subscription()` for PayPal; marks DB cancelled for both providers; user keeps access until `current_period_end`; cron downgrades on expiry |

---

## Providers evaluated and parked

Comparison rubric:
- **Egypt onboarding direct?** Can an Egyptian-resident founder open a merchant account WITHOUT incorporating elsewhere?
- **Subscriptions native?** Does the API support real auto-renew, or do we hack it with a cron?
- **Multi-currency settlement?** Can a Saudi customer pay SAR and we receive EGP/USD?
- **MENA local payment methods?** Does it support Mada / KNET / Apple Pay / STC Pay / Vodafone Cash / valU / Fawry?

### Comparison table

| Provider | Egypt direct | Subs native | Multi-currency | MENA methods | Fees | Verdict |
|---|---|---|---|---|---|---|
| **Paymob** | ✅ | ❌ (manual) | 🟡 (EGP settlement only in Egypt) | ✅ Egypt-strong (Meeza, Vodafone Cash, valU, Fawry) | 2.75-3.5% | **⚠️ Transitional** — kept until PayTabs lives 30 days, then deleted |
| **PayPal** | ✅ | ✅ | ✅ (USD native) | ❌ | 3.49% + $0.49 | **Phase 1** — shipped |
| **PayTabs** | ✅ (has Egyptian entity since 2017) | ✅ (RecurringBilling endpoint) | ✅ (17 currencies, settle EGP into local bank) | ✅ (Mada/KNET via per-country merchant, Apple Pay, STC Pay, Vodafone Cash, valU, Fawry) | 2.5-2.85% | **🎯 Target** — replaces Paymob entirely |
| **Fawry Pay** | ✅ | ❌ (one-time invoice → cash code) | ❌ (EGP only) | ✅ Cash-pay Egyptians (every kiosk accepts) | ~2.5% + fixed | **Phase 2 candidate** if we sell to clinic/pharmacy ops without cards |
| **Tap Payments** | ✅ (entered Egypt 2024) | ✅ | ✅ | ✅ (KNET strong, Apple Pay, Mada) | 2.5-3% | **Phase 2 alternative** — cleaner API than Paymob, but newer in Egypt |
| **MyFatoorah** | ❌ (requires GCC entity) | 🟡 (newer subscription API) | ✅ (10 currencies) | ✅ (KSA + Kuwait + Bahrain strong) | 2.0-2.75% | **Phase 4** — needs UAE entity |
| **HyperPay** | ❌ (KSA / via partner in Egypt) | ✅ | ✅ | ✅ Mada-strong | 2.5-3% | **Phase 4** — similar to MyFatoorah, no advantage |
| **Paddle** (Merchant of Record) | ✅ (onboards Egyptian devs freely) | ✅ | ✅ (they handle FX) | ❌ (no MENA-local methods) | **5% + $0.50** flat | **Phase 3 candidate** — they handle global VAT/tax for us. Worth the fee at scale. |
| **Lemon Squeezy** (MoR) | ✅ | ✅ | ✅ | ❌ | 5% + $0.50 | **Phase 3 alternative** — Paddle is more battle-tested |
| **Stripe direct** | ❌ (no Egyptian onboarding ever) | ✅ | ✅ | ❌ (in MENA) | 2.9% + $0.30 | **Phase 4** via Stripe Atlas ($500 US LLC) or UAE entity |
| **2Checkout (Verifone)** | ✅ | ✅ | ✅ | ❌ | **5.9%+** | Skip — expensive, no MENA value |
| **USDT crypto** (NOWPayments, etc.) | 🟡 (regulatory grey area in Egypt) | ❌ (one-time only at every provider we found) | ✅ | ❌ | ~0.4-1% | **Skip indefinitely** — Egyptian CBE ban + AML overhead + no real subscription support. Wait for explicit customer demand. |

### Why we ruled out the others

| Out of scope | Reason |
|---|---|
| **Square / Razorpay / Mollie / Adyen / Worldline / Checkout.com direct** | None onboard Egyptian merchants |
| **Direct bank-acquired (NBE Online, CIB SmartWallet)** | Lower fees, but no subscription API, no developer docs, manual onboarding meant for retail not SaaS |
| **2Checkout** | 5.9% baseline + per-tx fees crush margins on $9-$59/mo plans |
| **Gumroad** | 10% flat, design biased toward digital downloads, no enterprise feel |

---

## Egyptian-founder onboarding realities

Things every Egyptian SaaS founder runs into:

| | |
|---|---|
| **What blocks direct onboarding to most international gateways** | Stripe, Adyen, Square, Razorpay don't accept Egyptian merchant applications. Not "slow" — they explicitly don't have a process. |
| **What unlocks them** | Either a **US LLC via Stripe Atlas** (~$500 one-time + ~$200/yr filing) or a **UAE free-zone entity** (RAK ICC, IFZA, Meydan — ~$2.5K setup + $1.5K/yr renewal). Both are 100% foreign-ownable. |
| **Egyptian merchant account paperwork** | Commercial register + tax card + national ID + bank statement + Articles of Association. 2-4 weeks back-and-forth. Sole proprietorships work for Paymob/PayTabs; Fawry sometimes requires LLC. |
| **Settlement currency reality** | Even providers that "accept USD" usually settle EGP into your Egyptian bank account unless you have a USD account (CIB, NBE, HSBC support these). Wise multi-currency works as a workaround but adds friction. |
| **Recurring billing in Egypt** | Most Egyptian acquirers don't support card tokenization for recurring charges. This is why Paymob's "subscriptions" are really cron-driven one-time charges. PayTabs is one of the few exceptions. |

---

## Decision triggers — when to add the next provider

These are the SIGNALS that tell us "now is the time," not arbitrary dates.

### Add **PayTabs** — already decided (will replace Paymob)
**Action this week:** submit the PayTabs Egyptian merchant application. Onboarding
runs in parallel with Paymob's. The application takes 2-4 weeks; we use that time
to finish Paymob production go-live (the bridge) and stage the PayTabs code on
the staging environment.

→ See **[PAYTABS_APPLICATION.md](./PAYTABS_APPLICATION.md)** for the full
pre-application document checklist, suggested form answers tailored to
Mostakhles (MCC code, business description, MENA payment-method selection),
and the parallel sandbox integration workflow that lets us build the code
during the 2-4 week approval wait.

### Delete **Paymob code** when:
- PayTabs has processed real money for ≥30 days without operational fires, AND
- All currently-active Paymob subscriptions have either been migrated to PayTabs OR
  reached their natural expiry (no active sub on the legacy provider)

The DB columns and `PaymentEvent.provider='paymob'` rows stay forever for audit.
What gets deleted: the routes, the client, the mock, the env vars, the renewal-cron branch.

### Add **Fawry Pay** when:
- We have ≥5 prospects without cards (small clinics, pharmacies in rural Egypt), OR
- Vodafone Cash via Paymob is failing at >5% rate for these customers

### Add **Paddle** when:
- ≥30% of monthly paid revenue is from non-MENA customers, AND
- The compliance / VAT registration burden in EU + UK + Australia + US sales tax is consuming >4 hours/month

### Add **MyFatoorah** when:
- Gulf MRR ≥ $5K AND we're committed to a UAE entity for other reasons (Stripe, enterprise sales, Gulf hiring)

### Add **Stripe** (via UAE/US entity) when:
- MRR ≥ $20K AND we want first-class international polish + lower fees than PayPal at scale, AND
- We can absorb the $2.5K/yr UAE entity overhead OR $500 Stripe Atlas + US accounting

### Never add **crypto (USDT)** unless:
- A specific paying customer commits to paying via USDT, AND
- We have a legal opinion on the Egyptian CBE position by then, AND
- The provider supports real subscription billing (most don't)

---

## Architecture notes — making provider N+1 cheap

Every new provider integration mirrors the same pattern that's now battle-tested for Paymob + PayPal:

```
services/<provider>.py             # REST client: auth + create + verify_webhook + cancel
services/<provider>_mock.py        # Local dev mock mounted on ENV=local only
POST /billing/<provider>/checkout  # Mint checkout, redirect user
POST /billing/<provider>/webhook   # Verify signature, idempotent state update
+ tile on templates/checkout.html  # New <form> POST to the new endpoint
+ branch in cron_renewals.py       # Provider-specific renewal extension (or no-op if native)
```

Because `Subscription.provider` and `PaymentEvent.provider` are string columns
with `UNIQUE(provider, external_id)`, **no DB migration is needed** for any
new provider. The renewal cron and cancel endpoint are already provider-aware.

Estimated effort to add provider N+1 given the existing scaffolding: **~3-4 hours**.

---

## Production go-live checklist (Paymob + PayPal — Phase 1)

Before adding any new provider, these have to actually generate revenue:

### Paymob
- [ ] Finish merchant onboarding at paymob.com (commercial register + bank account)
- [ ] Set `PAYMOB_API_KEY` to live key (not sandbox)
- [ ] Set `PAYMOB_HMAC` to live HMAC secret
- [ ] Set `PAYMOB_INTEGRATION_ID` per payment method (one ID per: card, Vodafone Cash, Fawry)
- [ ] Set `PAYMOB_IFRAME_ID` from merchant dashboard
- [ ] Set `PAYMOB_BASE_URL=https://accept.paymob.com` (unset the mock URL)
- [ ] Test a real EGP 1 transaction end-to-end, verify webhook + Subscription row written

### PayPal
- [ ] Create PayPal Business account
- [ ] Generate live REST API credentials (Client ID + Secret)
- [ ] Create Product + 3 Plans in PayPal dashboard (Lite / Pro / Business)
- [ ] Set `PAYPAL_CLIENT_ID`, `PAYPAL_SECRET`, `PAYPAL_PLAN_ID_LITE/PRO/BUSINESS`
- [ ] Set `PAYPAL_BASE_URL=https://api-m.paypal.com` (was sandbox)
- [ ] Set `PAYPAL_MODE=live`
- [ ] Register webhook at `https://yourdomain.com/billing/paypal/webhook` for the 6 event types
- [ ] Save resulting `PAYPAL_WEBHOOK_ID` into env
- [ ] Test a real $9 USD transaction, verify webhook + Subscription row

### Renewal cron
- [ ] Install `cron_renewals.py` as a systemd timer or `cron.d` entry — daily at 06:15 UTC
- [ ] Set `RENEWAL_REMINDER_DAYS` (default 7) and `PUBLIC_URL`
- [ ] Verify `cron done: reminders=N downgrades=M` shows up in logs after first run

---

## Open questions / parked decisions

| | |
|---|---|
| **Annual billing discount mechanics** | Pricing page shows `-17%` on annual toggle, but the checkout flow currently only mints monthly plans. Need a separate `PAYPAL_PLAN_ID_PRO_ANNUAL` and a Paymob `interval=annual` path. **Park until ≥10 paid customers ask for annual.** |
| **VAT / sales tax** | Egypt VAT is 14%; we currently show "VAT included" on the checkout page. For non-Egyptian customers, EU VAT MOSS / UK VAT / US sales-tax-nexus are real compliance burdens — Paddle handles this for us, Stripe Tax for ~0.5% extra. **Park until Phase 3.** |
| **Refunds via UI** | `/billing/cancel` keeps access until period end but doesn't refund. Refunds via Paymob/PayPal dashboards manually. Build a `/billing/refund` UI when we have >3 manual refunds in a month. |
| **Dunning emails** | When a webhook flips a sub to `past_due`, we log it but don't email the user. Build a 3-step dunning email sequence when we have >5 past-due cases. |

---

## Changelog

| Date | Change |
|---|---|
| 2026-06-21 | Initial draft. Captures Paymob+PayPal current state, PayTabs as Phase 2 candidate, decision triggers, Egyptian onboarding realities. |
