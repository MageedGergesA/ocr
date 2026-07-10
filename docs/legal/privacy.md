# Privacy Policy — Mostakhles

<!--
DRAFT — not legal advice. Prepared by Mostakhles Operations. Have a local
Egyptian lawyer review before publishing. Fill every [[FOUNDER TO CONFIRM: …]]
placeholder first. Every factual claim below is deliberately grounded in what the
Mostakhles codebase actually does as of this draft — do not add security or
compliance claims that the product cannot back up.
-->

**Effective date:** [[FOUNDER TO CONFIRM: effective date]]
**Last updated:** [[FOUNDER TO CONFIRM: effective date]]

> **Arabic:** نسخة عربية كاملة قيد الإعداد وستُنشر جنبًا إلى جنب مع هذه الصفحة.
> النص الإنجليزي هو المرجع حتى اعتماد الترجمة العربية من مختصّ. الملخص: نحن لا
> ندرّب أي نموذج على مستنداتك، ولا نبيع بياناتك، ولا نحتفظ بالملف الأصلي بعد
> المعالجة افتراضيًا.

---

## 1. Who we are

Mostakhles ("Mostakhles", "we", "us", "our") is an Arabic-first document AI
service that extracts structured data from documents through a web app, a public
REST API, and a free open-source connector for Odoo 19.

- **Legal entity:** [[FOUNDER TO CONFIRM: legal entity name — registration in Egypt in progress; do not publish until confirmed]]
- **Registered address:** [[FOUNDER TO CONFIRM: registered address]]
- **Commercial registration / tax reference:** [[FOUNDER TO CONFIRM: CR no. / tax card no. once issued]]
- **Privacy contact:** [[FOUNDER TO CONFIRM: privacy contact email, e.g. privacy@mostakhles.ai — do not use a personal Gmail in the published text]]
- **Responsible person / data-protection contact:** [[FOUNDER TO CONFIRM: DPO or responsible contact person]]

This policy explains what personal data we handle, why, how long we keep it, who
we share it with, and the choices and rights you have.

## 2. Scope

This policy covers the Mostakhles web app, API, and the Odoo connector. It does
not cover third-party services you reach through links from our site, or the
internal systems of a customer who has installed our Odoo connector inside their
own Odoo instance.

**Controller vs processor.** For your **account and billing data**, Mostakhles is
the data controller. For the **content of documents you send us to process**, you
(or your organisation) are the controller and Mostakhles acts as your processor —
we process that content only to return your result and to run the service. If you
are a business customer, our **Data Processing Addendum (DPA)** governs that
relationship and forms part of your agreement with us.

## 3. Data we collect

**a) Account data.** Email address, hashed password (we never store your password
in readable form), your chosen plan, preferred language, and email-verification
state.

**b) Document content you submit.** The files you upload or send to the API for
processing (images/PDFs), and the structured data extracted from them.

> **How document files are handled — the honest detail.** We do **not** store your
> uploaded source file after processing by default. The file is held in memory only
> long enough to process it and return your result. We **do** save the **extracted
> result** (the structured fields we return) to your account **history** so you can
> review, re-export, and — if you enable it — correct it. You can delete any history
> item, and you can delete your whole account (see *Retention*).
>
> Two deliberate exceptions where a file **is** stored, because you asked us to:
> - **Saved templates.** If you save a reusable template built from one of your own
>   files (Excel/Word/PDF/HTML), we keep that original file so we can fill future
>   results back into the same format. It stays until you delete the template.
> - **Corrections.** If you edit an extracted value, we keep your corrected version
>   alongside the original result in your history.

**c) Corrections from the Odoo connector.** See *Section 8*.

**d) Usage and technical data.** Aggregated request counts and monthly usage
counters per API key (for metering and billing), plus standard server logs and
error diagnostics (e.g. timestamps, error types, performance timing). Error
diagnostics may be processed by our error-monitoring sub-processor (see
*Sub-processors*).

**e) Payment data.** When you subscribe to a paid plan, payment is handled by our
payment providers (Paymob and PayPal; PayTabs is planned). **We never see or store
your full card number, CVV, or bank credentials** — those go directly to the
payment provider. We retain a billing record: which plan, amount, provider,
subscription/transaction reference, and status.

**f) Things you send us directly.** Messages you send through the contact form or
by email (name, email, company, message).

We do **not** knowingly collect data from anyone under 18, and the service is not
directed at children.

## 4. How we use your data and our lawful basis

| Purpose | Data used | Basis (GDPR-style, applied by analogy in MENA) |
|---|---|---|
| Provide the extraction service | Document content, account data | Performance of a contract |
| Bill you and enforce plan limits | Account, usage, billing data | Performance of a contract |
| Send transactional email (verification, receipts, alerts) | Email | Performance of a contract |
| Keep the service secure and prevent abuse | Technical data, IP, bot-check | Legitimate interests |
| Improve extraction accuracy | Corrections you choose to share | Consent / legitimate interests (opt-out — see §8) |
| Respond to your messages | Contact-form data | Legitimate interests |
| Comply with legal and tax obligations | Billing records | Legal obligation |

## 5. What we do NOT do

- We **never** use your documents or extracted data to train any AI model — not
  ours, and we do not permit our AI sub-processor to train on it under our paid
  API terms.
- We **do not** sell, rent, or trade your data.
- We do not use your document content for advertising.

## 6. AI processing and sub-processors

To read your documents, Mostakhles sends the file content to a third-party large
language model for inference. **Our AI sub-processor is Google (Gemini).** Your
document content is transmitted to Google's Gemini API over an encrypted
connection, processed to produce your result, and returned to us. We use Google's
paid API tier; under those terms your content is not used to train Google's models.

We rely on the following categories of sub-processors. The current list is
maintained in Annex III of our DPA; the key ones are:

| Sub-processor | Purpose | Data it may process |
|---|---|---|
| Google (Gemini API) | Document AI inference | Document content you submit |
| Paymob | Payment processing (Egypt/EGP, cards, wallets) | Your payment + billing details (card data goes directly to Paymob) |
| PayPal | Payment processing (international) | Your payment + billing details |
| [[FOUNDER TO CONFIRM: hosting/VPS provider name & region]] | Hosting / infrastructure | All data stored by the service |
| [[FOUNDER TO CONFIRM: transactional email provider / SMTP host]] | Sending account & billing emails | Your email address |
| Sentry | Error monitoring | Technical diagnostics (may incidentally include limited request metadata) |
| Cloudflare (Turnstile) | Bot / abuse protection on forms | IP address and browser signals at the moment of a form submission |

We keep this list current. Before adding or replacing a sub-processor that
processes document content, we will update this policy / the DPA annex; business
customers under the DPA may object as set out there.

## 7. Retention

- **Uploaded source files:** not retained after processing by default (held in
  memory only for the duration of the request).
- **Extraction results in your history:** kept in your account until you delete
  them or delete your account.
- **Saved templates and their source files:** kept until you delete the template.
- **Account, usage, and billing records:** kept while your account is active and
  for as long afterwards as we need to meet tax, accounting, and legal obligations.
- **Server logs and error diagnostics:** kept for a limited operational period,
  then rotated out.

You can delete individual history items at any time from your dashboard. If you
delete your account, we remove the personal data associated with it, except records
we are legally required to retain (e.g. invoices for tax purposes).

> Note: we describe retention by how the product actually behaves. We do **not**
> currently offer a configurable per-account retention window or a contractual
> auto-delete schedule; do not represent that we do.

## 8. The Odoo connector and correction sharing

Our free Odoo 19 connector lets you extract inside Odoo and map fields onto your
Odoo records. It includes an **opt-out feature that shares your corrections back to
Mostakhles to improve future extraction quality**:

- **What is sent:** when you edit an extracted value before applying it, the
  connector may send the *field name*, the *original extracted value*, and your
  *corrected value*, tied to the extraction's identifier. It sends only fields you
  actually changed.
- **Default state:** this is **ON by default** (opt-out).
- **How to turn it off:** in Odoo, go to **Settings → Mostakhles** and disable
  **"Share corrections"** (`mostakhles.share_corrections`). When off, the connector
  sends nothing back.

If your Odoo documents contain personal data, you (as controller) should decide
whether to leave correction-sharing on, and configure the connector accordingly.

## 9. Security

We take reasonable technical and organisational measures to protect your data.
What is true today:

- **Encryption in transit:** traffic between your browser/API client, our service,
  and our AI sub-processor uses TLS (TLS 1.3).
- **Source documents are not stored by default** (see §3, §7).
- **Access control:** API keys can be scoped and revoked; access to stored data is
  limited to what is needed to run and support the service.
- **Passwords** are stored only as salted hashes.

We are an early-stage product and we describe our posture honestly. We do **not**
currently hold SOC 2, ISO 27001, or any formal security certification, and we do
not claim data-residency guarantees, dedicated infrastructure, or a contractual
uptime commitment. No method of transmission or storage is 100% secure.

## 10. International transfers

We are based in Egypt and serve customers across Egypt, KSA, UAE, Kuwait, and
potentially the EU. Processing your documents involves transferring content to our
AI sub-processor (Google), which may process data outside your country. Payment and
infrastructure providers may also process data internationally. Where such
transfers happen, we rely on the providers' own safeguards and contractual terms.
We handle personal data **in line with the principles of** Egypt's Personal Data
Protection Law (Law No. 151 of 2020), the KSA PDPL, applicable UAE data-protection
rules, and — for EU users — the GDPR. We do **not** claim to be certified or
formally "compliant" under any of these regimes.

## 11. Your rights

Subject to applicable law, you can:

- **Access** the personal data we hold about you;
- **Export** your data in a machine-readable form;
- **Correct** inaccurate data;
- **Delete** your data / account;
- **Object to or restrict** certain processing (including turning off
  correction-sharing in the Odoo connector);
- **Withdraw consent** where we relied on it;
- **Complain** to your national data-protection authority.

To exercise any of these, email
[[FOUNDER TO CONFIRM: privacy contact email]]. We will respond within a reasonable
time and in any case within the period required by applicable law.

## 12. Changes to this policy

We may update this policy as the product evolves. We will post the updated version
here and change the "Last updated" date. Material changes affecting document
handling or sub-processors will be highlighted.

## 13. Contact

Privacy questions and data requests:
[[FOUNDER TO CONFIRM: privacy contact email]]
General contact: the contact form at `/contact`, or
[[FOUNDER TO CONFIRM: general/support email, e.g. support@mostakhles.ai]].
