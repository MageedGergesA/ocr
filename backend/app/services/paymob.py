"""Paymob Accept API client.

Three-step checkout:
  1. auth_token()   POST /api/auth/tokens         (api_key   -> bearer token, valid 1h)
  2. create_order() POST /api/ecommerce/orders    (auth+amount -> order_id)
  3. payment_key()  POST /api/acceptance/payment_keys (auth+order -> payment token)
  4. Redirect user to iframe_url(payment_token).
  5. Paymob POSTs callback with HMAC SHA512 over a fixed concat of fields.

We do not store the auth token across requests — Paymob is happy to mint a new one
per checkout, and the token is single-use-ish in practice.

`PAYMOB_BASE_URL` can point at the local mock (services.paymob_mock) for tests.
"""
import hashlib
import hmac
import json
import logging
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger("mostakhles.paymob")

# Order of fields concatenated to verify the transaction-processed HMAC.
# Source: https://docs.paymob.com/docs/hmac-calculation (transaction processed).
# DO NOT change the order — Paymob will compute the digest in exactly this sequence.
_HMAC_FIELDS = [
    "amount_cents", "created_at", "currency", "error_occured",
    "has_parent_transaction", "id", "integration_id", "is_3d_secure",
    "is_auth", "is_capture", "is_refunded", "is_standalone_payment",
    "is_voided", "order.id", "owner", "pending",
    "source_data.pan", "source_data.sub_type", "source_data.type", "success",
]


class PaymobError(RuntimeError):
    """Raised on any non-2xx from Paymob or missing-key in the response body."""


def _base() -> str:
    return settings.PAYMOB_BASE_URL.rstrip("/")


def _post(path: str, body: dict[str, Any], timeout: float = 15.0) -> dict[str, Any]:
    url = f"{_base()}{path}"
    try:
        resp = httpx.post(url, json=body, timeout=timeout)
    except httpx.HTTPError as exc:
        raise PaymobError(f"Paymob network error on {path}: {exc}") from exc
    if resp.status_code >= 400:
        raise PaymobError(f"Paymob {resp.status_code} on {path}: {resp.text[:400]}")
    try:
        return resp.json()
    except json.JSONDecodeError as exc:
        raise PaymobError(f"Paymob returned non-JSON on {path}: {resp.text[:200]}") from exc


def auth_token() -> str:
    """Mint a short-lived bearer for the subsequent order + payment_key calls."""
    data = _post("/api/auth/tokens", {"api_key": settings.PAYMOB_API_KEY})
    token = data.get("token")
    if not token:
        raise PaymobError(f"auth_token: 'token' missing in response: {data}")
    return token


def create_order(auth: str, amount_cents: int, merchant_order_id: str,
                 currency: str = "EGP") -> int:
    """Register the intended payment with Paymob. Returns the Paymob order ID
    we'll attach the payment_key to. `merchant_order_id` is OUR ID — we'll get
    it back on the webhook so we can map the payment to a user."""
    data = _post("/api/ecommerce/orders", {
        "auth_token": auth,
        "delivery_needed": "false",
        "amount_cents": str(amount_cents),
        "currency": currency,
        "merchant_order_id": merchant_order_id,
        "items": [],
    })
    order_id = data.get("id")
    if not order_id:
        raise PaymobError(f"create_order: 'id' missing in response: {data}")
    return int(order_id)


def integration_id_for(currency: str) -> str:
    """Resolve the Paymob integration (MID) to use for `currency`.

    Paymob integration IDs are per-currency: a USD charge must go through a
    USD-enabled MID and an EGP charge through an EGP MID. We prefer the
    currency-specific setting and fall back to the legacy PAYMOB_INTEGRATION_ID
    so single-currency accounts keep working without new config."""
    cur = (currency or "").upper()
    specific = {
        "USD": settings.PAYMOB_INTEGRATION_ID_USD,
        "EGP": settings.PAYMOB_INTEGRATION_ID_EGP,
    }.get(cur, "")
    return specific or settings.PAYMOB_INTEGRATION_ID


def payment_key(auth: str, order_id: int, amount_cents: int,
                billing: dict[str, str], integration_id: str | None = None,
                currency: str = "EGP", expiration: int = 3600) -> str:
    """Mint the per-checkout token consumed by the iframe."""
    iid = integration_id or integration_id_for(currency)
    if not iid:
        raise PaymobError(
            f"payment_key: no Paymob integration configured for {currency} "
            f"(set PAYMOB_INTEGRATION_ID_{currency.upper()} or PAYMOB_INTEGRATION_ID)")
    data = _post("/api/acceptance/payment_keys", {
        "auth_token": auth,
        "amount_cents": str(amount_cents),
        "expiration": expiration,
        "order_id": order_id,
        "billing_data": billing,
        "currency": currency,
        "integration_id": int(iid),
    })
    token = data.get("token")
    if not token:
        raise PaymobError(f"payment_key: 'token' missing in response: {data}")
    return token


def iframe_url(payment_token: str, iframe_id: str | None = None) -> str:
    iid = iframe_id or settings.PAYMOB_IFRAME_ID
    if not iid:
        raise PaymobError("iframe_url: PAYMOB_IFRAME_ID not configured")
    return f"{_base()}/api/acceptance/iframes/{iid}?payment_token={payment_token}"


# ---------------------------------------------------------------------------
# HMAC verification of the webhook callback.
# ---------------------------------------------------------------------------

def _flatten(obj: dict, key: str) -> str:
    """Walk a dotted key path against the obj payload, returning the value as
    a string. Missing keys collapse to '' (Paymob hashes the empty string)."""
    cur: Any = obj
    for part in key.split("."):
        if not isinstance(cur, dict):
            return ""
        cur = cur.get(part)
        if cur is None:
            return ""
    # Paymob hashes booleans as the lowercase string ('true' / 'false').
    if isinstance(cur, bool):
        return "true" if cur else "false"
    return str(cur)


def verify_hmac(obj: dict, received_hmac: str,
                secret: str | None = None) -> bool:
    """Verify the SHA-512 HMAC Paymob sends with every transaction callback.

    `obj` is the parsed JSON body — NOT the wrapper, just the inner `obj`
    object Paymob delivers under `{"type": "TRANSACTION", "obj": {...}}`.
    Returns True on a match, False on tamper / missing config."""
    sec = secret or settings.PAYMOB_HMAC
    if not sec or not received_hmac:
        return False
    payload = "".join(_flatten(obj, k) for k in _HMAC_FIELDS)
    expected = hmac.new(sec.encode(), payload.encode(), hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, received_hmac.lower())


# ---------------------------------------------------------------------------
# High-level convenience: one call from /billing/checkout.
# ---------------------------------------------------------------------------

def begin_checkout(amount: float, merchant_order_id: str,
                   billing: dict[str, str], currency: str = "EGP") -> tuple[str, int]:
    """End-to-end: mint auth, create order, mint payment key. Returns
    (iframe_url, paymob_order_id). `amount` is in the MAJOR unit of `currency`
    (e.g. dollars for USD, pounds for EGP). Caller writes a Subscription row
    keyed by merchant_order_id BEFORE redirecting the user."""
    currency = (currency or "EGP").upper()
    amount_cents = int(round(amount * 100))
    tok = auth_token()
    order_id = create_order(tok, amount_cents, merchant_order_id, currency=currency)
    pk = payment_key(tok, order_id, amount_cents, billing, currency=currency)
    return iframe_url(pk), order_id
