"""Local Paymob mock — drop-in replacement for the real Accept API.

Mounted at /_mock/paymob when ENV=local so we can wire the full checkout flow
without a Paymob merchant account. The mock:

* Accepts the same 3 endpoints (/api/auth/tokens, /api/ecommerce/orders,
  /api/acceptance/payment_keys) and returns realistic shapes.
* Serves a fake iframe at /api/acceptance/iframes/{IFRAME_ID} with a single
  "Pay now" button that POSTs a signed callback to /billing/paymob/callback
  using PAYMOB_HMAC so the webhook handler accepts it as authentic.
* Stores in-memory state so the iframe can look up the order's amount + the
  merchant_order_id we need to map the payment back to a user.

Set PAYMOB_BASE_URL=http://localhost:8000/_mock/paymob and the rest of the code
(services.paymob) treats it as Paymob.
"""
import hashlib
import hmac
import secrets
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import settings
from app.services.paymob import _HMAC_FIELDS

router = APIRouter(prefix="/_mock/paymob", tags=["mock-paymob"])

# In-memory store. Process-local — that's fine, this only runs in dev.
_ORDERS: dict[int, dict[str, Any]] = {}
_PAY_TOKENS: dict[str, int] = {}  # token -> order_id


@router.post("/api/auth/tokens")
def mock_auth():
    return {"token": f"mock_auth_{secrets.token_hex(8)}"}


@router.post("/api/ecommerce/orders")
async def mock_order(request: Request):
    body = await request.json()
    order_id = int(time.time() * 1000) % 1_000_000_000  # numeric, deterministic-ish
    _ORDERS[order_id] = {
        "id": order_id,
        "amount_cents": int(body.get("amount_cents", 0)),
        "currency": body.get("currency", "EGP"),
        "merchant_order_id": body.get("merchant_order_id", ""),
    }
    return {"id": order_id, "amount_cents": body.get("amount_cents"),
            "currency": body.get("currency", "EGP")}


@router.post("/api/acceptance/payment_keys")
async def mock_payment_key(request: Request):
    body = await request.json()
    order_id = int(body["order_id"])
    if order_id not in _ORDERS:
        raise HTTPException(status_code=404, detail="order not found")
    token = f"mock_pk_{secrets.token_hex(12)}"
    _PAY_TOKENS[token] = order_id
    _ORDERS[order_id]["integration_id"] = body.get("integration_id", 0)
    return {"token": token}


@router.get("/api/acceptance/iframes/{iframe_id}", response_class=HTMLResponse)
def mock_iframe(iframe_id: str, payment_token: str = ""):
    """The fake checkout page. Two buttons: 'Pay' fires a signed success
    callback; 'Decline' fires a signed failure callback. Wired to the same
    /billing/paymob/callback endpoint the real Paymob would hit."""
    order_id = _PAY_TOKENS.get(payment_token)
    if not order_id:
        return HTMLResponse("<h1>Mock Paymob: invalid payment token</h1>", status_code=400)
    order = _ORDERS[order_id]
    amount_egp = order["amount_cents"] / 100
    mref = order.get("merchant_order_id", "")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Mock Paymob checkout</title>
<style>
body{{font:16px system-ui,-apple-system,sans-serif;background:#f3f4f6;margin:0;padding:60px 20px;display:flex;justify-content:center}}
.card{{background:white;max-width:520px;width:100%;border-radius:14px;padding:28px;box-shadow:0 4px 20px rgba(0,0,0,.08)}}
h1{{margin:0 0 6px;font-size:22px}} .muted{{color:#666;font-size:14px}}
.row{{display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid #eee}}
.amount{{font-size:32px;font-weight:800;margin:18px 0;color:#111}}
.btns{{display:flex;gap:10px;margin-top:22px}}
button{{flex:1;padding:14px;border:none;border-radius:10px;font:600 15px inherit;cursor:pointer}}
.pay{{background:#16a34a;color:white}} .pay:hover{{background:#15803d}}
.decline{{background:#dc2626;color:white}} .decline:hover{{background:#b91c1c}}
.warn{{margin-top:18px;font-size:12px;color:#a16207;background:#fef9c3;padding:10px;border-radius:8px}}
</style></head><body>
<div class="card">
  <h1>Mock Paymob Checkout</h1>
  <p class="muted">Local development only — no real money is moved.</p>
  <div class="amount">{amount_egp:,.2f} EGP</div>
  <div class="row"><span class="muted">Order ID</span><b>{order_id}</b></div>
  <div class="row"><span class="muted">Merchant ref</span><b>{mref}</b></div>
  <div class="row"><span class="muted">Iframe ID</span><b>{iframe_id}</b></div>
  <div class="btns">
    <button class="pay" onclick="callback(true)">Pay {amount_egp:,.0f} EGP</button>
    <button class="decline" onclick="callback(false)">Decline</button>
  </div>
  <div class="warn">This page only exists when ENV=local. Set PAYMOB_BASE_URL to swap to real Paymob.</div>
</div>
<script>
async function callback(success) {{
  const r = await fetch('/_mock/paymob/fire-callback', {{
    method: 'POST',
    headers: {{'content-type':'application/json'}},
    body: JSON.stringify({{order_id: {order_id}, success}})
  }});
  const data = await r.json();
  if (data.redirect) location.href = data.redirect;
  else document.body.innerHTML = '<div class="card"><h1>Callback fired</h1><pre>'+JSON.stringify(data,null,2)+'</pre></div>';
}}
</script>
</body></html>"""


@router.post("/fire-callback")
async def fire_callback(request: Request):
    """Server-side helper: build the real Paymob-shaped callback payload, sign
    it with PAYMOB_HMAC, and POST it to /billing/paymob/callback. Returns the
    redirect URL the iframe should navigate to."""
    import httpx as _httpx
    body = await request.json()
    order_id = int(body["order_id"])
    success = bool(body.get("success", True))
    order = _ORDERS.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="order not found")

    # Build the Paymob "Transaction Processed" obj. The fields here are exactly
    # the ones in services.paymob._HMAC_FIELDS so the HMAC matches.
    txn_id = int(time.time() * 1000) % 1_000_000
    obj = {
        "id": txn_id,
        "amount_cents": order["amount_cents"],
        "created_at": str(int(time.time())),
        "currency": order["currency"],
        "error_occured": not success,
        "has_parent_transaction": False,
        "integration_id": order.get("integration_id", 0),
        "is_3d_secure": True,
        "is_auth": False,
        "is_capture": False,
        "is_refunded": False,
        "is_standalone_payment": True,
        "is_voided": False,
        "owner": 0,
        "pending": False,
        "success": success,
        "order": {"id": order_id, "merchant_order_id": order.get("merchant_order_id", "")},
        "source_data": {"pan": "1234", "sub_type": "MasterCard", "type": "card"},
    }
    payload_str = "".join(_walk(obj, k) for k in _HMAC_FIELDS)
    sig = hmac.new(settings.PAYMOB_HMAC.encode(), payload_str.encode(),
                   hashlib.sha512).hexdigest()

    # Hit our own callback endpoint. Use the request's base URL so this works
    # whether we're on localhost or a deployed dev environment.
    # ASYNC httpx — this handler is `async def` and the callback URL routes
    # back into the SAME uvicorn process, so a sync `httpx.post` here would
    # deadlock the event loop (blocked waiting for a response it must serve).
    base = str(request.base_url).rstrip("/")
    callback_url = f"{base}/billing/paymob/callback?hmac={sig}"
    try:
        async with _httpx.AsyncClient(timeout=10) as client:
            await client.post(callback_url, json={"type": "TRANSACTION", "obj": obj})
    except _httpx.HTTPError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)

    redirect = "/dashboard?paid=1" if success else "/?paid=cancelled"
    return {"ok": True, "redirect": redirect}


def _walk(obj: dict, key: str) -> str:
    """Same as paymob._flatten but local to avoid the import cycle."""
    cur: Any = obj
    for part in key.split("."):
        if not isinstance(cur, dict):
            return ""
        cur = cur.get(part)
        if cur is None:
            return ""
    if isinstance(cur, bool):
        return "true" if cur else "false"
    return str(cur)
