"""Local PayPal mock — drop-in replacement for the Subscriptions API.

Mounted at /_mock/paypal when ENV=local so /billing/paypal/checkout works
without real PayPal merchant credentials. The mock:

* Accepts the same endpoints (/v1/oauth2/token, /v1/billing/subscriptions/...).
* Serves a fake approval page at /_mock/paypal/approve/{sub_id} with two
  buttons: "Approve" sends the user to the return_url with subscription_id,
  "Cancel" sends them to the cancel_url.
* Stores in-memory subscription state so /v1/billing/subscriptions/{id}
  returns the correct status when the return flow checks it.

Set PAYPAL_BASE_URL=http://localhost:8000/_mock/paypal and services.paypal
will treat it as PayPal.
"""
import secrets
import time
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

router = APIRouter(prefix="/_mock/paypal", tags=["mock-paypal"])

# In-memory store. Process-local — dev only.
# Maps sub_id -> {plan_id, custom_id, status, return_url, cancel_url, ...}
_SUBSCRIPTIONS: dict[str, dict[str, Any]] = {}


@router.post("/v1/oauth2/token")
def mock_oauth_token():
    """Mocks the client_credentials grant. Always returns a fresh fake token."""
    return {
        "access_token": f"mock_pp_{secrets.token_hex(16)}",
        "token_type": "Bearer",
        "expires_in": 32400,  # 9 hours — matches real PayPal
        "app_id": "APP-MOCK0000000000",
        "scope": "https://api-m.sandbox.paypal.com/v1/billing/subscriptions",
    }


@router.post("/v1/billing/subscriptions")
async def mock_create_subscription(request: Request):
    """Mock subscription creation. Stores state, returns an approve link
    that points back at our mock approval page."""
    body = await request.json()
    plan_id = body.get("plan_id", "P-MOCK")
    custom_id = body.get("custom_id", "")
    app_ctx = body.get("application_context", {}) or {}
    return_url = app_ctx.get("return_url", "/")
    cancel_url = app_ctx.get("cancel_url", "/")

    sub_id = f"I-MOCK{secrets.token_hex(6).upper()}"
    _SUBSCRIPTIONS[sub_id] = {
        "id": sub_id,
        "plan_id": plan_id,
        "custom_id": custom_id,
        "status": "APPROVAL_PENDING",
        "return_url": return_url,
        "cancel_url": cancel_url,
        "create_time": int(time.time()),
    }

    base = str(request.base_url).rstrip("/")
    approve_url = f"{base}/_mock/paypal/approve/{sub_id}"
    return {
        "id": sub_id,
        "status": "APPROVAL_PENDING",
        "create_time": _SUBSCRIPTIONS[sub_id]["create_time"],
        "links": [
            {"href": approve_url, "rel": "approve", "method": "GET"},
            {"href": f"{base}/_mock/paypal/v1/billing/subscriptions/{sub_id}",
             "rel": "self", "method": "GET"},
        ],
    }


@router.get("/v1/billing/subscriptions/{sub_id}")
def mock_get_subscription(sub_id: str):
    """Returns the current state of a stored subscription."""
    sub = _SUBSCRIPTIONS.get(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="subscription not found")
    return {
        "id": sub_id,
        "plan_id": sub["plan_id"],
        "custom_id": sub["custom_id"],
        "status": sub["status"],
        "create_time": sub["create_time"],
        "start_time": sub.get("start_time"),
    }


@router.post("/v1/billing/subscriptions/{sub_id}/cancel")
async def mock_cancel_subscription(sub_id: str):
    """Marks the subscription as CANCELLED. Returns 204 like real PayPal."""
    sub = _SUBSCRIPTIONS.get(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="subscription not found")
    sub["status"] = "CANCELLED"
    sub["cancel_time"] = int(time.time())
    return JSONResponse(content=None, status_code=204)


@router.get("/approve/{sub_id}", response_class=HTMLResponse)
def mock_approval_page(sub_id: str):
    """The fake PayPal approval UI. User clicks Approve or Cancel."""
    sub = _SUBSCRIPTIONS.get(sub_id)
    if not sub:
        return HTMLResponse(
            "<h1>Mock PayPal: subscription not found</h1>",
            status_code=404)

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Mock PayPal approval</title>
<style>
body{{font:16px system-ui,-apple-system,sans-serif;background:#003087;margin:0;padding:48px 20px;min-height:100vh;box-sizing:border-box;display:flex;justify-content:center;align-items:flex-start;color:#fff}}
.card{{background:white;color:#222;max-width:560px;width:100%;border-radius:14px;padding:32px;box-shadow:0 12px 40px rgba(0,0,0,.30)}}
.brand{{display:flex;align-items:center;gap:10px;margin-bottom:18px}}
.brand b{{font-size:22px;color:#003087;letter-spacing:-.02em}}
.brand i{{font-size:22px;color:#009cde;letter-spacing:-.02em;font-style:italic}}
h1{{margin:0 0 8px;font-size:20px}} .muted{{color:#666;font-size:14px}}
.row{{display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid #eee;font-size:14px}}
.row b{{font-family:ui-monospace,Menlo,monospace}}
.btns{{display:flex;gap:10px;margin-top:24px}}
a.btn{{flex:1;padding:14px;border-radius:10px;font:600 15px inherit;text-align:center;text-decoration:none}}
a.approve{{background:#0070ba;color:white}} a.approve:hover{{background:#003087}}
a.cancel{{background:#f5f5f5;color:#222;border:1px solid #ddd}} a.cancel:hover{{background:#eee}}
.warn{{margin-top:18px;font-size:12px;color:#a16207;background:#fef9c3;padding:10px;border-radius:8px}}
</style></head><body>
<div class="card">
  <div class="brand"><b>Pay</b><i>Pal</i></div>
  <h1>Confirm your subscription</h1>
  <p class="muted">You're about to authorize a recurring billing agreement.</p>
  <div class="row"><span class="muted">Subscription</span><b>{sub_id}</b></div>
  <div class="row"><span class="muted">Plan</span><b>{sub["plan_id"]}</b></div>
  <div class="row"><span class="muted">Reference</span><b>{sub["custom_id"]}</b></div>
  <div class="btns">
    <a class="btn approve"
       href="/_mock/paypal/approve/{sub_id}/fire?approved=1">Approve and subscribe</a>
    <a class="btn cancel"
       href="/_mock/paypal/approve/{sub_id}/fire?approved=0">Cancel</a>
  </div>
  <div class="warn">This page only exists when ENV=local. Set PAYPAL_BASE_URL to swap to real PayPal.</div>
</div>
</body></html>"""


@router.get("/approve/{sub_id}/fire")
async def mock_approval_fire(sub_id: str, request: Request, approved: int = 0):
    """User clicked Approve or Cancel — flip the status, fire a webhook (so
    Sitting PP-B handler runs locally too), then redirect to return_url /
    cancel_url with subscription_id appended."""
    sub = _SUBSCRIPTIONS.get(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="subscription not found")

    import httpx as _httpx

    base = str(request.base_url).rstrip("/")
    if approved:
        sub["status"] = "ACTIVE"
        sub["start_time"] = int(time.time())
        event_type = "BILLING.SUBSCRIPTION.ACTIVATED"
        sep = "&" if "?" in sub["return_url"] else "?"
        target = (f"{sub['return_url']}{sep}"
                  f"subscription_id={quote(sub_id)}&token=MOCK_APPROVE")
    else:
        sub["status"] = "CANCELLED"
        sub["cancel_time"] = int(time.time())
        event_type = "BILLING.SUBSCRIPTION.CANCELLED"
        sep = "&" if "?" in sub["cancel_url"] else "?"
        target = (f"{sub['cancel_url']}{sep}"
                  f"subscription_id={quote(sub_id)}")

    # Fire a webhook to ourselves to exercise the PP-B handler.
    # Use the same headers the real PayPal sends; the mock's verify endpoint
    # accepts any of them and always returns SUCCESS.
    event_id = f"WH-MOCK-{secrets.token_hex(8).upper()}"
    event_body = {
        "id": event_id,
        "event_type": event_type,
        "create_time": f"{time.time():.6f}",
        "resource_type": "subscription",
        "resource": {
            "id": sub_id,
            "plan_id": sub.get("plan_id", ""),
            "custom_id": sub.get("custom_id", ""),
            "status": sub["status"],
        },
    }
    headers = {
        "PayPal-Transmission-Id":   event_id,
        "PayPal-Transmission-Time": f"{time.time():.6f}",
        "PayPal-Transmission-Sig":  "mock-signature",
        "PayPal-Cert-Url":          f"{base}/_mock/paypal/cert.pem",
        "PayPal-Auth-Algo":         "SHA256withRSA",
        "Content-Type":             "application/json",
    }
    try:
        async with _httpx.AsyncClient(timeout=8) as client:
            await client.post(f"{base}/billing/paypal/webhook",
                              json=event_body, headers=headers)
    except _httpx.HTTPError:
        # Webhook delivery failure shouldn't block the user's redirect — they
        # already approved at PayPal. The return_url flow has its own path.
        pass

    return RedirectResponse(target, status_code=303)


@router.post("/v1/notifications/verify-webhook-signature")
def mock_verify_webhook():
    """Mock the verify-webhook-signature endpoint. Always returns SUCCESS so
    the local /billing/paypal/webhook handler treats mock-fired events as
    legitimate. The real PayPal endpoint validates 5 headers against a cert
    chain — we trust everything in local dev."""
    return {"verification_status": "SUCCESS"}
