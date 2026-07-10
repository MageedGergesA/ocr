# Data Processing Addendum (DPA) — Mostakhles

<!--
DRAFT — not legal advice. This is a standard controller↔processor addendum for
business customers (customer = controller, Mostakhles = processor). Have it
reviewed by a qualified lawyer before offering it for signature, especially the
liability cross-reference, the international-transfer mechanism, and how it maps to
Egypt Law 151/2020 executive regulations once those are fully in force. Fill every
[[FOUNDER TO CONFIRM: …]] placeholder.
-->

**Effective date:** [[FOUNDER TO CONFIRM: effective date]]
**Version:** 1.0 (draft)

> **Arabic:** نسخة عربية كاملة قيد الإعداد. النص الإنجليزي هو المرجع.

This Data Processing Addendum ("DPA") forms part of the agreement between the
customer ("**Customer**", acting as data **controller**) and
[[FOUNDER TO CONFIRM: legal entity name]] ("**Mostakhles**", acting as data
**processor**) for the customer's use of the Mostakhles service (the "Service"). It
applies where Mostakhles processes personal data on the Customer's behalf. If there
is a conflict between this DPA and the Terms of Service on data-protection matters,
this DPA prevails.

## 1. Definitions

Terms such as "personal data", "processing", "controller", "processor", "data
subject", and "personal data breach" have the meanings given in applicable data
protection law — including Egypt's Personal Data Protection Law No. 151 of 2020,
the KSA PDPL, applicable UAE rules, and, for EU data subjects, the GDPR ("Data
Protection Laws"). "Customer Personal Data" means personal data contained in
documents and data the Customer submits to the Service.

## 2. Roles and scope

- The **Customer is the controller** of Customer Personal Data; **Mostakhles is the
  processor**.
- Mostakhles processes Customer Personal Data only to provide the Service and on the
  Customer's documented instructions (including as set out in this DPA, the Terms,
  and the Customer's use of the Service).
- Details of the processing are set out in **Annex I**.

## 3. Processor obligations

Mostakhles will:

1. Process Customer Personal Data only on the Customer's documented instructions,
   unless required by law (and will then inform the Customer where legally
   permitted).
2. Ensure persons authorised to process the data are bound by confidentiality.
3. Implement appropriate technical and organisational security measures — see
   **Annex II**.
4. Not use Customer Personal Data to train any AI model, and not sell or share it
   except as needed to run the Service via the sub-processors in **Annex III**.
5. Assist the Customer, taking into account the nature of processing, to respond to
   data-subject requests and to meet the Customer's own security, breach-
   notification, and impact-assessment obligations.
6. Make available information reasonably necessary to demonstrate compliance with
   this DPA (see *Audit*).
7. On termination, delete or return Customer Personal Data as set out in *Deletion
   and return*.

## 4. Sub-processors

The Customer provides **general authorisation** for Mostakhles to engage
sub-processors to provide the Service. The current sub-processors are listed in
**Annex III**. Mostakhles will:

- impose data-protection obligations on each sub-processor no less protective than
  those in this DPA; and
- give the Customer notice (via the policy page and/or email) before adding or
  replacing a sub-processor that processes Customer Personal Data, allowing the
  Customer a reasonable period to object on reasonable data-protection grounds.

## 5. International transfers

The Service transmits document content to Mostakhles's AI sub-processor (Google
Gemini) and may involve hosting, email, and payment providers that process data
outside the Customer's country. Where such transfers occur, Mostakhles relies on the
relevant provider's safeguards and contractual terms and will handle transfers in
line with the principles of the applicable Data Protection Laws. The Customer, as
controller, is responsible for confirming these transfers are acceptable for its own
compliance posture.
[[FOUNDER TO CONFIRM: whether any customers require an explicit transfer mechanism
(e.g. SCC-equivalent) — flag to lawyer if EU customers are onboarded.]]

## 6. Correction sharing via the Odoo connector

The Odoo connector includes an **opt-out** feature (`mostakhles.share_corrections`,
default **ON**) that sends field-level corrections (field name, original value,
corrected value, extraction identifier) back to Mostakhles to improve extraction
quality. Where such corrections may contain personal data, the **Customer decides**
whether to leave this feature on and is responsible for configuring the connector
accordingly (Odoo → Settings → Mostakhles → "Share corrections"). When disabled, no
corrections are sent.

## 7. Data-subject requests

Mostakhles will, taking into account the nature of processing, provide reasonable
assistance (including appropriate technical measures) to help the Customer respond
to requests from data subjects exercising their rights (access, correction,
deletion, objection, portability). If Mostakhles receives such a request directly, it
will forward it to the Customer and not respond independently except to confirm
receipt, unless legally required.

## 8. Personal data breach

Mostakhles will notify the Customer **without undue delay** after becoming aware of a
personal data breach affecting Customer Personal Data, and will provide information
reasonably available to help the Customer meet its own notification obligations.
Notice to Mostakhles of a suspected breach: [[FOUNDER TO CONFIRM: security contact
email, e.g. security@mostakhles.ai]].

## 9. Deletion and return

On expiry or termination, and at the Customer's choice, Mostakhles will delete or
return Customer Personal Data and delete existing copies, except where retention is
required by law. Because the Service does not store uploaded source files by default,
Customer Personal Data held by Mostakhles primarily consists of extraction results
in the Customer's account, saved templates, and shared corrections; deleting the
account removes these (subject to legally required retention such as billing records).

## 10. Audit

Mostakhles will make available to the Customer information reasonably necessary to
demonstrate compliance with this DPA and will contribute to audits conducted by the
Customer or its mandated auditor, on reasonable prior notice, no more than once per
year (unless required by a supervisory authority), and subject to confidentiality and
Mostakhles's security constraints.

## 11. Liability

Each party's liability under this DPA is subject to the limitations and exclusions in
the Terms of Service.
[[FOUNDER TO CONFIRM: confirm with lawyer that the Terms' liability cap validly
extends to this DPA under the governing law.]]

## 12. Governing law

This DPA is governed by the law stated in the Terms of Service
([[FOUNDER TO CONFIRM: governing law]]).

## 13. Signature

For business customers, this DPA is accepted either by signature below or by
accepting the Terms of Service that incorporate it by reference.

Customer (Controller): ______________________  Date: __________
Mostakhles (Processor): [[FOUNDER TO CONFIRM: signatory name / title]]  Date: __________

---

## Annex I — Details of processing

- **Subject matter:** provision of AI document-extraction services.
- **Duration:** for the term of the Customer's use of the Service.
- **Nature and purpose:** receiving documents, extracting structured data via an AI
  sub-processor, returning results, storing results/templates/corrections in the
  Customer's account, and supporting the Service.
- **Types of personal data (as determined by the Customer's documents):** may
  include names, national ID / passport numbers, addresses, contact details, bank /
  IBAN details, tax and commercial-registration numbers, health information (e.g.
  prescriptions), and any other personal data present in submitted documents.
- **Categories of data subjects:** as determined by the Customer — e.g. the
  Customer's own customers, employees, patients, suppliers, and counterparties.
- **Special-category data:** may be present (e.g. health data in prescriptions).
  The Customer is responsible for ensuring it has a lawful basis to process it.

## Annex II — Technical and organisational security measures

Measures in place today (described honestly; not a certification):

- Encryption in transit (TLS 1.3) between client, Service, and AI sub-processor.
- Uploaded source documents are not stored after processing by default.
- Passwords stored only as salted hashes; scoped, revocable API keys.
- Access to stored data limited to what is needed to operate and support the Service.
- Error monitoring and operational logging, with logs rotated on a limited schedule.
- Bot/abuse protection on public forms.

Not currently in place (do not represent otherwise): SOC 2 / ISO 27001
certification, contractual data-residency guarantees, dedicated single-tenant
infrastructure, or a formal uptime SLA.
[[FOUNDER TO CONFIRM: hosting provider name & region for completeness of this annex.]]

## Annex III — Approved sub-processors

| Sub-processor | Role | Purpose | Location |
|---|---|---|---|
| Google (Gemini API) | AI inference | Extracting data from document content | [[FOUNDER TO CONFIRM: processing region]] |
| Paymob | Payment processing | Billing (Egypt/EGP) | Egypt / regional |
| PayPal | Payment processing | Billing (international) | International |
| [[FOUNDER TO CONFIRM: hosting/VPS provider]] | Hosting | Running the Service and storing account data | [[FOUNDER TO CONFIRM: region]] |
| [[FOUNDER TO CONFIRM: SMTP / email provider]] | Transactional email | Account & billing emails | [[FOUNDER TO CONFIRM: region]] |
| Sentry | Error monitoring | Technical diagnostics | [[FOUNDER TO CONFIRM: region / self-hosted?]] |
| Cloudflare (Turnstile) | Bot protection | Abuse prevention on forms | Global CDN |

(PayTabs is planned as an additional payment sub-processor; this annex will be
updated before it goes live.)
