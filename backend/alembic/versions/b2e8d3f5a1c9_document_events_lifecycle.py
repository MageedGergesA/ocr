"""document_events — per-document lifecycle timeline

Delivery-side lifecycle stamps (exported / erp) keyed to a History row. The
earlier lifecycle stages (uploaded/extracted/validated/reviewed/approved) are
derived at read time from History / ExtractionVersion / Approval and need no
table. Powers GET /v1/history/{hid}/timeline.

Revision ID: b2e8d3f5a1c9
Revises: a1f7c9d24b30
Create Date: 2026-07-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b2e8d3f5a1c9'
down_revision: Union[str, Sequence[str], None] = 'a1f7c9d24b30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'document_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('history_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('stage', sa.String(), nullable=False),
        sa.Column('detail', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['history_id'], ['history.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_document_events_history_id'), 'document_events', ['history_id'])
    op.create_index(op.f('ix_document_events_user_id'), 'document_events', ['user_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_document_events_user_id'), table_name='document_events')
    op.drop_index(op.f('ix_document_events_history_id'), table_name='document_events')
    op.drop_table('document_events')
