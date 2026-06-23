# Copyright 2026 Mageed Gerges <mageed.gerges28@gmail.com>
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)
"""Tests for the `mostakhles.mapping` model.

Mappings are user-editable records that say "fields from doctype X should
land on Odoo model Y at these field names". The model needs to:

* Be queryable by ordinary users (read-only — see security/ir.model.access.csv).
* Cascade-delete with its target ir.model so we don't leak orphans.
* Round-trip create/read so the SaaS-repo integration tests can rely on it.
"""
from odoo.tests.common import TransactionCase


class TestMostakhlesMapping(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Mapping = cls.env["mostakhles.mapping"]
        cls.Model = cls.env["ir.model"]
        # res.partner is guaranteed to exist in every Odoo install.
        cls.partner_model = cls.Model.search([("model", "=", "res.partner")], limit=1)
        cls.assertTrue(cls.partner_model, "res.partner ir.model row missing — base broken?")

    def _make_mapping(self, **overrides):
        vals = {
            "name": "Test invoice → partner",
            "document_type": "invoice",
            "model_id": self.partner_model.id,
        }
        vals.update(overrides)
        return self.Mapping.create(vals)

    def test_create_and_read(self):
        """Round-trip a mapping. `model_name` should auto-populate from related."""
        m = self._make_mapping()
        self.assertEqual(m.name, "Test invoice → partner")
        self.assertEqual(m.document_type, "invoice")
        # `model_name` is `related="model_id.model"` and stored.
        self.assertEqual(m.model_name, "res.partner")
        self.assertTrue(m.active)

    def test_active_default_true(self):
        """Newly-created mapping is active out of the box."""
        m = self._make_mapping(name="Active default check")
        self.assertTrue(m.active)

    def test_document_type_optional(self):
        """No doctype → match any detected type for this model. The field
        should accept being left empty without raising."""
        m = self._make_mapping(name="Catch-all", document_type=False)
        self.assertFalse(m.document_type)
        self.assertEqual(m.model_name, "res.partner")
