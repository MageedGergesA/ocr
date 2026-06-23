"""PayPal REST client — Subscriptions API.

Subscription checkout flow:
  1. auth_token()           POST /v1/oauth2/token         (client_id+secret -> bearer, ~9h TTL)
  2. create_subscription()  POST /v1/billing/subscriptions (plan_id -> sub_id + approval URL)
  3. Redirect user to the approval URL — they consent on PayPal's site.
  4. PayPal redirects them back to our return_url with ?subscription_id=I-xxx&token=...
  5. We GET /v1/billing/subscriptions/{id} to confirm status=ACTIVE before upgrading.
  6. PayPal also POSTs webhook events to /billing/paypal/webhook (Sitting B).

We don't cache the bearer token between requests — its TTL is ~9h, plenty per request,
and storing it adds failure modes (stale token = 401 retries) that aren't worth the
single network round-trip we'd save.

`PAYPAL_BASE_URL` can point at services.paypal_mock for local dev.
"""
import base64
import json
import logging
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger("mostakhles.paypal")


class PayPalError(RuntimeError):
    """Raised on any non-2xx from PayPal or a missing key in the response body."""


def _base() -> str:
    """Returns the configured PayPal base URL (live, sandbox, or local mock)."""
    return settings.PAYPAL_BASE_URL.rstrip("/")


def _basic_auth() -> str:
    """HTTP Basic auth value for the OAuth token endpoint."""
    raw = f"{settings.PAYPAL_CLIENT_ID}:{settings.PAYPAL_SECRET}"
    return "Basic " + base64.b64encode(raw.encode()).decode()


def _request(method: str, path: str, *, body: dict[str, Any] | None = None,
             auth_bearer: str | None = None, headers: dict[str, str] | None = None,
             timeout: float = 15.0) -> dict[str, Any]:
    """Generic HTTP wrapper. Handles token-endpoint (form-encoded) vs JSON endpoints,
    raises PayPalError on transport failures / 4xx / 5xx."""
    url = f"{_base()}{path}"
    hdrs: dict[str, str] = {"Accept": "application/json"}
    if headers:
        hdrs.update(headers)

    try:
        if auth_bearer:
            hdrs["Authorization"] = f"Bearer {auth_bearer}"
            hdrs.setdefault("Content-Type", "application/json")
            resp = httpx.request(method, url, headers=hdrs, json=body, timeout=timeout)
        elif method == "POST" and path == "/v1/oauth2/token":
            # OAuth client_credentials grant is form-encoded.
            hdrs["Authorization"] = _basic_auth()
            hdrs["Content-Type"] = "application/x-www-form-urlencoded"
            resp = httpx.post(url, headers=hdrs,
                              data={"grant_type": "client_credentials"},
                              timeout=timeout)
        else:
            resp = httpx.request(method, url, headers=hdrs, json=body, timeout=timeout)
    except httpx.HTTPError as exc:
        raise PayPalError(f"PayPal network error on {method} {path}: {exc}") from exc

    if resp.status_code >= 400:
        raise PayPalError(f"PayPal {resp.status_code} on {method} {path}: "
                          f"{resp.text[:400]}")

    if not resp.content:
        return {}
    try:
        return resp.json()
    except json.JSONDecodeError as exc:
        raise PayPalError(f"PayPal returned non-JSON on {method} {path}: "
                          f"{resp.text[:200]}") from exc


def auth_token() -> str:
    """Mint a fresh OAuth bearer. We get a new one per checkout — cheap and
    avoids stale-token edge cases."""
    if not (settings.PAYPAL_CLIENT_ID and settings.PAYPAL_SECRET):
        raise PayPalError("PAYPAL_CLIENT_ID / PAYPAL_SECRET not configured")
    data = _request("POST", "/v1/oauth2/token")
    token = data.get("access_token")
    if not token:
        raise PayPalError(f"auth_token: 'access_token' missing in response: {data}")
    return token


def create_subscription(plan_id: str, *, custom_id: str,
                        return_url: str, cancel_url: str,
                        subscriber_email: str | None = None,
                        brand_name: str = "Mostakhles") -> dict[str, Any]:
    """Create a PayPal subscription against `plan_id` (one of the pre-configured
    plan IDs in PAYPAL_PLAN_ID_LITE/PRO/BUSINESS env vars).

    `custom_id` is OUR opaque reference (we use the mst_v1_<user>_<plan>_<nonce>
    format from Paymob) so we can map the webhook back to a user.

    Returns the full subscription payload. The approval URL the user must visit
    is in result['links'] with rel='approve'."""
    tok = auth_token()
    body: dict[str, Any] = {
        "plan_id": plan_id,
        "custom_id": custom_id,
        "application_context": {
            "brand_name": brand_name,
            "user_action": "SUBSCRIBE_NOW",
            "shipping_preference": "NO_SHIPPING",
            "return_url": return_url,
            "cancel_url": cancel_url,
        },
    }
    if subscriber_email:
        body["subscriber"] = {"email_address": subscriber_email}
    return _request("POST", "/v1/billing/subscriptions",
                    body=body, auth_bearer=tok)


def approval_url(subscription: dict[str, Any]) -> str:
    """Extract the rel='approve' href from a create_subscription response.
    Raises PayPalError if no approve link is found."""
    for link in subscription.get("links") or []:
        if link.get("rel") == "approve":
            href = link.get("href")
            if href:
                return href
    raise PayPalError(f"create_subscription: no 'approve' link in response: "
                      f"{subscription.get('links')}")


def get_subscription(sub_id: str) -> dict[str, Any]:
    """Fetch the current state of a subscription. We call this in /billing/paypal/return
    to confirm status=ACTIVE before flipping user.plan."""
    tok = auth_token()
    return _request("GET", f"/v1/billing/subscriptions/{sub_id}",
                    auth_bearer=tok)


def cancel_subscription(sub_id: str, reason: str = "User requested cancellation") -> None:
    """Cancel a subscription. PayPal returns 204 No Content on success."""
    tok = auth_token()
    _request("POST", f"/v1/billing/subscriptions/{sub_id}/cancel",
             body={"reason": reason[:128]}, auth_bearer=tok)


# ---------------------------------------------------------------------------
# Webhook signature verification.
# PayPal sends 5 headers (Transmission-Id, Transmission-Time, Transmission-Sig,
# Cert-Url, Auth-Algo). We POST them back to PayPal's verify endpoint along
# with our configured webhook_id + the raw event body, and PayPal returns
# {"verification_status": "SUCCESS"|"FAILURE"}.
# ---------------------------------------------------------------------------

# The 5 PayPal headers we need (lowercased for case-insensitive lookup).
_WEBHOOK_HEADER_KEYS = (
    "paypal-transmission-id",
    "paypal-transmission-time",
    "paypal-transmission-sig",
    "paypal-cert-url",
    "paypal-auth-algo",
)


def verify_webhook_signature(headers: dict[str, str],
                             event_body: dict[str, Any]) -> bool:
    """Verify a PayPal webhook by POSTing the headers + body back to PayPal's
    /v1/notifications/verify-webhook-signature endpoint.

    `headers` is the case-insensitive request headers dict (Starlette/FastAPI
    request.headers works directly).  `event_body` is the parsed JSON event.

    Returns False on any failure path (missing webhook_id config, missing
    transmission headers, PayPal returning FAILURE, network error). The caller
    treats False as "drop with 403"."""
    if not settings.PAYPAL_WEBHOOK_ID:
        log.warning("verify_webhook_signature: PAYPAL_WEBHOOK_ID not set; rejecting")
        return False

    # Case-insensitive header lookup. Starlette gives us a Headers object that
    # supports .get() with case-insensitive keys, but dict() coerces to the
    # original case — so normalize manually.
    h = {k.lower(): v for k, v in headers.items()}
    missing = [k for k in _WEBHOOK_HEADER_KEYS if not h.get(k)]
    if missing:
        log.warning("verify_webhook_signature: missing headers %s", missing)
        return False

    body = {
        "transmission_id":   h["paypal-transmission-id"],
        "transmission_time": h["paypal-transmission-time"],
        "transmission_sig":  h["paypal-transmission-sig"],
        "cert_url":          h["paypal-cert-url"],
        "auth_algo":         h["paypal-auth-algo"],
        "webhook_id":        settings.PAYPAL_WEBHOOK_ID,
        "webhook_event":     event_body,
    }
    try:
        tok = auth_token()
        result = _request("POST", "/v1/notifications/verify-webhook-signature",
                          body=body, auth_bearer=tok)
    except PayPalError as exc:
        log.error("verify_webhook_signature: verify call failed: %s", exc)
        return False
    status = (result.get("verification_status") or "").upper()
    if status != "SUCCESS":
        log.warning("verify_webhook_signature: status=%s", status)
        return False
    return True


# ---------------------------------------------------------------------------
# High-level convenience: one call from /billing/paypal/checkout.
# ---------------------------------------------------------------------------

def begin_checkout(plan_id: str, custom_id: str, *,
                   return_url: str, cancel_url: str,
                   subscriber_email: str | None = None) -> tuple[str, str]:
    """End-to-end: create subscription, return (approval_url, subscription_id).
    Caller persists nothing yet — we wait for the user to actually approve at
    PayPal, then /billing/paypal/return confirms ACTIVE before upgrading."""
    sub = create_subscription(plan_id, custom_id=custom_id,
                              return_url=return_url, cancel_url=cancel_url,
                              subscriber_email=subscriber_email)
    sub_id = sub.get("id")
    if not sub_id:
        raise PayPalError(f"create_subscription: 'id' missing in response: {sub}")
    return approval_url(sub), sub_id
