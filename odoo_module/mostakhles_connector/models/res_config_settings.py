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
