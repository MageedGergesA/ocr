"""template source_kind + bytes

Revision ID: 43c752e0b723
Revises: d23dc5298229
Create Date: 2026-05-30 16:31:53.454888

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '43c752e0b723'
down_revision: Union[str, Sequence[str], None] = 'd23dc5298229'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. NOTE: ix_history_result_gin (created by the prior migration
    with postgresql_using='gin') is preserved — autogenerate can't see the using
    clause and tries to drop the index. We keep it for future JSONB queries."""
    op.add_column('templates', sa.Column('source_kind', sa.String(length=8), nullable=True))
    op.add_column('templates', sa.Column('source_bytes', sa.LargeBinary(), nullable=True))
    op.add_column('templates', sa.Column('source_name', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('templates', 'source_name')
    op.drop_column('templates', 'source_bytes')
    op.drop_column('templates', 'source_kind')
