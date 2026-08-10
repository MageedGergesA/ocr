"""ops_events: add provenance/slicing columns (document_type, model, versions, release)

Revision ID: b4c5d6e7f8a9
Revises: a3c4d5e6f7b8
Create Date: 2026-08-10

Phase 1: OpsEvent could not be sliced by document type / model / release, so
"did Saudi-invoice success drop after yesterday's deploy?" was unanswerable. Adds
nullable columns document_type, model_id, prompt_version, schema_version, release.

LEGACY DATA: all columns NULLABLE — historical rows (which never recorded these)
stay valid and are simply reported as unknown. No historical data is rewritten.

ROLLBACK: downgrade drops the columns (and their data). Safe.

PRODUCTION COMPATIBILITY: additive; PostgreSQL + SQLite. Run before starting the
new app code (the schema guard enforces this).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, Sequence[str], None] = "a3c4d5e6f7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ops_events", sa.Column("document_type", sa.String(), nullable=True))
    op.add_column("ops_events", sa.Column("model_id", sa.String(), nullable=True))
    op.add_column("ops_events", sa.Column("prompt_version", sa.String(), nullable=True))
    op.add_column("ops_events", sa.Column("schema_version", sa.String(), nullable=True))
    op.add_column("ops_events", sa.Column("release", sa.String(), nullable=True))
    op.create_index("ix_ops_events_document_type", "ops_events", ["document_type"])
    op.create_index("ix_ops_events_release", "ops_events", ["release"])


def downgrade() -> None:
    op.drop_index("ix_ops_events_release", table_name="ops_events")
    op.drop_index("ix_ops_events_document_type", table_name="ops_events")
    for col in ("release", "schema_version", "prompt_version", "model_id", "document_type"):
        op.drop_column("ops_events", col)
