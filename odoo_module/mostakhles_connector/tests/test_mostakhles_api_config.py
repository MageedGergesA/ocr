# Copyright 2026 Mageed Gerges <mageed.gerges28@gmail.com>
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)
"""Tests for the Mostakhles API client's config plumbing.

We intentionally DON'T hit the real Mostakhles API in tests — these tests
verify that:

* The abstract model is registered with the expected name.
* `_config()` reads `mostakhles.api_key` / `mostakhles.base_url` from
  `ir.config_parameter` and falls back to the documented default base URL.
* `_config()` raises a clear UserError when no API key is set (this is the
  message that surfaces in the wizard if the user hasn't configured the
  module yet).

Network behaviour (`extract()`) is covered by integration tests in the
SaaS repo, not here.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestMostakhlesApiConfig(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.api = cls.env["mostakhles.api"]
        cls.icp = cls.env["ir.config_parameter"].sudo()

    def test_abstract_model_registered(self):
        """The API client is exposed under the expected technical name."""
        self.assertIn("mostakhles.api", self.env.registry)
        self.assertTrue(
            self.api._abstract,
            "mostakhles.api should be an AbstractModel — no DB table needed.",
        )

    def test_missing_api_key_raises_userwarning(self):
        """No key configured → friendly UserError pointing to Settings."""
        self.icp.set_param("mostakhles.api_key", "")
        with self.assertRaises(UserError) as ctx:
            self.api._config()
        # Make sure the message names "Settings" so the user knows where to go.
        self.assertIn("Settings", str(ctx.exception))

    def test_config_returns_default_base_url(self):
        """No explicit base URL → fall back to the documented prod endpoint."""
        self.icp.set_param("mostakhles.api_key", "test-key-not-real")
        self.icp.set_param("mostakhles.base_url", "")
        key, base = self.api._config()
        self.assertEqual(key, "test-key-not-real")
        self.assertEqual(base, "https://api.mostakhles.ai")

    def test_config_strips_trailing_slash_on_base_url(self):
        """User pasted a URL with a trailing slash — we must strip it so the
        downstream request joins paths cleanly with f"{base}/v1/extract"."""
        self.icp.set_param("mostakhles.api_key", "test-key-not-real")
        self.icp.set_param("mostakhles.base_url", "https://staging.example.com/")
        _, base = self.api._config()
        self.assertEqual(base, "https://staging.example.com")
