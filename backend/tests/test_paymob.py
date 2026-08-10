"""Paymob billing tests — dual-currency (USD/EGP) checkout + callback handling.

Hermetic: runs against the app in-process (TestClient) on a throwaway SQLite DB
with stubbed Paymob config (see conftest). Checkout tests stub the outbound
Paymob call; callback tests POST directly-signed webhooks (no network).
"""
import hashlib
import hmac
import itertools

import pytest

from app import db, models
from app.config import settings
from app.main import (_mint_merchant_order_id, _paymob_amount,
                      _paymob_currencies)
from app.services import paymob as P
from app.services.paymob import _HMAC_FIELDS, _flatten
from app.services.plans import get_plan
from tests.conftest import PAYMOB_HMAC

_txn = itertools.count(700001)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def sign(obj: dict, secret: str = PAYMOB_HMAC) -> str:
    payload = "".join(_flatten(obj, k) for k in _HMAC_FIELDS)
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha512).hexdigest()


def make_obj(amount_cents: int, currency: str, success: bool, mid: str,
             txn_id: int | None = None) -> dict:
    txn_id = txn_id if txn_id is not None else next(_txn)
    return {
        "id": txn_id, "amount_cents": amount_cents, "created_at": "1700000000",
        "currency": currency, "error_occured": not success,
        "has_parent_transaction": False,
        "integration_id": 1111 if currency == "USD" else 2222, "is_3d_secure": True,
        "is_auth": False, "is_capture": False, "is_refunded": False,
        "is_standalone_payment": True, "is_voided": False, "owner": 0,
        "pending": False, "success": success,
        "order": {"id": txn_id + 1, "merchant_order_id": mid},
        "source_data": {"pan": "1234", "sub_type": "MasterCard", "type": "card"},
    }


def post_callback(client, obj, hmac_override=None):
    sig = hmac_override or sign(obj)
    return client.post(f"/billing/paymob/callback?hmac={sig}",
                       json={"type": "TRANSACTION", "obj": obj})


def event_row(uid, external_id=None):
    s = db.SessionLocal()
    try:
        q = s.query(models.PaymentEvent).filter_by(user_id=uid, provider="paymob")
        if external_id:
            q = q.filter_by(external_id=external_id)
        e = q.order_by(models.PaymentEvent.id.desc()).first()
        if e is None:
            return None
        return {"event_type": e.event_type, "amount_usd": e.amount_usd,
                "external_id": e.external_id, "raw": e.raw_payload or ""}
    finally:
        s.close()


def user_state(uid):
    s = db.SessionLocal()
    try:
        u = s.query(models.User).filter_by(id=uid).first()
        active = [x.plan for x in s.query(models.Subscription)
                  .filter_by(user_id=uid, status="active").all()]
        cancelled = s.query(models.Subscription).filter_by(
            user_id=uid, status="cancelled").count()
        events = s.query(models.PaymentEvent).filter_by(user_id=uid).count()
        return {"plan": u.plan, "active": active, "cancelled": cancelled, "events": events}
    finally:
        s.close()


# --------------------------------------------------------------------------
# unit — currency resolution
# --------------------------------------------------------------------------
class TestCurrencyResolution:
    def test_offered_currencies(self):
        assert _paymob_currencies() == ["USD", "EGP"]

    def test_amounts(self):
        starter = get_plan("starter")           # $29
        assert _paymob_amount(starter, "USD") == 29
        assert _paymob_amount(starter, "EGP") == 29 * settings.EGP_PER_USD

    def test_per_currency_integration_ids(self):
        assert P.integration_id_for("USD") == "1111"
        assert P.integration_id_for("EGP") == "2222"

    def test_unknown_currency_falls_back_to_legacy(self):
        assert P.integration_id_for("GBP") == "legacy0"

    def test_empty_per_currency_falls_back_to_legacy(self, monkeypatch):
        monkeypatch.setattr(settings, "PAYMOB_INTEGRATION_ID_EGP", "")
        assert P.integration_id_for("EGP") == "legacy0"


# --------------------------------------------------------------------------
# checkout endpoint — currency routing + guards (outbound Paymob call stubbed)
# --------------------------------------------------------------------------
class TestCheckoutEndpoint:
    @pytest.fixture
    def capture_begin(self, monkeypatch):
        calls = {}

        def fake_begin(amount, merchant_order_id, billing, currency="EGP"):
            calls.update(amount=amount, currency=currency, mid=merchant_order_id)
            return ("http://mock/iframe?token=x", 12345)

        monkeypatch.setattr(P, "begin_checkout", fake_begin)
        return calls

    def _checkout(self, client, u, currency):
        client.cookies.set("sid", u.sid)
        try:
            return client.post("/billing/paymob/checkout",
                               data={"plan": "starter", "currency": currency,
                                     "csrf_token": u.csrf},
                               follow_redirects=False)
        finally:
            client.cookies.clear()

    def test_usd_charges_native_usd(self, client, user_factory, capture_begin):
        u = user_factory()
        r = self._checkout(client, u, "USD")
        assert r.status_code == 303
        assert capture_begin == {"amount": 29, "currency": "USD",
                                 "mid": capture_begin["mid"]}

    def test_egp_charges_derived_egp(self, client, user_factory, capture_begin):
        u = user_factory()
        r = self._checkout(client, u, "EGP")
        assert r.status_code == 303
        assert capture_begin["currency"] == "EGP"
        assert capture_begin["amount"] == 29 * settings.EGP_PER_USD

    def test_invalid_currency_defaults_to_first(self, client, user_factory, capture_begin):
        u = user_factory()
        self._checkout(client, u, "XYZ")
        assert capture_begin["currency"] == "USD"

    def test_picker_requires_auth(self, client):
        r = client.get("/billing/checkout?plan=starter", follow_redirects=False)
        assert r.status_code == 303 and "/login" in r.headers.get("location", "")

    def test_bad_csrf_rejected(self, client, user_factory, capture_begin):
        u = user_factory()
        client.cookies.set("sid", u.sid)
        try:
            r = client.post("/billing/paymob/checkout",
                            data={"plan": "starter", "currency": "USD", "csrf_token": "WRONG"},
                            follow_redirects=False)
        finally:
            client.cookies.clear()
        assert r.status_code == 403
        assert capture_begin == {}   # never reached the Paymob call

    def test_picker_shows_both_currencies(self, client, user_factory):
        u = user_factory()
        client.cookies.set("sid", u.sid)
        try:
            r = client.get("/billing/checkout?plan=starter")
        finally:
            client.cookies.clear()
        assert r.status_code == 200
        assert 'value="USD"' in r.text and 'value="EGP"' in r.text
        assert "$29.00" in r.text and "1,450" in r.text


# --------------------------------------------------------------------------
# callback — grant / idempotency / decline / tamper / normalization / switch
# --------------------------------------------------------------------------
class TestCallback:
    def test_success_usd_grants_subscription(self, client, user_factory):
        u = user_factory()
        mid = _mint_merchant_order_id(u.uid, "starter")
        r = post_callback(client, make_obj(2900, "USD", True, mid))
        assert r.status_code == 200 and r.json()["upgraded"]
        st = user_state(u.uid)
        assert st["plan"] == "starter" and st["active"] == ["starter"]
        assert event_row(u.uid)["amount_usd"] == 29.00

    def test_idempotent_replay_no_double_grant(self, client, user_factory):
        u = user_factory()
        mid = _mint_merchant_order_id(u.uid, "starter")
        obj = make_obj(2900, "USD", True, mid)
        post_callback(client, obj)
        before = user_state(u.uid)
        r2 = post_callback(client, obj)               # same txn id
        assert r2.json().get("duplicate") is True
        after = user_state(u.uid)
        assert after["events"] == before["events"] and after["active"] == ["starter"]

    def test_egp_success_normalizes_to_usd(self, client, user_factory):
        u = user_factory()
        mid = _mint_merchant_order_id(u.uid, "starter")
        r = post_callback(client, make_obj(145000, "EGP", True, mid))   # 1450 EGP
        assert r.json()["upgraded"]
        assert event_row(u.uid)["amount_usd"] == 29.00

    def test_decline_does_not_grant(self, client, user_factory):
        u = user_factory()
        mid = _mint_merchant_order_id(u.uid, "pro")
        r = post_callback(client, make_obj(5900, "USD", False, mid))
        assert r.status_code == 200 and not r.json()["upgraded"]
        st = user_state(u.uid)
        assert st["plan"] == "free" and st["active"] == []

    def test_failed_event_is_attributed_to_user(self, client, user_factory):
        """Regression: failed transactions must carry user_id (was NULL)."""
        u = user_factory()
        mid = _mint_merchant_order_id(u.uid, "pro")
        obj = make_obj(5900, "USD", False, mid)
        post_callback(client, obj)
        row = event_row(u.uid, external_id=str(obj["id"]))
        assert row is not None and row["event_type"] == "paymob.transaction.failed"

    def test_hmac_tamper_rejected_and_not_persisted(self, client, user_factory):
        u = user_factory()
        mid = _mint_merchant_order_id(u.uid, "starter")
        obj = make_obj(2900, "USD", True, mid)
        r = post_callback(client, obj, hmac_override="deadbeef")
        assert r.status_code == 403
        s = db.SessionLocal()
        try:
            assert s.query(models.PaymentEvent).filter_by(
                external_id=str(obj["id"])).count() == 0
        finally:
            s.close()

    def test_foreign_merchant_order_id_no_grant(self, client, user_factory):
        u = user_factory()
        r = post_callback(client, make_obj(2900, "USD", True, "paymob_test_xyz"))
        assert r.status_code == 200 and not r.json()["upgraded"]

    def test_plan_switch_cancels_prior(self, client, user_factory):
        u = user_factory()
        post_callback(client, make_obj(2900, "USD", True,
                                       _mint_merchant_order_id(u.uid, "starter")))
        post_callback(client, make_obj(5900, "USD", True,
                                       _mint_merchant_order_id(u.uid, "pro")))
        st = user_state(u.uid)
        assert st["plan"] == "pro"
        assert st["active"] == ["pro"] and st["cancelled"] >= 1
