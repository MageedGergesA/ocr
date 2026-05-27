import base64
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class MostakhlesFillWizard(models.TransientModel):
    _name = "mostakhles.fill.wizard"
    _description = "Extract & Fill Record with Mostakhles"

    res_model = fields.Char(string="Model", readonly=True)
    res_id = fields.Integer(string="Record ID", readonly=True)
    record_name = fields.Char(string="Record", compute="_compute_record_name")
    document = fields.Binary(string="Document", attachment=False)
    filename = fields.Char()
    hard = fields.Boolean(
        string="High accuracy (Arabic & handwriting)", default=True,
        help="Precise mode — best for Arabic and handwriting. Costs more credits.")
    document_type = fields.Char(string="Detected Type", readonly=True)
    state = fields.Selection(
        [("upload", "Upload"), ("preview", "Preview")], default="upload")
    line_ids = fields.One2many("mostakhles.fill.line", "wizard_id", string="Proposed Values")
    info = fields.Char(readonly=True)

    @api.depends("res_model", "res_id")
    def _compute_record_name(self):
        for w in self:
            name = ""
            if w.res_model and w.res_id and w.res_model in self.env:
                rec = self.env[w.res_model].browse(w.res_id).exists()
                name = rec.display_name if rec else ""
            w.record_name = name

    def action_extract(self):
        self.ensure_one()
        if not self.document:
            raise UserError(_("Please upload a document first."))
        if not (self.res_model and self.res_id):
            raise UserError(_("No target record — open this from a record's Action menu."))

        result = self.env["mostakhles.api"].extract(
            base64.b64decode(self.document), filename=self.filename or "document", hard=self.hard)
        if result.get("mode") == "batch":
            raise UserError(_("Large PDFs (batch processing) aren't supported here yet."))

        data = result.get("data") or {}
        doc_type = result.get("document_type") or ""
        mapping = self._find_mapping(doc_type)
        if not mapping:
            raise UserError(_(
                "No field mapping found for model '%(model)s'%(typ)s.\n"
                "Create one under Mostakhles → Field Mappings.",
                model=self.res_model,
                typ=(_(" and type '%s'") % doc_type) if doc_type else ""))

        target = self.env[self.res_model].browse(self.res_id)
        lines = [(5, 0, 0)]
        for ml in mapping.line_ids:
            raw = data.get(ml.source_field)
            value, conf = (raw.get("value"), raw.get("confidence")) if isinstance(raw, dict) else (raw, None)
            if value in (None, ""):
                continue
            fld = target._fields.get(ml.field_name)
            confp = round(conf * 100) if isinstance(conf, (int, float)) else False
            lines.append((0, 0, {
                "source_field": ml.source_field,
                "target_field": ml.field_name,
                "target_label": fld.string if fld else ml.field_name,
                "value": str(value),
                "confidence": confp,
                "apply": confp is False or confp >= 60,
            }))

        self.write({
            "document_type": doc_type,
            "state": "preview",
            "line_ids": lines,
            "info": _("%d field(s) matched — review and apply.") % (len(lines) - 1),
        })
        return self._reopen()

    def _find_mapping(self, doc_type):
        Mapping = self.env["mostakhles.mapping"]
        base = [("model_name", "=", self.res_model), ("active", "=", True)]
        return (
            (doc_type and Mapping.search(base + [("document_type", "=", doc_type)], limit=1))
            or Mapping.search(base + [("document_type", "in", [False, ""])], limit=1)
            or Mapping.search(base, limit=1)
        )

    def action_apply(self):
        self.ensure_one()
        target = self.env[self.res_model].browse(self.res_id).exists()
        if not target:
            raise UserError(_("The target record no longer exists."))

        vals, skipped = {}, []
        for line in self.line_ids.filtered("apply"):
            fld = target._fields.get(line.target_field)
            if not fld:
                skipped.append(line.target_field)
                continue
            try:
                vals[line.target_field] = self._coerce(fld, line.value)
            except Exception:  # noqa: BLE001 — one bad field shouldn't abort the rest
                skipped.append(line.target_label or line.target_field)
        if vals:
            target.write(vals)

        msg = _("Updated %(n)d field(s) on %(rec)s.", n=len(vals), rec=target.display_name)
        if skipped:
            msg += _(" Skipped (couldn't convert): %s.") % ", ".join(skipped)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "مُستخلِص",
                "message": msg,
                "type": "success" if vals else "warning",
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    def _coerce(self, field, value):
        """Convert a string value to the target Odoo field's type."""
        t = field.type
        v = value.strip()
        if t in ("char", "text", "html", "selection"):
            return v
        if t == "integer":
            return int(float(re.sub(r"[^\d.\-]", "", v) or 0))
        if t in ("float", "monetary"):
            return float(re.sub(r"[^\d.\-]", "", v.replace(",", "")) or 0)
        if t == "boolean":
            return v.lower() in ("1", "true", "yes", "نعم", "صح")
        if t == "date":
            return fields.Date.to_date(v)
        if t == "datetime":
            return fields.Datetime.to_datetime(v)
        if t == "many2one":
            rec = self.env[field.comodel_name].search([("display_name", "=ilike", v)], limit=1)
            if not rec:
                raise ValueError("no match for %r" % v)
            return rec.id
        return v

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": "mostakhles.fill.wizard",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }


class MostakhlesFillLine(models.TransientModel):
    _name = "mostakhles.fill.line"
    _description = "Mostakhles Fill Preview Line"
    _order = "id"

    wizard_id = fields.Many2one("mostakhles.fill.wizard", ondelete="cascade")
    apply = fields.Boolean(string="Apply", default=True)
    source_field = fields.Char(string="Extracted", readonly=True)
    target_label = fields.Char(string="Odoo Field", readonly=True)
    target_field = fields.Char(readonly=True)
    value = fields.Char(string="Value")
    confidence = fields.Integer(string="Confidence %", readonly=True)
