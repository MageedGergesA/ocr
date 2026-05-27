from odoo import api, fields, models

# A code server action bound to the target model — shows "extract & fill" in its Action menu.
BINDING_ACTION_NAME = "استخرِج واملأ بمُستخلِص"
BINDING_CODE = """\
action = {
    'type': 'ir.actions.act_window',
    'name': 'استخرِج واملأ بمُستخلِص',
    'res_model': 'mostakhles.fill.wizard',
    'view_mode': 'form',
    'target': 'new',
    'context': {
        'default_res_model': env.context.get('active_model'),
        'default_res_id': env.context.get('active_id'),
    },
}
"""


class MostakhlesMapping(models.Model):
    _name = "mostakhles.mapping"
    _description = "Mostakhles Field Mapping"
    _order = "model_id, document_type"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    document_type = fields.Char(
        string="Document Type",
        help="Mostakhles document type to match (e.g. invoice, prescription, egyptian_id). "
             "Leave empty to match any detected type for this model.")
    model_id = fields.Many2one(
        "ir.model", string="Target Model", required=True, ondelete="cascade")
    model_name = fields.Char(related="model_id.model", store=True, string="Model")
    line_ids = fields.One2many(
        "mostakhles.mapping.line", "mapping_id", string="Field Mapping")
    action_id = fields.Many2one(
        "ir.actions.server", string="Record Action", readonly=True, copy=False)

    def _sync_binding(self):
        """Ensure a single 'extract & fill' Action-menu entry exists per target model."""
        server = self.env["ir.actions.server"].sudo()
        for rec in self.filtered(lambda m: m.active and m.model_id):
            action = server.search([
                ("binding_model_id", "=", rec.model_id.id),
                ("name", "=", BINDING_ACTION_NAME),
            ], limit=1)
            if not action:
                action = server.create({
                    "name": BINDING_ACTION_NAME,
                    "model_id": rec.model_id.id,
                    "binding_model_id": rec.model_id.id,
                    "state": "code",
                    "code": BINDING_CODE,
                })
            rec.action_id = action.id

    def _cleanup_binding(self):
        server = self.env["ir.actions.server"].sudo()
        for rec in self:
            still_used = self.search_count([
                ("model_id", "=", rec.model_id.id),
                ("id", "!=", rec.id),
                ("active", "=", True),
            ])
            if not still_used and rec.action_id:
                rec.action_id.unlink()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_binding()
        return records

    def write(self, vals):
        res = super().write(vals)
        if {"model_id", "active"} & set(vals):
            self.filtered("active")._sync_binding()
            self.filtered(lambda m: not m.active)._cleanup_binding()
        return res

    def unlink(self):
        self._cleanup_binding()
        return super().unlink()


class MostakhlesMappingLine(models.Model):
    _name = "mostakhles.mapping.line"
    _description = "Mostakhles Field Mapping Line"
    _order = "id"

    mapping_id = fields.Many2one(
        "mostakhles.mapping", required=True, ondelete="cascade")
    source_field = fields.Char(
        string="Extracted Field", required=True,
        help="Field name as returned by Mostakhles, e.g. patient_name, total, phone_1.")
    field_id = fields.Many2one(
        "ir.model.fields", string="Odoo Field", required=True, ondelete="cascade")
    field_name = fields.Char(related="field_id.name", store=True, string="Technical Name")
