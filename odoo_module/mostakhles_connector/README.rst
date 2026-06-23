============================
Mostakhles Connector for Odoo
============================

.. |badge_license| image:: https://img.shields.io/badge/licence-LGPL--3-blue.svg
    :alt: License: LGPL-3
.. |badge_odoo| image:: https://img.shields.io/badge/Odoo-19.0-714B67.svg
    :alt: Odoo 19.0

|badge_license| |badge_odoo|

Extract structured data from Arabic invoices, national IDs, prescriptions,
contracts, and handwritten documents — straight into Odoo records, in one
click.

This module connects your Odoo instance to the **Mostakhles AI** document
extraction API (https://mostakhles.ai) and exposes a one-click *Extract*
wizard on any record.

.. contents::
   :local:

Features
========

* **One-click extraction** — Drop an image or PDF on any Odoo form view,
  the wizard auto-detects the document type and returns structured fields.
* **28+ document types** out of the box: tax invoices, Egyptian IDs, Saudi
  commercial registers, Arabic prescriptions, lease contracts, passports,
  bank statements, business cards, utility bills.
* **Cognitive extraction** — per-field confidence scores, plain-language
  summary, validations (tax-ID checksum, IBAN, MRZ check digits, totals
  reconcile), and computed values (subtotals, tax, ages).
* **Field mapping wizard** — configure how Mostakhles fields land in your
  Odoo records. Save reusable mappings per doctype, share across users.
* **Privacy first** — documents are never used to train any AI model
  (contractually guaranteed via the Mostakhles DPA).
* **Bilingual UI** — every label available in Arabic and English; respects
  the user's preferred language.

Installation
============

#. Make sure the Python ``requests`` library is installed in the same
   environment as Odoo. On a stock Odoo install:

   .. code-block:: bash

      pip install requests

#. Clone or copy this module into your Odoo addons path.

#. Restart Odoo and update the apps list:

   .. code-block:: bash

      ./odoo-bin -d <your_db> --update-list

#. Install the module from *Apps* → search "Mostakhles".

Configuration
=============

#. Sign up at https://mostakhles.ai/signup — you get **30 free credits per
   month**, no credit card required.

#. Open *Settings → Mostakhles* in your Odoo instance.

#. Paste your API key from the Mostakhles dashboard. Save.

#. (Optional) Override the API base URL if you're on a self-hosted
   Mostakhles deployment.

Usage
=====

On any Odoo form view (invoice, partner, lead, HR contract, …):

#. Click the **Extract with Mostakhles** button in the form's button box.

#. Drop a document (PDF, JPG, PNG) or upload it from your file system.

#. Pick the target doctype — or leave it on *Auto-detect*.

#. Click **Extract**. The wizard shows extracted fields with confidence
   scores in a few seconds.

#. Review low-confidence values inline, then click **Apply** to write the
   data into the Odoo record. The chatter on the record gets an audit
   message with the source filename, doctype, and confidence summary.

Custom field mappings
---------------------

The default mappings cover the standard Odoo models (account.move,
res.partner, hr.contract). To map Mostakhles fields onto a custom Odoo
model:

#. Go to *Settings → Mostakhles → Field mappings*.

#. Click *Create*, pick the Odoo model + the source doctype, and add
   ``mostakhles_field → odoo_field`` rows.

#. Save. The mapping is now available system-wide on that model's form.

Pricing
=======

The Odoo module is **free**. The Mostakhles SaaS API it connects to is
metered by credits — see https://mostakhles.ai/pricing.

Requirements
============

* Odoo 19.0 (Community or Enterprise)
* Python ``requests`` package
* Outbound HTTPS to ``api.mostakhles.ai``
* A free or paid Mostakhles account

Support
=======

Bugs, feature requests, or general questions:

* Email: support@mostakhles.ai
* API docs: https://mostakhles.ai/docs
* Status page: https://status.mostakhles.ai

Credits
=======

Author
------

* Mageed Gerges — `mageed.gerges28@gmail.com <mailto:mageed.gerges28@gmail.com>`_

Maintainer
----------

This module is maintained by Mostakhles (https://mostakhles.ai).
For commercial support, deployment help, or custom doctype training,
write to support@mostakhles.ai.

License
=======

LGPL-3. See the ``LICENSE`` file at the repository root for the full text.
