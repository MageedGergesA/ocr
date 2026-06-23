# Copyright 2026 Mageed Gerges <mageed.gerges28@gmail.com>
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)
import base64
import json

from odoo import _, fields, models
from odoo.exceptions import UserError


class MostakhlesExtractWizard(models.TransientModel):
    _name = "mostakhles.extract.wizard"
    _description = "Extract Document Data with Mostakhles"

    document = fields.Binary(string="Document", required=True, attachment=False)
    filename = fields.Char(string="File Name")
    hard = fields.Boolean(
        string="High accuracy (Arabic & handwriting)", default=True,
        help="Precise mode — best for Arabic text and handwriting. Costs more credits.")
    document_type = fields.Char(string="Detected Type", readonly=True)
    line_ids = fields.One2many(
        "mostakhles.extract.line", "wizard_id", string="Extracted Fields")
    result_json = fields.Text(string="Raw Result", readonly=True)

    def action_extract(self):
        self.ensure_one()
        if not self.document:
            raise UserError(_("Please upload a document first."))
        file_bytes = base64.b64decode(self.document)
        result = self.env["mostakhles.api"].extract(
            file_bytes, filename=self.filename or "document", hard=self.hard)

        data = result.get("data") or {}
        if result.get("mode") == "batch":
            raise UserError(_(
                "This document was sent for batch processing (large PDF). "
                "Batch results aren't shown here yet — try a smaller file."))

        lines = [(5, 0, 0)]
        for name, raw in data.items():
            if isinstance(raw, dict):
                value, conf = raw.get("value"), raw.get("confidence")
            else:
                value, conf = raw, None
            lines.append((0, 0, {
                "name": name,
                "value": "" if value is None else str(value),
                "confidence": round(conf * 100) if isinstance(conf, (int, float)) else False,
            }))

        self.write({
            "document_type": result.get("document_type") or result.get("mode") or "",
            "result_json": json.dumps(result, ensure_ascii=False, indent=2),
            "line_ids": lines,
        })
        return {
            "type": "ir.actions.act_window",
            "res_model": "mostakhles.extract.wizard",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }


class MostakhlesExtractLine(models.TransientModel):
    _name = "mostakhles.extract.line"
    _description = "Mostakhles Extracted Field"
    _order = "id"

    wizard_id = fields.Many2one("mostakhles.extract.wizard", ondelete="cascade")
    name = fields.Char(string="Field", readonly=True)
    value = fields.Char(string="Value")
    confidence = fields.Integer(string="Confidence %", readonly=True)
