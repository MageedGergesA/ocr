"""Phase-1 preflight — PayPal callback plan defense-in-depth (deferred Phase-0 item).

Same spirit as the Paymob amount check: the plan we grant comes from our custom_id,
so verify it matches the ACTUAL PayPal plan_id on the subscription. Mismatch → no
grant. PayPal's get_subscription is stubbed (no live PayPal / keys needed); the
point is the server-side consistency gate, not the network call.
"""
from app import db, main as m, models


def _plan(uid):
    s = db.SessionLocal()
    try:
        return s.get(models.User, uid).plan
    finally:
        s.close()


def _subs(uid):
    s = db.SessionLocal()
    try:
        return s.query(models.Subscription).filter_by(user_id=uid).count()
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


def test_paypal_return_rejects_plan_mismatch(client, user_factory, monkeypatch):
    u = user_factory()
    cid = m._mint_merchant_order_id(u.uid, "starter")
    monkeypatch.setattr(m.plans, "paypal_plan_id", lambda slug: "P-EXPECTED")
    monkeypatch.setattr(m._paypal, "get_subscription", lambda sid: {
        "status": "ACTIVE", "custom_id": cid, "plan_id": "P-DIFFERENT"})
    try:
        r = client.get("/billing/paypal/return?subscription_id=I-mismatch",
                       follow_redirects=False)
        assert r.status_code == 303
        assert "plan_mismatch" in r.headers.get("location", "")
        assert _plan(u.uid) == "free" and _subs(u.uid) == 0    # no grant
    finally:
        _cleanup(u.uid)


def test_paypal_return_grants_on_plan_match(client, user_factory, monkeypatch):
    u = user_factory()
    cid = m._mint_merchant_order_id(u.uid, "starter")
    monkeypatch.setattr(m.plans, "paypal_plan_id", lambda slug: "P-OK")
    monkeypatch.setattr(m._paypal, "get_subscription", lambda sid: {
        "status": "ACTIVE", "custom_id": cid, "plan_id": "P-OK"})
    try:
        r = client.get("/billing/paypal/return?subscription_id=I-ok",
                       follow_redirects=False)
        assert r.status_code == 303
        assert "billing/success" in r.headers.get("location", "")
        assert _plan(u.uid) == "starter" and _subs(u.uid) == 1
    finally:
        _cleanup(u.uid)
