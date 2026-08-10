"""PayTabs PayPage client (Gulf coverage: KSA mada + UAE / GCC cards).

Hosted-redirect checkout, mirroring the Paymob client shape so the billing
endpoints, dashboard, and renewal/cancel UI stay provider-agnostic:

  1. begin_checkout()  POST /payment/request  → (redirect_url, tran_ref)
  2. Redirect the user to redirect_url (PayTabs hosted PayPage — SAQ-A, we never
     touch card data).
  3. PayTabs POSTs a server-to-server IPN to our `callback` URL with the result
     and a `signature`, and returns the browser to our `return` URL.
  4. On the IPN we VERIFY authoritatively by calling query_transaction() with our
     Server Key — we never grant credits on the posted body alone. The posted
     `signature` is checked too (defence in depth), but the query is the gate.

`PAYTABS_BASE_URL` is region-specific and can point at a local mock for tests.
"""
import hashlib
import hmac
import json
import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import settings

log = logging.getLogger("mostakhles.paytabs")

# PayTabs "response_status" of an approved/authorised transaction.
APPROVED = "A"


class PayTabsError(RuntimeError):
    """Raised on any non-2xx from PayTabs or a missing key in the response."""


def _base() -> str:
    return settings.PAYTABS_BASE_URL.rstrip("/")


def _headers() -> dict[str, str]:
    return {"authorization": settings.PAYTABS_SERVER_KEY,
            "content-type": "application/json"}


def _profile_id() -> Any:
    pid = settings.PAYTABS_PROFILE_ID
    return int(pid) if str(pid).isdigit() else pid


def _post(path: str, body: dict[str, Any], timeout: float = 20.0) -> dict[str, Any]:
    if not settings.PAYTABS_PROFILE_ID or not settings.PAYTABS_SERVER_KEY:
        raise PayTabsError("PayTabs not configured (PAYTABS_PROFILE_ID / PAYTABS_SERVER_KEY)")
    url = f"{_base()}{path}"
    try:
        resp = httpx.post(url, json=body, headers=_headers(), timeout=timeout)
    except httpx.HTTPError as exc:
        raise PayTabsError(f"PayTabs network error on {path}: {exc}") from exc
    if resp.status_code >= 400:
        raise PayTabsError(f"PayTabs {resp.status_code} on {path}: {resp.text[:400]}")
    try:
        return resp.json()
    except json.JSONDecodeError as exc:
        raise PayTabsError(f"PayTabs returned non-JSON on {path}: {resp.text[:200]}") from exc


def begin_checkout(amount: float, currency: str, cart_id: str, description: str,
                   customer: dict[str, str], callback_url: str,
                   return_url: str) -> tuple[str, str]:
    """Create a hosted PayPage. Returns (redirect_url, tran_ref). `cart_id` is
    OUR merchant order id (mst_v1_…) — PayTabs echoes it back so we can map the
    payment to a user, same trick as Paymob's merchant_order_id."""
    body = {
        "profile_id": _profile_id(),
        "tran_type": "sale",
        "tran_class": "ecom",
        "cart_id": cart_id,
        "cart_currency": currency,
        "cart_amount": round(float(amount), 2),
        "cart_description": description[:100],
        "hide_shipping": True,
        "customer_details": customer,
        "callback": callback_url,   # server-to-server IPN
        "return": return_url,       # browser redirect back
    }
    data = _post("/payment/request", body)
    redirect = data.get("redirect_url")
    if not redirect:
        raise PayTabsError(f"begin_checkout: 'redirect_url' missing in response: {data}")
    return redirect, str(data.get("tran_ref") or "")


def query_transaction(tran_ref: str) -> dict[str, Any]:
    """Authoritative status fetch — the security gate. Because this call is
    authenticated with our Server Key, a forged IPN can't make us grant credits:
    we independently ask PayTabs what really happened to `tran_ref`."""
    return _post("/payment/query", {"profile_id": _profile_id(), "tran_ref": tran_ref})


def is_approved(query_result: dict[str, Any]) -> bool:
    pr = query_result.get("payment_result") or {}
    return str(pr.get("response_status") or "").upper() == APPROVED


def verify_signature(form: dict[str, str], received: str,
                     secret: str | None = None) -> bool:
    """Defence-in-depth check of the IPN `signature`: HMAC-SHA256 over the
    key-sorted, URL-encoded POST fields (excluding `signature`), keyed by the
    Server Key. NB the grant decision rests on query_transaction(), not this —
    PayTabs has signed a couple of different field-set variants over time, so we
    treat a mismatch as a warning, not a hard block."""
    sec = secret or settings.PAYTABS_SERVER_KEY
    if not sec or not received:
        return False
    fields = {k: v for k, v in form.items() if k != "signature" and v is not None}
    query = urlencode(sorted((k, str(v)) for k, v in fields.items()))
    expected = hmac.new(sec.encode(), query.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, (received or "").lower())
