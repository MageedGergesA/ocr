# Copyright 2026 Mageed Gerges <mageed.gerges28@gmail.com>
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0)
import json

import requests

from odoo import _, api, models
from odoo.exceptions import UserError


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
