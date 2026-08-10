"""correction_memory.scope_key — vendor scoping for the learning loop

A learned correction now carries the vendor/party identity of the document it
came from, so it's only re-applied to documents from the same source (learning
loop v1.1 hardening). Nullable = global correction.

Revision ID: c3f1a7e9d2b4
Revises: b2e8d3f5a1c9
Create Date: 2026-07-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3f1a7e9d2b4'
down_revision: Union[str, Sequence[str], None] = 'b2e8d3f5a1c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('correction_memory', sa.Column('scope_key', sa.String(), nullable=True))
    op.create_index(op.f('ix_correction_memory_scope_key'), 'correction_memory', ['scope_key'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_correction_memory_scope_key'), table_name='correction_memory')
    op.drop_column('correction_memory', 'scope_key')
