# Copyright 2026 Mageed Gerges <mageed.gerges28@gmail.com>
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)
"""Regression guard for the two revenue/moat features:

* The correction-capture feedback loop (`_capture_corrections` on the fill
  wizard) — the human-in-the-loop signal that builds the proprietary
  Arabic-correction dataset.
* The usage-meter labels (`_format_usage` / `_usage_label`) that power the
  "credits remaining" widget and the upgrade-at-the-wall prompt.

Every test mocks ``requests`` at the module boundary, so NOTHING here touches
the network or the live SaaS. We assert behaviour, not wire format:

(a) only EDITED fill.lines (value != orig_value) fire a correction; unedited
    lines are silent.
(b) the ``mostakhles.share_corrections=False`` opt-out short-circuits entirely.
(c) a missing ``hid`` degrades gracefully — no call, no error.
(d) ``_format_usage`` / ``_usage_label`` label a normal quota, an exhausted
    quota (remaining<=0), and a missing/None payload correctly.
"""
from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase

# Patch requests where it's LOOKED UP (the api module's global), not where it's
# defined — otherwise the real library still runs.
REQUESTS = "odoo.addons.mostakhles_connector.models.mostakhles_api.requests"


class TestMostakhlesFeedback(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.api = cls.env["mostakhles.api"]
        cls.icp = cls.env["ir.config_parameter"].sudo()
        # A key must be present so submit_correction()/get_usage() reach the
        # (mocked) HTTP call instead of bailing early in _config().
        cls.icp.set_param("mostakhles.api_key", "test-key-not-real")
        cls.icp.set_param("mostakhles.base_url", "https://api.example.test")
        cls.icp.set_param("mostakhles.share_corrections", "True")

    def _ok_response(self, json_body=None):
        """A MagicMock that looks like a 200 requests.Response."""
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = json_body or {"ok": True, "corrected_count": 1}
        return resp

    def _make_wizard(self, hid, lines):
        """Build a fill wizard with the given hid and (source_field, value,
        orig_value) lines. Created inside a requests patch by the caller so the
        default_get usage lookup never hits the network."""
        return self.env["mostakhles.fill.wizard"].create({
            "hid": hid,
            "line_ids": [
                (0, 0, {"source_field": sf, "value": v, "orig_value": ov,
                        "target_field": sf, "target_label": sf})
                for (sf, v, ov) in lines
            ],
        })

    # -- (a) only edited lines fire a correction ---------------------------
    def test_only_edited_lines_are_sent(self):
        with patch(REQUESTS) as mock_requests:
            mock_requests.post.return_value = self._ok_response()
            wiz = self._make_wizard(hid=101, lines=[
                ("name_ar", "الاسم المصحّح", "الاسم الأصلي"),  # edited
                ("phone", "0100000000", "0100000000"),          # untouched
                ("tax_id", "  ", ""),                            # blank → ignored
            ])
            wiz._capture_corrections()

            # Exactly one POST — for the edited line only.
            mock_requests.post.assert_called_once()
            sent_field = mock_requests.post.call_args.kwargs["json"]["field"]
            self.assertEqual(sent_field, "name_ar")
            # And it targeted the correct hid endpoint.
            self.assertIn("/v1/extract/correct/101", mock_requests.post.call_args.args[0])

    # -- (b) opt-out short-circuits ----------------------------------------
    def test_optout_sends_nothing(self):
        self.icp.set_param("mostakhles.share_corrections", "False")
        self.addCleanup(self.icp.set_param, "mostakhles.share_corrections", "True")
        with patch(REQUESTS) as mock_requests:
            mock_requests.post.return_value = self._ok_response()
            wiz = self._make_wizard(hid=102, lines=[
                ("name_ar", "قيمة جديدة", "قيمة قديمة"),  # edited, but opted out
            ])
            wiz._capture_corrections()
            mock_requests.post.assert_not_called()

    # -- (c) missing hid degrades gracefully -------------------------------
    def test_missing_hid_is_safe(self):
        with patch(REQUESTS) as mock_requests:
            mock_requests.post.return_value = self._ok_response()
            wiz = self._make_wizard(hid=0, lines=[
                ("name_ar", "قيمة جديدة", "قيمة قديمة"),  # edited, but no hid
            ])
            # Must not raise and must not call out.
            wiz._capture_corrections()
            mock_requests.post.assert_not_called()

    # -- (c-bis) a failing callback never propagates -----------------------
    def test_callback_failure_never_raises(self):
        with patch(REQUESTS) as mock_requests:
            import requests as real_requests
            mock_requests.RequestException = real_requests.RequestException
            mock_requests.post.side_effect = real_requests.RequestException("boom")
            wiz = self._make_wizard(hid=103, lines=[
                ("name_ar", "قيمة جديدة", "قيمة قديمة"),
            ])
            # A network blow-up must be swallowed — the Odoo write already
            # committed and must stay committed.
            wiz._capture_corrections()  # no assertRaises: it must simply return

    # -- (d) usage labels --------------------------------------------------
    def test_format_usage_labels(self):
        self.assertEqual(
            self.api._format_usage({"used": 90, "limit": 100, "remaining": 10}),
            "Credits left: 10 / 100",
        )
        # Exhausted (remaining == 0) still yields a truthful label, not "".
        self.assertEqual(
            self.api._format_usage({"used": 100, "limit": 100, "remaining": 0}),
            "Credits left: 0 / 100",
        )
        # Missing / unusable payloads produce no label (widget stays hidden).
        self.assertEqual(self.api._format_usage(None), "")
        self.assertEqual(self.api._format_usage({}), "")
        self.assertEqual(self.api._format_usage({"remaining": 5}), "")

    def test_usage_label_reads_live_quota(self):
        with patch(REQUESTS) as mock_requests:
            mock_requests.get.return_value = self._ok_response(
                {"used": 40, "limit": 50, "remaining": 10})
            self.assertEqual(self.api._usage_label(), "Credits left: 10 / 50")

    def test_usage_label_swallows_network_error(self):
        with patch(REQUESTS) as mock_requests:
            import requests as real_requests
            mock_requests.RequestException = real_requests.RequestException
            mock_requests.get.side_effect = real_requests.RequestException("down")
            # Best-effort: a failed lookup yields "" so the wizard still opens.
            self.assertEqual(self.api._usage_label(), "")
