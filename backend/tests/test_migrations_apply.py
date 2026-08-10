"""P0.10 — apply the P0.4 / P0.5 migrations against a representative legacy schema.

Complements test_api_key_migration (P0.2). Together these prove all three Phase-0
migrations run and do the right thing to legacy data on a clean SQLite DB (the
full production chain is Postgres-only; see MIGRATIONS.md).
"""
import importlib.util
import os

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

_VDIR = os.path.join(os.path.dirname(__file__), "..", "alembic", "versions")


def _load(fname):
    spec = importlib.util.spec_from_file_location(fname, os.path.join(_VDIR, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(mod, conn, direction):
    mod.op = Operations(MigrationContext.configure(conn))
    getattr(mod, direction)()


def test_idempotency_unique_migration_dedupes_and_constrains():
    mod = _load("f2b3c4d5e6a7_idempotency_unique.py")
    eng = sa.create_engine("sqlite://")
    with eng.begin() as conn:
        conn.execute(sa.text(
            "CREATE TABLE idempotency_keys (id INTEGER PRIMARY KEY, user_id INTEGER "
            "NOT NULL, key VARCHAR NOT NULL, response_json TEXT, created_at DATETIME)"))
        # Two duplicate (user_id, key) rows the old schema allowed.
        conn.execute(sa.text(
            "INSERT INTO idempotency_keys (id, user_id, key) VALUES "
            "(1, 7, 'dup'), (2, 7, 'dup'), (3, 7, 'other')"))
        _run(mod, conn, "upgrade")

        # Duplicate removed (newest kept), distinct key untouched.
        n = conn.execute(sa.text(
            "SELECT COUNT(*) FROM idempotency_keys")).scalar()
        assert n == 2
        kept = conn.execute(sa.text(
            "SELECT id FROM idempotency_keys WHERE key='dup'")).scalar()
        assert kept == 2  # MAX(id) kept
        # The unique constraint now rejects a new duplicate.
        try:
            conn.execute(sa.text(
                "INSERT INTO idempotency_keys (id, user_id, key) VALUES (4, 7, 'dup')"))
            assert False, "expected a uniqueness violation"
        except sa.exc.IntegrityError:
            pass


def test_subscription_user_nullable_migration():
    mod = _load("a3c4d5e6f7b8_subscription_user_nullable.py")
    eng = sa.create_engine("sqlite://")
    with eng.begin() as conn:
        conn.execute(sa.text(
            "CREATE TABLE subscriptions (id INTEGER PRIMARY KEY, user_id INTEGER "
            "NOT NULL, provider VARCHAR NOT NULL, external_id VARCHAR NOT NULL, "
            "plan VARCHAR NOT NULL, status VARCHAR NOT NULL, current_period_end "
            "DATETIME, cancelled_at DATETIME, amount_usd NUMERIC, created_at "
            "DATETIME NOT NULL, updated_at DATETIME NOT NULL)"))
        conn.execute(sa.text(
            "INSERT INTO subscriptions (id, user_id, provider, external_id, plan, "
            "status, created_at, updated_at) VALUES "
            "(1, 5, 'paymob', 'x', 'starter', 'active', '2026-01-01', '2026-01-01')"))
        _run(mod, conn, "upgrade")

        # After the migration a detached (NULL user_id) row is allowed — this is
        # what account-deletion-with-retention relies on.
        conn.execute(sa.text(
            "INSERT INTO subscriptions (id, user_id, provider, external_id, plan, "
            "status, created_at, updated_at) VALUES "
            "(2, NULL, 'paymob', 'y', 'starter', 'cancelled', '2026-01-01', '2026-01-01')"))
        got = conn.execute(sa.text(
            "SELECT user_id FROM subscriptions WHERE id=2")).scalar()
        assert got is None
        # Legacy row is preserved unchanged.
        assert conn.execute(sa.text(
            "SELECT user_id FROM subscriptions WHERE id=1")).scalar() == 5
