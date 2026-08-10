# PayTabs Go-Live / Merchant-Onboarding Runbook — Mostakhles

> **Purpose:** Add PayTabs as a payment gateway so Mostakhles can accept **mada (Saudi Arabia)** and **UAE local cards** — the two things Paymob (Egypt) and PayPal do not serve well.
>
> **Who executes this:** Mageed (founder), himself, in his own browser session. This document is a checklist. It does **not** contain credentials and nobody but you should ever type your CR number, IBAN, national ID, card, or API keys.
>
> **Honesty note:** Fees, payout timing, and approval SLAs below are marked **APPROXIMATE — confirm with PayTabs sales**. PayTabs publishes exact numbers only inside your signed merchant agreement / a sales quote. Do not treat any percentage here as a quoted rate. Requirements can change — the authoritative source is always PayTabs' own onboarding pages (linked at the bottom).
>
> **I am not a lawyer or tax advisor.** Points flagged "needs local advice" require a real Saudi/UAE/Egyptian accountant or lawyer — do not rely on this doc for a filing.

---

## TL;DR — the one thing that decides everything

**PayTabs is a per-country acquirer. Your merchant account lives in ONE country, and that country is decided by where you have (a) a legal trade licence/CR and (b) a local bank account in the local currency.**

- **mada (Saudi)** → requires a **Saudi merchant account** → requires a **Saudi CR/trade licence + a Saudi bank account** (mada settles through a Saudi bank; the SNB flow literally requires opening a Saudi commercial bank account). **You cannot get mada on an Egyptian or UAE account.**
- **UAE local cards** → requires a **UAE merchant account** → requires a **UAE trade licence + UAE bank/IBAN**.
- **Egypt** → an Egyptian CR + Egyptian bank account gets you PayTabs **Egypt** (Egyptian Visa/Mastercard/meeza) — **not** mada, **not** UAE domestic acquiring.

**One PayTabs account ≠ both countries.** To serve BOTH KSA mada AND UAE local cards you need **two merchant profiles** (one KSA, one UAE), each with its own in-country entity + bank account, each with its own `profile_id` / `server_key` / regional endpoint. Your DB is already provider-agnostic (`provider` string + `UNIQUE(provider, external_id)`), so two profiles = two provider rows (e.g. `paytabs_sa`, `paytabs_ae`) is clean.

**→ THE LONGEST-LEAD BLOCKER: getting a Gulf legal entity + Gulf bank account.** Everything else (code, website pages, sandbox) can be done this week. The entity+bank is weeks-to-months and is the real critical path. Start it first, in parallel, and keep Paymob/Instapay/PayPal as the bridge so your first paying customer is never gated on this.

---

## PART 1 — Which PayTabs entity/region to register under

### The tradeoffs

| Register under | Gets you | Requires (hard) | Reality for a Cairo solo founder |
|---|---|---|---|
| **PayTabs KSA** (`secure.paytabs.sa`) | **mada**, Saudi Visa/MC, Apple Pay, SADAD | Saudi CR **or** Saudi freelancer certificate (Wathiq/"Freelance" permit), **Saudi bank account**, settles in **SAR** | This is the ONLY way to get mada. Needs Saudi presence. Hard blocker without it. |
| **PayTabs UAE** (`secure.paytabs.com`) | UAE domestic Visa/MC, Apple Pay | UAE trade licence (mainland or free-zone), **UAE bank account/IBAN**, Emirates ID/visa for resident owners, settles in **AED** | Only way to get true UAE domestic acquiring. Needs UAE presence. Hard blocker without it. |
| **PayTabs Egypt** (`secure-egypt.paytabs.com`) | Egyptian cards, meeza | Egyptian CR + tax card + Egyptian bank account (single-owner path exists; freelancer path exists) | Achievable now with your Egyptian setup — but does NOT deliver your Gulf goal. |

### Honest read on "can a foreign / Egyptian entity do it?"

- **No, an Egyptian entity cannot open a KSA-mada or a UAE-domestic PayTabs account.** PayTabs KYC ties the merchant to an **in-country** trade licence and an **in-country bank account matching the settlement currency**. This is an acquiring-network rule, not a PayTabs quirk — mada and UAE domestic schemes settle through local banks.
- **What a foreigner CAN do in KSA without a full company:** Saudi Arabia now issues **Freelancer Certificates** (through the government freelance/self-employment programme), and PayTabs states it accepts them for onboarding. **BUT** — this still requires a **Saudi bank account**, and a non-resident typically cannot open one without an Iqama (residency). So the freelancer route mostly helps Saudi residents, not a Cairo-based founder operating remotely. **Verify eligibility with PayTabs KSA sales and a Saudi accountant before banking on it — this is the make-or-break question for your mada goal.**
- **UAE** similarly: a **free-zone licence** (e.g. a media/tech free zone) is the usual low-friction route for a foreigner to get a UAE trade licence + corporate bank account + residence visa, which then unlocks a UAE PayTabs account. This is a real, common path for MENA SaaS founders — but it costs money and takes weeks, and **UAE corporate bank account opening is itself a known bottleneck** (banks are strict on new single-founder tech companies). Needs local advice / a free-zone formation agent.

### RECOMMENDED PATH (my recommendation — decision is yours)

**Phase it. Do not try to stand up KSA + UAE + Egypt entities at once.**

1. **Pick UAE as your first Gulf entity** (recommendation), because:
   - A UAE **free-zone company** is the most founder-accessible Gulf entity for a non-resident (no local sponsor needed, gives you a residence visa + corporate bank pathway).
   - It gives you AED domestic acquiring for the UAE market immediately.
   - It gives you a credible Gulf HQ for the business generally (invoicing Gulf SMBs, USD receipts, etc.).
2. **Treat KSA-mada as Phase 2**, opened once you have either (a) real Saudi revenue justifying a Saudi entity/branch, or (b) a Saudi resident partner, or (c) confirmation from PayTabs KSA that your UAE entity + a specific cross-border arrangement can acquire mada (ask them explicitly — do not assume). mada is the harder, later prize.
3. **Keep Paymob/Fawry (Egypt) + Instapay/bank transfer + PayPal (international)** live the entire time as the bridge, so no customer waits on any of the above.

> ⚠️ **DECISION NEEDED FROM YOU before Part 1 can proceed:** Are you willing/able to fund a **UAE free-zone company** (setup + first-year cost is real money, and you'd get a residence visa)? Or do you have any **Saudi resident** relationship to make the mada path viable sooner? Tell me which, and I'll turn the chosen path into a dated formation checklist with cost ranges. Until you decide, PayTabs Gulf onboarding is blocked at the entity step — but every "can-start-now" item below can proceed regardless.

---

## PART 2 — KYC / documents PayTabs will ask for

> Source of truth: **PayTabs "KYC, Documents" support article** (linked at bottom). Confirm the live list there before you submit — it changes.

### KSA (for the mada goal)
- [ ] Saudi **CR / trade licence** — OR a Saudi **Freelancer Certificate** — *line of business must match your website* (e.g. "software / IT services"). **HARD BLOCKER without Saudi presence.**
- [ ] **Saudi Civil ID** of owner(s); **passport** if non-resident.
- [ ] **MOA** (Memorandum of Association) — only if multiple owners.
- [ ] **Bank certificate** showing account title + **IBAN** — must be a **Saudi bank account**. **HARD BLOCKER — mada settles to a Saudi bank.**
- [ ] **Tax document** (VAT cert) — "if available".
- [ ] **Website** live with the **trade number displayed**, plus About/Contact/Terms/Privacy/Refund pages.

### UAE (recommended first Gulf entity)
- [ ] UAE **trade licence** (mainland or free-zone) — line of business must match website. **HARD BLOCKER without a UAE licence.**
- [ ] **Emirates ID** + **passport copy** + **visa copy** for owner(s). (Foreigner → needs residence visa, which the free-zone company provides.)
- [ ] **MOA** — if multiple owners.
- [ ] **Bank certificate** with account title + **IBAN** — **UAE bank account**. **HARD BLOCKER — UAE domestic settles to a UAE bank.**
- [ ] **Merchant Application Form** (PayTabs form).
- [ ] Tax document (VAT) — if available.
- [ ] Live website with About/Contact/Terms/Privacy pages, company name prominent.

### Egypt (only if you also want Egyptian PayTabs acquiring)
- [ ] Single-owner path: **commercial registration + tax card + owner ID/passport + bank account proof**.
- [ ] Freelancer path: **national ID + bank account statements** (lighter).
- Note: gets Egyptian cards/meeza, **not** your Gulf goal.

### Hard-blocker summary for a solo founder with no Gulf entity yet
- ❌ Saudi bank account (blocks mada) — cannot open remotely without Iqama.
- ❌ UAE trade licence + UAE IBAN (blocks UAE cards) — solvable via free-zone formation, weeks + cost.
- ❌ In-country CR/licence with LOB matching your website.
- ✅ Everything **website-side** (Terms, Privacy, Refund, pricing, About, Contact) — you can build these now and they're required anyway.

---

## PART 3 — The exact credentials the integration code needs

PayTabs (PT2 API) needs **three** things per merchant profile:

| Credential | What it is | Where in the dashboard |
|---|---|---|
| **`profile_id`** | Numeric ID of your merchant profile | Merchant dashboard → your account/profile info (PayTabs' "How to get your account information from PT2 Dashboard" article). Sent in the **request payload**. |
| **`server_key`** (a.k.a. Server Key / secret key) | Secret used in the HTTP **Authorization header** to authenticate API calls | Dashboard → Developers / API Keys section. **Secret — treat like a password.** |
| **Regional API base URL** | The country-specific endpoint your account belongs to | Decided by your account's region (see table). Wrong region = auth failure even with correct keys. |

### Regional API base URLs (confirmed from PayTabs docs)

Rule of thumb PayTabs gives: take your **dashboard** domain and swap `merchant` → `secure`.

| Region | Base endpoint (payment request) |
|---|---|
| **KSA** | `https://secure.paytabs.sa/payment/request` |
| **UAE** (also the default/global `.com`) | `https://secure.paytabs.com/payment/request` |
| **Egypt** | `https://secure-egypt.paytabs.com/payment/request` |
| Oman | `https://secure-oman.paytabs.com/payment/request` |
| Jordan | `https://secure-jordan.paytabs.com/payment/request` |
| Kuwait | `https://secure-kuwait.paytabs.com/payment/request` |
| Global | `https://secure-global.paytabs.com/payment/request` |

> If you run BOTH a KSA and a UAE profile, they use **different base URLs AND different keys**. Store them per-provider (`paytabs_sa` → `.sa` + KSA keys; `paytabs_ae` → `.com` + UAE keys). Never mix a KSA key against the `.com` endpoint.

### Callback / return / IPN URLs to register

When you create a payment (Hosted Payment Page = "PayPage"), you pass two URLs, and you configure a server-to-server IPN:

- **`return`** — the browser is redirected here after the customer finishes paying (your `/app` success/failure landing). User-facing only; **never trust it for fulfilment**.
- **`callback`** (IPN / server-to-server) — PayTabs POSTs the authoritative transaction result to this URL. **This is what you flip the subscription to "active" on.** Must be a public HTTPS URL on `mostakhles.ai` (e.g. `https://api.mostakhles.ai/webhooks/paytabs`).
- Register/whitelist these in the dashboard's transaction/IPN settings **and** pass them in the create-payment payload.

### IPN signature verification

- PayTabs signs the IPN callback so you can prove it really came from PayTabs (not a spoofer hitting your webhook). Verification uses a **signature/HMAC computed with your `server_key`** over the posted fields.
- **Your code must:** recompute the signature from the received payload using the `server_key` and compare it to the `signature` header/field; **reject if it doesn't match**; and additionally **re-query the transaction** via PayTabs' verify/query API before granting access (defence in depth). Then upsert into your payments table keyed on `UNIQUE(provider, external_id)` — idempotent, so a duplicate IPN can't double-provision.
- Confirm the exact fields and hashing method against PayTabs' current IPN/"Transaction feedback" doc — do not hardcode from memory.

### Test/sandbox vs live

- PayTabs issues **separate sandbox (demo) credentials** from live. Sandbox `profile_id` + `server_key` are different values; some regions use a demo dashboard. **Your integration should read all three (profile_id, server_key, base_url) from environment/config per environment** — never hardcode, never commit. You already keep secrets in env; keep KSA/UAE/sandbox sets separate.

---

## PART 4 — Sandbox → live sequence

- [ ] **1. Get sandbox credentials** from PayTabs (demo profile). No entity needed to *explore* the API docs, but a real sandbox profile is issued as part of onboarding.
- [ ] **2. Integrate against sandbox.** Implement create-payment (Hosted PayPage) + IPN handler + signature verification + transaction verify-query. Store results idempotently.
- [ ] **3. Run test cards**, including a **mada test card** (PayTabs provides test PANs in its testing/sandbox doc — use theirs, do not invent card numbers). Test: success, decline, 3-D Secure challenge, and a **refund**.
- [ ] **4. Verify the IPN** actually fires to your public HTTPS callback and that a tampered payload is rejected.
- [ ] **5. Submit KYC + website for review** (Part 2). PayTabs reviews: your documents, that your **website LOB matches your licence**, that pricing + refund + terms + contact pages are live, and (KSA) that the trade number shows on the site.
- [ ] **6. PayTabs flips you live** and issues **live** `profile_id` + `server_key`. Swap env to live keys + live base URL.
- [ ] **7. Do one real low-value live transaction** end-to-end, then refund it, before announcing Gulf payments.

### Approval time, settlement, fees — **APPROXIMATE, confirm with PayTabs sales**

- **Approval SLA:** *Approximate* — often a few business days to a couple of weeks once **all** KYC is clean; incomplete docs or LOB mismatch is the usual delay. **Not a committed figure — ask PayTabs.**
- **Settlement currency:** you settle in the **account's local currency** — **SAR** for a KSA account, **AED** for a UAE account. You do **not** settle mada into a foreign account.
- **Payout schedule:** *Approximate* — commonly a rolling cycle (e.g. T+ a few business days, sometimes weekly for new merchants until history builds). **Confirm exact cycle and any rolling reserve with PayTabs — new/high-risk merchants sometimes get a reserve held.**
- **Fees:** *Approximate ranges only, NOT a quote* — Gulf card MDR typically lands in the low-single-digit-percent-per-transaction area, often with a small fixed per-transaction component, and mada is usually cheaper than international cards; there may be a setup and/or monthly/annual fee. **Get the actual schedule in writing from PayTabs sales — do not use any number here for pricing or margin math.**

---

## PART 5 — Compliance gotchas

- **PCI DSS — use the Hosted PayPage.** With PayTabs' **Hosted Payment Page** the card data is entered on PayTabs' domain, so you qualify for **SAQ-A** (the lightest self-assessment) — you never touch/store PAN. **Recommendation: use Hosted PayPage, not the direct/managed-form API,** to keep your PCI scope minimal. (You still complete an SAQ-A attestation; a full audit is not required at your scale — needs confirmation with your acquirer, but SAQ-A is the standard hosted-page posture.)
- **Refund policy page is mandatory.** PayTabs (and the card schemes) require a **clear refund/cancellation policy** page and clear **pricing** on the live site before approval. You're a monthly SaaS — state your refund stance plainly (e.g. pro-ration / no-refund-after-use / X-day policy). I can draft this to match your Terms. **This is a can-start-now item and it's on the KYC critical path — do it early.**
- **Currency: USD pricing vs SAR/AED settlement.**
  - **mada is a domestic Saudi scheme and is SAR-centric.** Charging a mada card in USD is a poor fit and can be declined or penalised. **Recommendation: price the Gulf checkout in local currency** — show SAR for mada/KSA, AED for UAE — even though your headline tiers are quoted in USD ($9/$29/$59/$199). Convert the USD tier to a fixed SAR/AED price (e.g. set a local price, not a live FX rate, to avoid rounding churn). **Needs a pricing decision from you** (I can propose SAR/AED equivalents that stay clean, e.g. rounded).
  - This also interacts with local VAT (KSA 15% VAT / UAE 5% VAT) on B2B SaaS sold to Gulf customers — **needs local accountant advice**; don't wing tax on Gulf invoices.
- **3-D Secure / SCA.** Gulf card payments (mada especially) run **3-D Secure**; expect a challenge step (OTP/bank app). Your integration must handle the 3DS redirect/callback and the "pending → authorised" state. Hosted PayPage handles the 3DS flow for you — another reason to use it.
- **No overclaiming.** Keep your Terms/Privacy honest per house rule: documents are processed by a third-party LLM, state retention, Arabic + English. **Do not claim PCI Level 1 / SOC2 / ISO** — you hold none. "Card payments are processed by PayTabs; we do not store card data" is the accurate, sufficient statement.

---

## PART 6 — What YOU must do vs what's already coded, + blockers

### Already handled on the code side (provider-agnostic architecture)
- DB is `provider` (string) + `UNIQUE(provider, external_id)` → PayTabs slots in as `paytabs_sa` / `paytabs_ae` with **zero schema change**.
- Idempotent upsert on `(provider, external_id)` → duplicate IPNs are safe.
- (To build, but it's *code*, not paperwork — not your job on this runbook): the create-payment call, the IPN handler with signature verify + transaction re-query, and the SAR/AED price mapping. This can be done in **sandbox now**, before any entity exists.

### What ONLY you (the founder) can do — nobody does this for you
- [ ] Decide the Gulf entity path (UAE free-zone vs Saudi presence) — **the gating decision**.
- [ ] Form the entity / get the trade licence (or freelancer cert).
- [ ] Open the **in-country bank account** (SAR for KSA, AED for UAE).
- [ ] Create the PayTabs merchant account **in your own session**, enter your own CR/ID/IBAN, e-sign the merchant agreement.
- [ ] Retrieve `profile_id` + `server_key` from the dashboard and put them in your server env **yourself** — never paste them to me or anyone.
- [ ] Publish the live website pages (Terms, Privacy, Refund, Pricing, About, Contact) on `mostakhles.ai`.
- [ ] Sign off the real live test transaction.

### HARD BLOCKERS (cannot proceed without these)
1. **Saudi bank account** → blocks mada. No remote workaround without Saudi residency/entity. *(Longest lead for the mada goal specifically.)*
2. **UAE trade licence + UAE IBAN** → blocks UAE cards. Solvable via free-zone formation — **cost + weeks**, and UAE corporate bank opening is itself slow.
3. **In-country CR/licence whose line-of-business matches the website.**

### CAN-START-NOW (do these this week, in parallel — none need a Gulf entity)
- [ ] Draft + publish **Terms, Privacy, Refund/Cancellation, Pricing, About, Contact** pages (needed for KYC anyway; I can draft all of these).
- [ ] Decide **SAR/AED local pricing** for the Gulf checkout (I can propose clean numbers).
- [ ] Build + test the PayTabs integration in **sandbox** (code side) incl. mada test card.
- [ ] Register the **callback/return URLs** structure on `mostakhles.ai` DNS/nginx.
- [ ] Start the **UAE free-zone / Saudi-presence research** with a formation agent + a MENA accountant (long lead — start it first).
- [ ] Keep **Paymob + Instapay/bank transfer + PayPal** as the live bridge so customer #1 never waits on any of this.

---

## Official sources (verify against these — they supersede this doc)
- PayTabs — **What is my Region / endpoint URL?** — https://support.paytabs.com/en/support/solutions/articles/60000718070-what-is-my-region-endpoint-url-
- PayTabs — **KYC, Documents required to activate my account** — https://support.paytabs.com/en/support/solutions/articles/60000716510-what-kyc-documents-are-required-to-activate-my-paytabs-account-
- PayTabs — **Merchant's Onboarding Journey** — https://support.paytabs.com/en/support/solutions/articles/60000716345-merchant-s-onboarding-journey
- PayTabs — **mada Activation with SNB (KSA only)** — https://support.paytabs.com/en/support/solutions/articles/60000816586-mada-activation-with-snb-saudi-national-bank-
- PayTabs — **Freelancer Certificate/Permit accepted** — https://ai.paytabs.com/en/freelancer-certificate-permit-accepted-get-started-with-paytabs/
- PayTabs — **PT2 API Endpoints (Hosted Payment Page + IPN)** — https://docs.paytabs.com/ and https://support.paytabs.com/en/support/solutions/articles/60000709775-the-pt2-api-endpoints-integration-manual
- PayTabs — **ZATCA activation & guidelines (KSA only)** — https://support.paytabs.com/en/support/solutions/articles/60001568956-zatca-2-activation-and-guidelines-ksa-only-

*Fees, payout timing, and approval SLAs in this doc are approximate and must be confirmed in writing with PayTabs sales. Entity/tax/bank steps need a local (Saudi/UAE/Egyptian) accountant or lawyer — this runbook is founder guidance, not legal or tax advice.*
