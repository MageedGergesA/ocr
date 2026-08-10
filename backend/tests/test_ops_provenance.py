"""Phase 1 — OpsEvent provenance/slicing dimensions are recorded."""
from app import db, models
from app.main import _log_ops, _model_id_for, APP_RELEASE


def test_ops_event_records_provenance(user_factory):
    u = user_factory()
    s = db.SessionLocal()
    try:
        _log_ops(s, u.uid, "auto", "ok", latency_ms=123, tier="hard",
                 document_type="tax_invoice", model_id="gemini-x",
                 schema_version="schema@abc", prompt_version="extract_auto@def")
    finally:
        s.close()
    s = db.SessionLocal()
    try:
        row = (s.query(models.OpsEvent).filter_by(user_id=u.uid)
               .order_by(models.OpsEvent.id.desc()).first())
        assert row is not None
        assert row.document_type == "tax_invoice"
        assert row.model_id == "gemini-x"
        assert row.schema_version == "schema@abc"
        assert row.prompt_version == "extract_auto@def"
        assert row.release == APP_RELEASE      # stamped automatically
    finally:
        s.query(models.OpsEvent).filter_by(user_id=u.uid).delete()
        s.commit()
        s.close()


def test_model_id_for_uses_registry():
    from app.ai import registry
    assert _model_id_for(True) == registry.production_strong_model_id()
    assert _model_id_for(False) == registry.production_fast_model_id()


def test_opsevent_model_has_new_columns():
    cols = {c.name for c in models.OpsEvent.__table__.columns}
    assert {"document_type", "model_id", "prompt_version", "schema_version",
            "release"} <= cols
