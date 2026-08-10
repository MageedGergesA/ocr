"""idempotency_keys: enforce UNIQUE(user_id, key)

Revision ID: f2b3c4d5e6a7
Revises: e1a2b3c4d5f6
Create Date: 2026-08-10

P0.4: the client Idempotency-Key replay guarantee depended on (user_id, key)
being unique, but the schema only had a non-unique index — so two concurrent
requests with the same key could both miss the lookup and both run/charge. This
adds the missing UNIQUE constraint so the database enforces it (the loser
IntegrityErrors on insert and the app replays the winner's stored response).

LEGACY DATA: if duplicate (user_id, key) rows already exist (possible without the
constraint), we keep the newest (MAX(id)) and delete the older duplicates before
creating the constraint. Idempotency rows are a response cache, so dropping older
duplicates is safe and loses no billable state.

ROLLBACK: downgrade drops the constraint only; no data is restored (the deleted
duplicate cache rows are not recreated). Safe.

PRODUCTION COMPATIBILITY: batch_alter_table for SQLite + PostgreSQL. Additive
constraint; run before or with the new app code (the store path already tolerates
an IntegrityError by rolling back and replaying).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2b3c4d5e6a7"
down_revision: Union[str, Sequence[str], None] = "e1a2b3c4d5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    # Deduplicate so the unique constraint can be created (keep newest per key).
    conn.execute(sa.text(
        "DELETE FROM idempotency_keys WHERE id NOT IN "
        "(SELECT max_id FROM (SELECT MAX(id) AS max_id FROM idempotency_keys "
        "GROUP BY user_id, key) AS keep)"))
    with op.batch_alter_table("idempotency_keys") as batch:
        batch.create_unique_constraint("uq_idempotency_user_key", ["user_id", "key"])


def downgrade() -> None:
    with op.batch_alter_table("idempotency_keys") as batch:
        batch.drop_constraint("uq_idempotency_user_key", type_="unique")
