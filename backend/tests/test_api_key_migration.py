"""P0.2 — the api-key-hashing Alembic migration is correct and reversible-in-shape.

Runs the real upgrade()/downgrade() from the migration module against an
in-memory SQLite DB seeded with the PRE-migration `api_keys` schema (plaintext
`key` column), and asserts:

  - key_hash / key_prefix are backfilled from the plaintext,
  - the hash equals sha256(raw) so the same raw key still resolves,
  - the plaintext `key` column is dropped (no usable credential remains),
  - downgrade() restores the column shape (documented: values NOT recoverable).

The migration's module-global `op` (bound by `from alembic import op`) is
rebound to an Operations instance on a live connection — a standard way to
exercise a migration's SQL outside a full alembic run.
"""
import hashlib
import importlib.util
import os

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

_MIG_PATH = os.path.join(os.path.dirname(__file__), "..", "alembic", "versions",
                         "e1a2b3c4d5f6_api_key_hashing.py")


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_apikey_hash", _MIG_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed_old_schema(conn):
    conn.execute(sa.text(
        "CREATE TABLE api_keys ("
        " id INTEGER PRIMARY KEY,"
        " key VARCHAR NOT NULL UNIQUE,"
        " user_id INTEGER NOT NULL,"
        " active BOOLEAN NOT NULL,"
        " created_at DATETIME)"))
    conn.execute(sa.text(
        "INSERT INTO api_keys (id, key, user_id, active) VALUES "
        "(1, 'mk_legacy_alpha', 10, 1), (2, 'mk_legacy_bravo', 10, 0)"))


def _run(mod, conn, direction):
    ctx = MigrationContext.configure(conn)
    mod.op = Operations(ctx)  # rebind the module's `op` to this live connection
    getattr(mod, direction)()


def test_upgrade_backfills_and_drops_plaintext():
    mod = _load_migration()
    eng = sa.create_engine("sqlite://")
    with eng.begin() as conn:
        _seed_old_schema(conn)
        _run(mod, conn, "upgrade")

        cols = {c["name"] for c in sa.inspect(conn).get_columns("api_keys")}
        assert "key" not in cols, "plaintext column must be dropped"
        assert {"key_hash", "key_prefix"} <= cols

        rows = conn.execute(sa.text(
            "SELECT id, key_hash, key_prefix FROM api_keys ORDER BY id")).fetchall()
        assert rows[0][1] == hashlib.sha256(b"mk_legacy_alpha").hexdigest()
        assert rows[0][2] == "mk_legacy_alpha"[:12]   # prefix = first 12 chars
        assert rows[1][1] == hashlib.sha256(b"mk_legacy_bravo").hexdigest()

        # a unique index on key_hash exists
        idx = {i["name"] for i in sa.inspect(conn).get_indexes("api_keys")}
        assert "ix_api_keys_key_hash" in idx


def test_downgrade_restores_column_shape():
    mod = _load_migration()
    eng = sa.create_engine("sqlite://")
    with eng.begin() as conn:
        _seed_old_schema(conn)
        _run(mod, conn, "upgrade")
        _run(mod, conn, "downgrade")
        cols = {c["name"] for c in sa.inspect(conn).get_columns("api_keys")}
        assert "key" in cols
        assert "key_hash" not in cols and "key_prefix" not in cols
