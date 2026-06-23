Changelog
=========

19.0.1.0.0 (2026-06-21)
-----------------------

Initial public release on the Odoo Apps Store.

Features
~~~~~~~~

* One-click "Extract with Mostakhles" wizard on any Odoo form view.
* 28+ document types auto-detected (invoices, IDs, prescriptions,
  contracts, bank statements, passports, business cards, utility bills).
* Cognitive extraction: per-field confidence scores, validations
  (tax-ID checksum, IBAN, MRZ check digits), computed values.
* Field mapping wizard — configure how Mostakhles fields land in Odoo
  records. Save reusable mappings per doctype.
* Bilingual UI (Arabic + English).
* Privacy-first: documents never used to train any AI model.

Technical
~~~~~~~~~

* Compatible with Odoo 19.0 (Community and Enterprise).
* Uses ``ir.config_parameter`` for the API key (no secrets in code).
* Connects to the Mostakhles SaaS API at ``api.mostakhles.ai``.
* Python dependency: ``requests`` (declared in ``external_dependencies``).
* Licensed under LGPL-3.0 or later.
