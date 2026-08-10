"""P0.7 — migration chain integrity + the startup schema-revision guard.

Regression for the discovery finding: the deploy could boot against a stale schema
and fail later at query time; there was no revision check and the prod-readiness
guard was dormant. These tests prove the migration tree is single-headed (so new
migrations chain correctly) and that assert_schema_current() fails fast when the DB
is not at head and passes when it is — without ever migrating.
"""
import sqlalchemy as sa

from app import db


def test_single_alembic_head():
    """A healthy chain has exactly one head. More than one = an unmerged branch
    (a hand-authored-migration mistake this catches before deploy)."""
    heads = db.alembic_head_revisions()
    assert len(heads) == 1, f"expected a single alembic head, got {heads}"
    assert next(iter(heads))  # non-empty revision id


def _stamp(engine, revision):
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES (:r)"),
                     {"r": revision})


def test_guard_passes_when_db_at_head():
    head = next(iter(db.alembic_head_revisions()))
    eng = sa.create_engine("sqlite://")
    _stamp(eng, head)
    db.assert_schema_current(engine_=eng)   # must not raise


def test_guard_raises_when_db_behind():
    eng = sa.create_engine("sqlite://")
    _stamp(eng, "c3f1a7e9d2b4")             # an older, real revision
    try:
        db.assert_schema_current(engine_=eng)
        assert False, "expected RuntimeError for a stale schema"
    except RuntimeError as e:
        assert "alembic upgrade head" in str(e)


def test_guard_raises_when_unmanaged():
    """A DB with no alembic_version (never migrated) must not be treated as current."""
    eng = sa.create_engine("sqlite://")
    try:
        db.assert_schema_current(engine_=eng)
        assert False, "expected RuntimeError when there is no alembic_version"
    except RuntimeError:
        pass
