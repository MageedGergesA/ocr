# Copyright 2026 Mageed Gerges <mageed.gerges28@gmail.com>
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)
import json
import logging

import requests

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Shown whenever the account is out of credits — a single source of truth so the
# "upgrade at the wall" prompt is identical everywhere it can fire.
PRICING_URL = "https://mostakhles.ai/pricing"


class MostakhlesApi(models.AbstractModel):
    """Thin client for the Mostakhles document-extraction API.

    Other models call ``self.env["mostakhles.api"].extract(...)``.
    """
    _name = "mostakhles.api"
    _description = "Mostakhles API Client"

    @api.model
    def _config(self):
        icp = self.env["ir.config_parameter"].sudo()
        key = icp.get_param("mostakhles.api_key")
        base = (icp.get_param("mostakhles.base_url") or "https://api.mostakhles.ai").rstrip("/")
        if not key:
            raise UserError(_(
                "No Mostakhles API key configured.\n"
                "Go to Settings → Mostakhles and paste the key from your dashboard."
            ))
        return key, base

    @api.model
    def extract(self, file_bytes, filename="document", hard=True, target_schema=None):
        """Send a document to /v1/extract and return the parsed JSON result.

        :param bytes file_bytes: raw file content (decoded, not base64).
        :param str filename: original file name.
        :param bool hard: precise mode (Arabic & handwriting) vs fast mode.
        :param dict target_schema: optional {field: description} for a custom schema.
        :returns: dict with keys like ``document_type``, ``data``, ``usage``.
        """
        key, base = self._config()
        data = {"hard": "true" if hard else "false"}
        if target_schema:
            data["target_schema"] = json.dumps(target_schema)
        try:
            resp = requests.post(
                f"{base}/v1/extract",
                headers={"x-api-key": key},
                files={"file": (filename or "document", file_bytes)},
                data=data,
                timeout=180,
            )
        except requests.RequestException as err:
            raise UserError(_("Could not reach Mostakhles: %s") % err)

        if resp.status_code in (402, 429):
            # Out of credits (or rate-limited on the quota). Be honest and point
            # the user straight at the upgrade page instead of a cryptic error.
            raise UserError(_(
                "You're out of Mostakhles credits for this billing period.\n"
                "Upgrade your plan to keep extracting: %s"
            ) % PRICING_URL)
        if resp.status_code != 200:
            detail = resp.text
            try:
                detail = resp.json().get("detail", detail)
            except ValueError:
                pass
            raise UserError(_("Mostakhles error (%(code)s): %(msg)s",
                              code=resp.status_code, msg=detail))
        try:
            return resp.json()
        except ValueError:
            raise UserError(_("Mostakhles returned an unexpected (non-JSON) response."))

    @api.model
    def get_usage(self):
        """Return the caller's current-month quota as {used, limit, remaining},
        or ``None`` if it can't be fetched. Best-effort: never raises, so a
        usage-meter widget can call it on form load without risking the wizard.
        """
        try:
            key, base = self._config()
        except UserError:
            return None
        try:
            resp = requests.get(
                f"{base}/v1/usage", headers={"x-api-key": key}, timeout=15)
            if resp.status_code == 200:
                return resp.json()
        except (requests.RequestException, ValueError) as err:
            _logger.warning("Mostakhles usage lookup failed: %s", err)
        return None

    @api.model
    def _format_usage(self, usage):
        """Format a usage dict ``{used, limit, remaining}`` into a short label,
        or '' if it's empty/unusable."""
        if not usage:
            return ""
        remaining = usage.get("remaining")
        limit = usage.get("limit")
        if remaining is None or limit is None:
            return ""
        return _("Credits left: %(remaining)s / %(limit)s",
                 remaining=remaining, limit=limit)

    @api.model
    def _usage_label(self):
        """Best-effort usage label for a wizard opening on the upload step."""
        return self._format_usage(self.get_usage())

    @api.model
    def submit_correction(self, hid, field, value):
        """Fire-and-forget POST of a single human correction to
        /v1/extract/correct/{hid}. This is the feedback loop that builds the
        proprietary Arabic-correction dataset.

        Deliberately swallows every failure and returns a bool: capturing
        training signal must NEVER block or roll back the user's Odoo write.
        """
        if not hid or not field:
            return False
        try:
            key, base = self._config()
        except UserError:
            return False
        try:
            resp = requests.post(
                f"{base}/v1/extract/correct/{hid}",
                headers={"x-api-key": key},
                json={"field": field, "value": value},
                timeout=15,
            )
            if resp.status_code == 200:
                return True
            _logger.warning(
                "Mostakhles correction callback for hid=%s returned %s: %s",
                hid, resp.status_code, resp.text[:200])
        except requests.RequestException as err:
            _logger.warning("Mostakhles correction callback failed (hid=%s): %s", hid, err)
        return False
