"""workflow engine + prove-the-platform tables

Adds every table/column that dev auto-creates via create_all()/_ensure_columns()
but that has no migration yet, so prod can be brought up to the current models:

  Workflow Engine v1        : workflow_rules, approvals, audit_log
  Prove-the-platform spines : ops_events (observability), idempotency_keys,
                              correction_memory (learning loop),
                              extraction_versions (version history)
  Usage metrics             : history.field_count, history.avg_confidence

FK-safe create order; CASCADE deletes, index names, and JSONB variants match
app/models.py exactly.

Revision ID: a1f7c9d24b30
Revises: 43c752e0b723
Create Date: 2026-07-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1f7c9d24b30'
down_revision: Union[str, Sequence[str], None] = '43c752e0b723'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# JSONB on Postgres, JSON elsewhere — mirrors models.JsonCol.
def _json():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    """Upgrade schema."""
    # ---- usage metrics: two new History columns ------------------------------
    op.add_column('history', sa.Column('field_count', sa.Integer(), nullable=True))
    op.add_column('history', sa.Column('avg_confidence', sa.Integer(), nullable=True))

    # ---- Workflow Engine v1 --------------------------------------------------
    op.create_table(
        'workflow_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('field', sa.String(), nullable=False),
        sa.Column('op', sa.String(), nullable=False),
        sa.Column('value', sa.String(), nullable=False),
        sa.Column('action', sa.String(), nullable=False, server_default='require_approval'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_workflow_rules_user_id'), 'workflow_rules', ['user_id'])
    op.create_index('ix_workflow_rules_user', 'workflow_rules', ['user_id', 'active'])

    op.create_table(
        'approvals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('history_id', sa.Integer(), nullable=False),
        sa.Column('rule_id', sa.Integer(), nullable=True),
        sa.Column('rule_name', sa.String(), nullable=True),
        sa.Column('document_type', sa.String(), nullable=True),
        sa.Column('amount', sa.Numeric(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('decided_by', sa.Integer(), nullable=True),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['history_id'], ['history.id']),
        sa.ForeignKeyConstraint(['rule_id'], ['workflow_rules.id']),
        sa.ForeignKeyConstraint(['decided_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_approvals_user_id'), 'approvals', ['user_id'])
    op.create_index('ix_approvals_user_status', 'approvals', ['user_id', 'status'])

    op.create_table(
        'audit_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('approval_id', sa.Integer(), nullable=True),
        sa.Column('event', sa.String(), nullable=False),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['approval_id'], ['approvals.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_audit_log_user_id'), 'audit_log', ['user_id'])
    op.create_index('ix_audit_user_created', 'audit_log', ['user_id', 'created_at'])

    # ---- Observability: one row per extraction attempt -----------------------
    op.create_table(
        'ops_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('kind', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('http_status', sa.Integer(), nullable=True),
        sa.Column('tier', sa.String(), nullable=True),
        sa.Column('error_type', sa.String(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_ops_events_user_id'), 'ops_events', ['user_id'])
    op.create_index(op.f('ix_ops_events_created_at'), 'ops_events', ['created_at'])

    # ---- Idempotency-Key replay store ----------------------------------------
    op.create_table(
        'idempotency_keys',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('response_json', _json(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_idempotency_keys_user_id'), 'idempotency_keys', ['user_id'])
    op.create_index(op.f('ix_idempotency_keys_key'), 'idempotency_keys', ['key'])

    # ---- Correction-learning store -------------------------------------------
    op.create_table(
        'correction_memory',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('document_type', sa.String(), nullable=True),
        sa.Column('field_key', sa.String(), nullable=False),
        sa.Column('original_value', sa.Text(), nullable=True),
        sa.Column('corrected_value', sa.Text(), nullable=True),
        sa.Column('count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_correction_memory_user_id'), 'correction_memory', ['user_id'])
    op.create_index(op.f('ix_correction_memory_document_type'), 'correction_memory', ['document_type'])

    # ---- Extraction version history ------------------------------------------
    op.create_table(
        'extraction_versions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('history_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('field', sa.String(), nullable=True),
        sa.Column('old_value', sa.Text(), nullable=True),
        sa.Column('new_value', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['history_id'], ['history.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_extraction_versions_history_id'), 'extraction_versions', ['history_id'])
    op.create_index(op.f('ix_extraction_versions_user_id'), 'extraction_versions', ['user_id'])


def downgrade() -> None:
    """Downgrade schema — drop in reverse FK order."""
    op.drop_index(op.f('ix_extraction_versions_user_id'), table_name='extraction_versions')
    op.drop_index(op.f('ix_extraction_versions_history_id'), table_name='extraction_versions')
    op.drop_table('extraction_versions')

    op.drop_index(op.f('ix_correction_memory_document_type'), table_name='correction_memory')
    op.drop_index(op.f('ix_correction_memory_user_id'), table_name='correction_memory')
    op.drop_table('correction_memory')

    op.drop_index(op.f('ix_idempotency_keys_key'), table_name='idempotency_keys')
    op.drop_index(op.f('ix_idempotency_keys_user_id'), table_name='idempotency_keys')
    op.drop_table('idempotency_keys')

    op.drop_index(op.f('ix_ops_events_created_at'), table_name='ops_events')
    op.drop_index(op.f('ix_ops_events_user_id'), table_name='ops_events')
    op.drop_table('ops_events')

    op.drop_index('ix_audit_user_created', table_name='audit_log')
    op.drop_index(op.f('ix_audit_log_user_id'), table_name='audit_log')
    op.drop_table('audit_log')

    op.drop_index('ix_approvals_user_status', table_name='approvals')
    op.drop_index(op.f('ix_approvals_user_id'), table_name='approvals')
    op.drop_table('approvals')

    op.drop_index('ix_workflow_rules_user', table_name='workflow_rules')
    op.drop_index(op.f('ix_workflow_rules_user_id'), table_name='workflow_rules')
    op.drop_table('workflow_rules')

    op.drop_column('history', 'avg_confidence')
    op.drop_column('history', 'field_count')
