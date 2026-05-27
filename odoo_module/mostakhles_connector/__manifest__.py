{
    "name": "Mostakhles — Arabic Document AI",
    "version": "19.0.1.0.0",
    "summary": "Extract data from Arabic documents (invoices, IDs, prescriptions, handwriting) with Mostakhles AI",
    "description": """
Mostakhles Connector
====================
Read Arabic business documents — invoices, contracts, national IDs, prescriptions,
real-estate and legal papers, even handwriting — straight into Odoo.

Uploads a document to the Mostakhles AI platform, gets back structured fields
with a confidence score per field, and shows them inside Odoo.
""",
    "author": "Mageed Gerges",
    "website": "https://mostakhles.ai",
    "category": "Productivity/Documents",
    "license": "LGPL-3",
    "depends": ["base"],
    "data": [
        "security/ir.model.access.csv",
        "wizard/mostakhles_extract_wizard_views.xml",
        "views/res_config_settings_views.xml",
        "views/menus.xml",
    ],
    "application": True,
    "installable": True,
}
