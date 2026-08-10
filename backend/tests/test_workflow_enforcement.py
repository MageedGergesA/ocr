"""P0.6 — approval state gates document egress (export / reproduce / ERP).

Regression for the discovery finding: /v1/export (and the other egress paths)
never checked Approval status, so a document that was pending, blocked, or
rejected could still be exported / sent to ERP — nullifying the workflow.

The gate is centralized in _enforce_workflow_gate. These tests drive it through
the real endpoints for every persisted status, and confirm approved / no-rule
documents still proceed. Persisted status strings (pending/blocked/approved/
rejected) are unchanged.
"""
import pytest

from app import db, models


def _make_doc(uid, status=None):
    """A History row, optionally with an Approval in `status`. Returns hid."""
    s = db.SessionLocal()
    try:
        h = models.History(user_id=uid, kind="auto", document_type="invoice",
                           charged=1, result_json={"total": {"value": "500"}})
        s.add(h); s.commit(); s.refresh(h)
        hid = h.id
        if status is not None:
            s.add(models.Approval(user_id=uid, history_id=hid, rule_name="amount",
                                  status=status))
            s.commit()
        return hid
    finally:
        s.close()


def _cleanup(uid):
    s = db.SessionLocal()
    try:
        s.query(models.Approval).filter_by(user_id=uid).delete()
        s.query(models.DocumentEvent).filter_by(user_id=uid).delete()
        s.query(models.History).filter_by(user_id=uid).delete()
        s.commit()
    finally:
        s.close()


def _export(client, key, hid):
    return client.post("/v1/export",
                       json={"format": "csv", "rows": [{"a": 1}], "history_id": hid},
                       headers={"x-api-key": key})


@pytest.mark.parametrize("status", ["pending", "blocked", "rejected"])
def test_export_blocked_for_held_document(client, user_factory, api_key_factory, status):
    u = user_factory()
    key = api_key_factory(u.uid)
    hid = _make_doc(u.uid, status=status)
    try:
        r = _export(client, key, hid)
        assert r.status_code == 409, r.text
        # No export bytes leaked — it's a JSON error, not a CSV attachment.
        assert "attachment" not in r.headers.get("content-disposition", "")
    finally:
        _cleanup(u.uid)


def test_export_allowed_when_approved(client, user_factory, api_key_factory):
    u = user_factory()
    key = api_key_factory(u.uid)
    hid = _make_doc(u.uid, status="approved")
    try:
        r = _export(client, key, hid)
        assert r.status_code == 200, r.text
        assert "attachment" in r.headers.get("content-disposition", "")
    finally:
        _cleanup(u.uid)


def test_export_allowed_when_no_rule_applies(client, user_factory, api_key_factory):
    """A document with no applicable approval rule keeps the current normal behavior."""
    u = user_factory()
    key = api_key_factory(u.uid)
    hid = _make_doc(u.uid, status=None)   # no Approval row at all
    try:
        r = _export(client, key, hid)
        assert r.status_code == 200, r.text
    finally:
        _cleanup(u.uid)


def test_reproduce_and_erp_confirm_are_also_gated(client, user_factory, api_key_factory):
    """The gate is centralized — reproduce and erp/confirm enforce it too."""
    u = user_factory()
    key = api_key_factory(u.uid)
    hid = _make_doc(u.uid, status="pending")
    try:
        r1 = client.post("/v1/reproduce",
                         json={"document_type": "invoice", "data": {"x": 1},
                               "format": "html", "history_id": hid},
                         headers={"x-api-key": key})
        assert r1.status_code == 409, r1.text
        r2 = client.post("/v1/erp/confirm",
                         json={"history_id": hid, "model": "account.move", "record_id": 5},
                         headers={"x-api-key": key})
        assert r2.status_code == 409, r2.text
        # The blocked import must NOT have been stamped.
        s = db.SessionLocal()
        try:
            assert s.query(models.DocumentEvent).filter_by(
                history_id=hid, stage="imported").count() == 0
        finally:
            s.close()
    finally:
        _cleanup(u.uid)


def test_approved_doc_can_be_sent_to_erp(client, user_factory, api_key_factory):
    u = user_factory()
    key = api_key_factory(u.uid)
    hid = _make_doc(u.uid, status="approved")
    try:
        r = client.post("/v1/erp/confirm",
                        json={"history_id": hid, "model": "account.move", "record_id": 5},
                        headers={"x-api-key": key})
        assert r.status_code == 200, r.text
        assert r.json()["stage"] == "imported"
    finally:
        _cleanup(u.uid)
