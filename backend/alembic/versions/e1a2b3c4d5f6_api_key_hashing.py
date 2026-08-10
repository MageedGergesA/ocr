"""api key hashing: store sha256(key) + display prefix, drop plaintext

Revision ID: e1a2b3c4d5f6
Revises: c3f1a7e9d2b4
Create Date: 2026-08-10

Security (P0.2): API keys were stored in plaintext, so a DB dump / backup leak
exposed every tenant's live credentials. This migration:

  1. adds `key_hash` (sha256 hex of the raw key) and `key_prefix` (non-secret
     display fragment, e.g. 'mk_AbCdEf12'),
  2. BACKFILLS both from the existing plaintext `key` (we still have it here), so
     every existing customer key keeps working (resolution is by hash of the same
     raw key the customer already holds),
  3. enforces NOT NULL + a unique index on `key_hash`,
  4. DROPS the plaintext `key` column.

LEGACY DATA: fully preserved — no rows are deleted; each key row keeps its id,
user_id, active flag, and now authenticates via its hash instead of its plaintext.

ROLLBACK RISK (important): hashing is one-way. `downgrade()` re-creates the
`key` column for schema symmetry but CANNOT restore the plaintext values — they
were intentionally destroyed. After a downgrade, the old code path
(`filter_by(key=...)`) would find no keys, so every key would stop resolving.
Do not downgrade in production once real keys have been migrated; re-issue keys
instead. `downgrade()` is safe only on a DB that had no keys.

PRODUCTION COMPATIBILITY: uses batch_alter_table so it runs on both PostgreSQL
and SQLite. Deploy order matters — run this migration BEFORE starting the new
app code (the new code reads `key_hash`; the old code reads `key`). The schema
revision guard added in P0.7 enforces this.
"""
import hashlib
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1a2b3c4d5f6"
down_revision: Union[str, Sequence[str], None] = "c3f1a7e9d2b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _sha256(raw: str) -> str:
    return hashlib.sha256((raw or "").encode()).hexdigest()


def upgrade() -> None:
    # 1) additive, nullable columns (works on PG + SQLite without a rewrite)
    op.add_column("api_keys", sa.Column("key_hash", sa.String(), nullable=True))
    op.add_column("api_keys", sa.Column("key_prefix", sa.String(), nullable=True))

    # 2) backfill hash + prefix from the plaintext key that still exists here
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, key FROM api_keys")).fetchall()
    for row in rows:
        raw = row[1]
        if raw is None:
            continue
        conn.execute(
            sa.text("UPDATE api_keys SET key_hash=:h, key_prefix=:p WHERE id=:i"),
            {"h": _sha256(raw), "p": raw[:12], "i": row[0]},
        )

    # 3) enforce constraints + unique index, then 4) drop the plaintext column.
    #    batch mode recreates the table on SQLite; a no-op wrapper on PostgreSQL.
    with op.batch_alter_table("api_keys") as batch:
        batch.alter_column("key_hash", existing_type=sa.String(), nullable=False)
        batch.alter_column("key_prefix", existing_type=sa.String(),
                           nullable=False, server_default="")
        batch.create_index("ix_api_keys_key_hash", ["key_hash"], unique=True)
        batch.drop_column("key")


def downgrade() -> None:
    # See ROLLBACK RISK above: plaintext keys are NOT recoverable. This only
    # restores the column shape.
    with op.batch_alter_table("api_keys") as batch:
        batch.add_column(sa.Column("key", sa.String(), nullable=True))
        batch.drop_index("ix_api_keys_key_hash")
        batch.drop_column("key_prefix")
        batch.drop_column("key_hash")
