# Copyright 2026 Mageed Gerges <mageed.gerges28@gmail.com>
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    mostakhles_api_key = fields.Char(
        string="Mostakhles API Key",
        config_parameter="mostakhles.api_key",
        help="Create a key in your Mostakhles dashboard (mostakhles.ai → لوحة التحكم).",
    )
    mostakhles_base_url = fields.Char(
        string="Mostakhles Base URL",
        config_parameter="mostakhles.base_url",
        default="https://api.mostakhles.ai",
        help="The Mostakhles API base URL. Leave as default unless self-hosting.",
    )
    mostakhles_share_corrections = fields.Boolean(
        string="Share corrections to improve accuracy",
        config_parameter="mostakhles.share_corrections",
        default=True,
        help="When you edit an extracted value before applying it, send the "
             "correction back to Mostakhles so the Arabic models keep improving. "
             "Only the field name and your corrected value are sent — never the "
             "document. Turn this off to opt out.",
    )
