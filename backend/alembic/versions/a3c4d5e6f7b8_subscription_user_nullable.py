"""subscriptions.user_id nullable (for account-deletion anonymize/detach)

Revision ID: a3c4d5e6f7b8
Revises: f2b3c4d5e6a7
Create Date: 2026-08-10

P0.5: account deletion must not blindly destroy financial/accounting records.
To retain Subscription rows for tax/accounting while removing the personal link,
user_id must be nullable so it can be set to NULL (detached) on deletion.
(PaymentEvent.user_id was already nullable.)

LEGACY DATA: no rows changed; only the column's NOT NULL is dropped. Existing
subscriptions keep their user_id.

ROLLBACK: downgrade re-imposes NOT NULL. This FAILS if any detached (user_id IS
NULL) subscriptions exist by then — expected, and documented: do not downgrade
after accounts have been deleted-with-retention.

PRODUCTION COMPATIBILITY: batch_alter_table for SQLite + PostgreSQL.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3c4d5e6f7b8"
down_revision: Union[str, Sequence[str], None] = "f2b3c4d5e6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("subscriptions") as batch:
        batch.alter_column("user_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("subscriptions") as batch:
        batch.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
