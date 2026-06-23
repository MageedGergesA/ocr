{
    "name": "Mostakhles — Arabic Document AI",
    # Odoo version (19.0) + module version (1.0.0).
    "version": "19.0.1.0.0",
    # Short, single-sentence summary (shown under the title on the listing).
    "summary": "Extract structured data from Arabic invoices, IDs, prescriptions, "
               "contracts, and handwriting straight into Odoo.",
    # The full long-form description lives in static/description/index.html.
    # Keep this field SHORT — it's what shows when the index.html isn't
    # rendered (e.g. in odoo-bin update output, IDE tooltips).
    "description": "Mostakhles Connector — Arabic document AI extraction for Odoo.",
    "author": "Mageed Gerges",
    "maintainer": "Mageed Gerges <mageed.gerges28@gmail.com>",
    "website": "https://mostakhles.ai",
    "support": "support@mostakhles.ai",
    # Official Odoo category. "Productivity/Documents" was a custom nesting
    # the Apps Store moderators reject — moved to the canonical category.
    "category": "Document Management",
    "license": "LGPL-3",
    "depends": ["base"],
    # The Mostakhles API client uses `requests`. Apps Store moderators require
    # third-party Python deps to be declared here so odoo-bin's pre-install
    # check can fail fast with a clear message.
    "external_dependencies": {
        "python": ["requests"],
    },
    "data": [
        "security/ir.model.access.csv",
        "wizard/mostakhles_extract_wizard_views.xml",
        "wizard/mostakhles_fill_wizard_views.xml",
        "views/mostakhles_mapping_views.xml",
        "views/res_config_settings_views.xml",
        "views/menus.xml",
    ],
    # Image used for the Apps Store listing's social-share preview + banner.
    # Path is relative to the module root.
    "images": [
        "static/description/banner.png",
    ],
    "application": True,
    "installable": True,
}
