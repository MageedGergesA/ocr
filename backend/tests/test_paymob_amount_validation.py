"""P0.9 — Paymob callback defense-in-depth: grant is tied to the SIGNED amount.

Regression for the discovery finding: the (user, plan) mapping comes from
merchant_order_id, which is NOT in Paymob's signed HMAC field set — only amount
and currency are. A validly-signed callback whose merchant_order_id was swapped to
a higher plan could otherwise grant that plan without paying for it. The callback
now rejects the grant unless the paid amount matches the decoded plan's price.

Reuses the signing helpers from test_paymob (a correctly-signed body — the point
is that even WITH a valid signature, a wrong amount does not grant).
"""
from app import db, models
from app.main import _mint_merchant_order_id
from app.services.plans import get_plan
from tests.test_paymob import make_obj, post_callback


def _plan(uid):
    s = db.SessionLocal()
    try:
        return s.get(models.User, uid).plan
    finally:
        s.close()


def _cleanup(uid):
    s = db.SessionLocal()
    try:
        s.query(models.PaymentEvent).filter_by(user_id=uid).delete()
        s.query(models.Subscription).filter_by(user_id=uid).delete()
        s.commit()
    finally:
        s.close()


def test_correct_usd_amount_grants(client, user_factory):
    u = user_factory()
    mid = _mint_merchant_order_id(u.uid, "starter")
    cents = int(get_plan("starter").usd * 100)          # $29 -> 2900
    try:
        r = post_callback(client, make_obj(cents, "USD", True, mid))
        assert r.status_code == 200 and r.json()["upgraded"] is True
        assert _plan(u.uid) == "starter"
    finally:
        _cleanup(u.uid)


def test_correct_egp_amount_grants(client, user_factory):
    u = user_factory()
    mid = _mint_merchant_order_id(u.uid, "starter")
    # EGP price = usd * EGP_PER_USD (conftest pins EGP_PER_USD=50) -> 29*50=1450.00
    cents = int(round(get_plan("starter").usd * 50 * 100))
    try:
        r = post_callback(client, make_obj(cents, "EGP", True, mid))
        assert r.status_code == 200 and r.json()["upgraded"] is True
        assert _plan(u.uid) == "starter"
    finally:
        _cleanup(u.uid)


def test_swapped_plan_with_underpayment_is_not_granted(client, user_factory):
    """THE attack: merchant_order_id claims 'business' ($199) but only the starter
    amount ($29) was paid. Valid signature, but the amount doesn't match the plan —
    no grant; plan stays free. The event is still recorded for audit."""
    u = user_factory()
    mid = _mint_merchant_order_id(u.uid, "business")     # claims the expensive plan
    starter_cents = int(get_plan("starter").usd * 100)   # but paid the cheap price
    try:
        r = post_callback(client, make_obj(starter_cents, "USD", True, mid))
        assert r.status_code == 200
        assert r.json()["upgraded"] is False             # grant rejected
        assert _plan(u.uid) == "free"                    # plan unchanged
        # The (failed-to-grant) event is still logged for support/fraud review.
        s = db.SessionLocal()
        try:
            assert s.query(models.PaymentEvent).filter_by(user_id=u.uid).count() == 1
            assert s.query(models.Subscription).filter_by(user_id=u.uid).count() == 0
        finally:
            s.close()
    finally:
        _cleanup(u.uid)


def test_wrong_currency_amount_is_not_granted(client, user_factory):
    """A USD-priced amount (2900) echoed as EGP would be ~1/50th of the EGP price
    for the plan — mismatch, so no grant."""
    u = user_factory()
    mid = _mint_merchant_order_id(u.uid, "starter")
    try:
        r = post_callback(client, make_obj(2900, "EGP", True, mid))  # 29 EGP, not 1450
        assert r.status_code == 200 and r.json()["upgraded"] is False
        assert _plan(u.uid) == "free"
    finally:
        _cleanup(u.uid)
