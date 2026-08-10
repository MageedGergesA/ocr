"""P0.3 — the learning loop is auditable and non-destructive.

Regression for the discovery finding: _apply_learned_corrections silently
overwrote result_json and forced confidence to 0.9 with no version/audit row, so
a learned override was indistinguishable from a genuine high-confidence model
read and the model's original value was lost.

These tests prove:
  - the model's original value + confidence are preserved on the node,
  - confidence is NOT blindly forced to 0.9,
  - a high-confidence field is never overridden,
  - each learned change is recorded as an auditable ExtractionVersion
    (source='learned', old=model, new=learned),
  - so "what did the model produce?" and "what did Mostakhles change, and why?"
    are both answerable.
"""
from datetime import datetime

from app import db, models
from app.main import _apply_learned_corrections, _record_learned_versions


def _seed_correction(uid, field_key, corrected_value, document_type="invoice",
                     scope_key="", count=5):
    s = db.SessionLocal()
    try:
        s.add(models.CorrectionMemory(
            user_id=uid, document_type=document_type, field_key=field_key,
            scope_key=scope_key, original_value=None,
            corrected_value=corrected_value, count=count,
            updated_at=datetime.utcnow()))
        s.commit()
    finally:
        s.close()


def _cleanup(uid):
    s = db.SessionLocal()
    try:
        s.query(models.CorrectionMemory).filter_by(user_id=uid).delete()
        s.query(models.ExtractionVersion).filter_by(user_id=uid).delete()
        s.query(models.History).filter_by(user_id=uid).delete()
        s.commit()
    finally:
        s.close()


def test_low_conf_override_preserves_model_read_and_confidence(user_factory):
    u = user_factory()
    _seed_correction(u.uid, "vendor_name", "Acme Corp")
    data = {"vendor_name": {"value": "Acrne Corp", "confidence": 0.4}}
    s = db.SessionLocal()
    try:
        changes = _apply_learned_corrections(s, u.uid, "invoice", data)
    finally:
        s.close()
    try:
        assert len(changes) == 1
        node = data["vendor_name"]
        # Effective value is the learned one...
        assert node["value"] == "Acme Corp"
        assert node["learned"] is True
        assert node["learned_source"] == "correction_memory"
        # ...but the model's original read + confidence are preserved (reconstructable).
        assert node["model_value"] == "Acrne Corp"
        assert node["model_confidence"] == 0.4
        # Confidence is NOT blindly forced to 0.9 — it stays the model's value.
        assert node["confidence"] == 0.4
        # The returned change carries the provenance the caller will persist.
        ch = changes[0]
        assert ch["field"] == "vendor_name"
        assert ch["model_value"] == "Acrne Corp" and ch["learned_value"] == "Acme Corp"
    finally:
        _cleanup(u.uid)


def test_high_conf_field_not_overridden(user_factory):
    u = user_factory()
    _seed_correction(u.uid, "vendor_name", "Acme Corp")
    data = {"vendor_name": {"value": "Acme Corporation", "confidence": 0.95}}
    s = db.SessionLocal()
    try:
        changes = _apply_learned_corrections(s, u.uid, "invoice", data)
    finally:
        s.close()
    try:
        assert changes == []
        node = data["vendor_name"]
        assert node["value"] == "Acme Corporation"   # untouched
        assert "model_value" not in node and "learned" not in node
    finally:
        _cleanup(u.uid)


def test_no_corrections_leaves_data_untouched(user_factory):
    u = user_factory()
    data = {"vendor_name": {"value": "Foo", "confidence": 0.2}}
    s = db.SessionLocal()
    try:
        changes = _apply_learned_corrections(s, u.uid, "invoice", data)
    finally:
        s.close()
    assert changes == []
    assert data == {"vendor_name": {"value": "Foo", "confidence": 0.2}}


def test_volatile_field_never_learned(user_factory):
    u = user_factory()
    _seed_correction(u.uid, "invoice_total", "999.00")   # volatile (amount-like)
    data = {"invoice_total": {"value": "111.00", "confidence": 0.3}}
    s = db.SessionLocal()
    try:
        changes = _apply_learned_corrections(s, u.uid, "invoice", data)
    finally:
        s.close()
    try:
        assert changes == []
        assert data["invoice_total"]["value"] == "111.00"
    finally:
        _cleanup(u.uid)


def test_learned_changes_recorded_as_auditable_versions(user_factory):
    u = user_factory()
    # A real History row to attach versions to.
    s = db.SessionLocal()
    try:
        h = models.History(user_id=u.uid, kind="auto", document_type="invoice",
                           charged=1, result_json={"vendor_name": {"value": "Acme Corp"}})
        s.add(h); s.commit(); s.refresh(h)
        # v1 'extracted' marker, mirroring _record_history.
        s.add(models.ExtractionVersion(history_id=h.id, user_id=u.uid, version=1,
                                       source="extracted"))
        s.commit()
        hid = h.id
    finally:
        s.close()

    changes = [{"field": "vendor_name", "model_value": "Acrne Corp",
                "model_confidence": 0.4, "learned_value": "Acme Corp"}]
    s = db.SessionLocal()
    try:
        _record_learned_versions(s, hid, u.uid, changes)
    finally:
        s.close()

    s = db.SessionLocal()
    try:
        rows = (s.query(models.ExtractionVersion)
                .filter_by(history_id=hid).order_by(models.ExtractionVersion.version).all())
        by_source = {r.source for r in rows}
        assert "extracted" in by_source and "learned" in by_source
        learned = [r for r in rows if r.source == "learned"]
        assert len(learned) == 1
        lr = learned[0]
        # "what did the model produce?" -> old_value; "what did we change it to?" -> new_value
        assert lr.field == "vendor_name"
        assert lr.old_value == "Acrne Corp"
        assert lr.new_value == "Acme Corp"
        assert lr.version == 2                     # appended after v1
        assert lr.created_at is not None           # timestamped
    finally:
        s.close()
        _cleanup(u.uid)
