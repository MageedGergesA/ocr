"""P0.5 — account deletion is complete, FK-safe, and all-or-nothing.

Regression for the discovery finding: the delete sweep omitted WorkflowRule,
Approval and AuditLog (no ondelete cascade), so on a FK-enforcing DB the delete
raised an IntegrityError and rolled back (account NOT deleted); on lax SQLite it
orphaned rows. Runs with SQLite foreign-key enforcement ON (see conftest).

Proves: with rows in every user-owned table, deletion succeeds, leaves NO
user-owned rows behind, and RETAINS financial records (Subscription, PaymentEvent)
in anonymized form (user_id NULL, raw_payload redacted) for accounting.
"""
from app import auth, db, models


def _seed_everything(uid):
    """One row in each user-owned table, created parents-before-children so it is
    valid even with FK enforcement on."""
    s = db.SessionLocal()
    try:
        key, _raw = models.new_api_key(uid)
        s.add(key); s.commit(); s.refresh(key)
        s.add(models.Usage(api_key_id=key.id, period=auth.current_period(), count=3))

        h = models.History(user_id=uid, kind="auto", document_type="invoice",
                           charged=1, result_json={"x": 1})
        s.add(h); s.commit(); s.refresh(h)
        s.add(models.ExtractionVersion(history_id=h.id, user_id=uid, version=1,
                                       source="extracted"))
        s.add(models.DocumentEvent(history_id=h.id, user_id=uid, stage="exported"))

        rule = models.WorkflowRule(user_id=uid, name="r", field="total", op="gt",
                                   value="100", action="require_approval", active=True)
        s.add(rule); s.commit(); s.refresh(rule)
        appr = models.Approval(user_id=uid, history_id=h.id, rule_id=rule.id,
                               rule_name="r", status="pending")
        s.add(appr); s.commit(); s.refresh(appr)
        s.add(models.AuditLog(user_id=uid, approval_id=appr.id, event="rule_matched",
                              detail="x"))

        s.add(models.CorrectionMemory(user_id=uid, document_type="invoice",
                                      field_key="vendor", corrected_value="Acme", count=1))
        s.add(models.OpsEvent(user_id=uid, kind="auto", status="ok"))
        s.add(models.IdempotencyKey(user_id=uid, key="k1", response_json={"a": 1}))
        s.add(models.WebhookDelivery(user_id=uid, target_url="https://x.example",
                                     event_kind="job.completed", payload="{}",
                                     status="delivered", attempt_count=1))

        sub = models.Subscription(user_id=uid, provider="paymob", external_id="sub_del_1",
                                  plan="starter", status="active", amount_usd=29)
        s.add(sub); s.commit(); s.refresh(sub)
        s.add(models.PaymentEvent(provider="paymob", external_id="evt_del_1",
                                  event_type="paid", user_id=uid, amount_usd=29,
                                  raw_payload='{"billing_name":"Jane Doe"}'))
        s.commit()
    finally:
        s.close()


def _count(model, **filt):
    s = db.SessionLocal()
    try:
        return s.query(model).filter_by(**filt).count()
    finally:
        s.close()


def test_account_deletion_is_complete_and_retains_anonymized_financials(client, user_factory):
    u = user_factory()
    # Verify + set a known password so /account/delete accepts it.
    s = db.SessionLocal()
    try:
        usr = s.get(models.User, u.uid)
        usr.email_verified = True
        usr.password_hash = auth.hash_password("secretpw")
        s.commit()
    finally:
        s.close()
    _seed_everything(u.uid)

    client.cookies.set("sid", u.sid)
    try:
        r = client.post("/account/delete",
                        data={"current_password": "secretpw", "confirm": "DELETE",
                              "csrf_token": u.csrf},
                        follow_redirects=False)
    finally:
        client.cookies.clear()

    assert r.status_code == 303, r.text  # success redirect, not a 500 error page

    # The user and ALL non-financial owned rows are gone.
    assert _count(models.User, id=u.uid) == 0
    for model in (models.ApiKey, models.Session, models.Template, models.History,
                  models.ExtractionVersion, models.DocumentEvent, models.Approval,
                  models.WorkflowRule, models.AuditLog, models.CorrectionMemory,
                  models.OpsEvent, models.IdempotencyKey, models.WebhookDelivery):
        assert _count(model, user_id=u.uid) == 0, f"{model.__name__} not deleted"

    # Financial records are RETAINED but anonymized (detached + PII redacted).
    s = db.SessionLocal()
    try:
        sub = s.query(models.Subscription).filter_by(external_id="sub_del_1").first()
        assert sub is not None and sub.user_id is None
        assert sub.amount_usd is not None  # accounting data kept
        ev = s.query(models.PaymentEvent).filter_by(external_id="evt_del_1").first()
        assert ev is not None and ev.user_id is None
        assert "Jane Doe" not in (ev.raw_payload or "")   # PII scrubbed
        assert ev.amount_usd is not None                   # accounting data kept
    finally:
        # Clean up the retained (now user-less) financial rows.
        s.query(models.PaymentEvent).filter_by(external_id="evt_del_1").delete()
        s.query(models.Subscription).filter_by(external_id="sub_del_1").delete()
        s.commit()
        s.close()


def test_wrong_password_does_not_delete(client, user_factory):
    u = user_factory()
    s = db.SessionLocal()
    try:
        usr = s.get(models.User, u.uid)
        usr.password_hash = auth.hash_password("rightpw")
        s.commit()
    finally:
        s.close()
    client.cookies.set("sid", u.sid)
    try:
        r = client.post("/account/delete",
                        data={"current_password": "WRONG", "confirm": "DELETE",
                              "csrf_token": u.csrf},
                        follow_redirects=False)
    finally:
        client.cookies.clear()
    assert r.status_code == 200            # re-rendered account page, not deleted
    assert _count(models.User, id=u.uid) == 1
