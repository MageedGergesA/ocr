# Copyright 2026 Mageed Gerges <mageed.gerges28@gmail.com>
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)
import base64
import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


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
    # Mostakhles History id for this extraction — the anchor for the correction
    # feedback loop (POST /v1/extract/correct/{hid}).
    hid = fields.Integer(string="Extraction ID", readonly=True)
    usage_info = fields.Char(string="Credits", readonly=True)

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        if "usage_info" in fields_list:
            vals["usage_info"] = self.env["mostakhles.api"]._usage_label()
        return vals

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
            strval = str(value)
            lines.append((0, 0, {
                "source_field": ml.source_field,
                "target_field": ml.field_name,
                "target_label": fld.string if fld else ml.field_name,
                "value": strval,
                # Snapshot what the model proposed, so on Apply we can tell which
                # values the human edited and feed those corrections back.
                "orig_value": strval,
                "confidence": confp,
                "apply": confp is False or confp >= 60,
            }))

        usage = result.get("usage") or {}
        self.write({
            "document_type": doc_type,
            "state": "preview",
            "hid": result.get("hid") or 0,
            "usage_info": self.env["mostakhles.api"]._format_usage(usage),
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
            self._log_to_chatter(target, vals)

        # THE MOAT: after the write succeeds, feed back any values the human
        # edited (extracted != final). Fire-and-forget — a failed callback must
        # never undo or block the Odoo write we just committed.
        self._capture_corrections()

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

    def _log_to_chatter(self, target, vals):
        """Post an audit note to the target's chatter (only if it's a mail.thread).
        Records the source file, detected type, and which fields were written —
        so there's a trail of what Mostakhles populated and from what document."""
        if not hasattr(target, "message_post"):
            return
        rows = "".join(
            "<li><strong>%s</strong>: %s</li>" % (
                (line.target_label or line.target_field), line.value)
            for line in self.line_ids.filtered("apply")
            if line.target_field in vals
        )
        body = _(
            "<p>Filled by <strong>Mostakhles</strong> from <em>%(file)s</em>"
            "%(typ)s.</p><ul>%(rows)s</ul>",
            file=self.filename or _("document"),
            typ=(_(" (detected: %s)") % self.document_type) if self.document_type else "",
            rows=rows,
        )
        try:
            target.message_post(body=body)
        except Exception as err:  # noqa: BLE001 — chatter note must not break Apply
            _logger.warning("Mostakhles chatter log skipped: %s", err)

    def _capture_corrections(self):
        """Send human edits (extracted value → corrected value) back to Mostakhles.

        Robust by design: guarded by a settings opt-out, wrapped so any error is
        logged and swallowed — the user's Odoo record is already saved and must
        stay saved regardless of what the feedback callback does.
        """
        icp = self.env["ir.config_parameter"].sudo()
        if icp.get_param("mostakhles.share_corrections", "True") in ("False", "0", ""):
            return
        if not self.hid:
            return
        api = self.env["mostakhles.api"]
        for line in self.line_ids:
            new = (line.value or "").strip()
            old = (line.orig_value or "").strip()
            if new and new != old:
                try:
                    api.submit_correction(self.hid, line.source_field, line.value)
                except Exception as err:  # noqa: BLE001 — never let feedback break Apply
                    _logger.warning("Mostakhles correction capture skipped: %s", err)

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
    # The value Mostakhles proposed, before any human edit — compared against
    # `value` on Apply to detect corrections for the feedback loop.
    orig_value = fields.Char(readonly=True)
    confidence = fields.Integer(string="Confidence %", readonly=True)
