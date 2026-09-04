"""phase F agent debate tables

Revision ID: f1a2b3c4d5e6
Revises: a3f8c2d91e47
Create Date: 2026-09-04 06:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'a3f8c2d91e47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'agent_debates',
        sa.Column('merchant_id', sa.Uuid(), nullable=False),
        sa.Column('objective', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('current_round', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('manager_agent_id', sa.String(length=80), nullable=True),
        sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('final_synthesis', sa.Text(), nullable=True),
        sa.Column('recommendation_id', sa.Uuid(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['merchant_id'], ['merchants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_agent_debates_id'), 'agent_debates', ['id'], unique=False)
    op.create_index(op.f('ix_agent_debates_merchant_id'), 'agent_debates', ['merchant_id'], unique=False)
    op.create_index(op.f('ix_agent_debates_status'), 'agent_debates', ['status'], unique=False)
    op.create_index('ix_agent_debates_merchant_status', 'agent_debates', ['merchant_id', 'status'], unique=False)

    op.create_table(
        'agent_tasks',
        sa.Column('debate_id', sa.Uuid(), nullable=False),
        sa.Column('merchant_id', sa.Uuid(), nullable=False),
        sa.Column('assigned_to', sa.String(length=40), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='assigned'),
        sa.Column('input_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('output_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['debate_id'], ['agent_debates.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['merchant_id'], ['merchants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_agent_tasks_id'), 'agent_tasks', ['id'], unique=False)
    op.create_index(op.f('ix_agent_tasks_debate_id'), 'agent_tasks', ['debate_id'], unique=False)
    op.create_index(op.f('ix_agent_tasks_merchant_id'), 'agent_tasks', ['merchant_id'], unique=False)
    op.create_index(op.f('ix_agent_tasks_assigned_to'), 'agent_tasks', ['assigned_to'], unique=False)
    op.create_index(op.f('ix_agent_tasks_status'), 'agent_tasks', ['status'], unique=False)
    op.create_index('ix_agent_tasks_debate_status', 'agent_tasks', ['debate_id', 'status'], unique=False)

    op.create_table(
        'agent_findings',
        sa.Column('debate_id', sa.Uuid(), nullable=False),
        sa.Column('task_id', sa.Uuid(), nullable=True),
        sa.Column('merchant_id', sa.Uuid(), nullable=False),
        sa.Column('agent_specialty', sa.String(length=40), nullable=False),
        sa.Column('finding_type', sa.String(length=20), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('confidence', sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column('uncertainty_notes', sa.Text(), nullable=True),
        sa.Column('supports_recommendation', sa.Boolean(), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['debate_id'], ['agent_debates.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_id'], ['agent_tasks.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['merchant_id'], ['merchants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_agent_findings_confidence_range",
        ),
    )
    op.create_index(op.f('ix_agent_findings_id'), 'agent_findings', ['id'], unique=False)
    op.create_index(op.f('ix_agent_findings_debate_id'), 'agent_findings', ['debate_id'], unique=False)
    op.create_index(op.f('ix_agent_findings_task_id'), 'agent_findings', ['task_id'], unique=False)
    op.create_index(op.f('ix_agent_findings_merchant_id'), 'agent_findings', ['merchant_id'], unique=False)
    op.create_index(op.f('ix_agent_findings_agent_specialty'), 'agent_findings', ['agent_specialty'], unique=False)
    op.create_index(op.f('ix_agent_findings_finding_type'), 'agent_findings', ['finding_type'], unique=False)
    op.create_index('ix_agent_findings_debate_type', 'agent_findings', ['debate_id', 'finding_type'], unique=False)

    op.create_table(
        'agent_messages',
        sa.Column('debate_id', sa.Uuid(), nullable=False),
        sa.Column('merchant_id', sa.Uuid(), nullable=False),
        sa.Column('from_agent', sa.String(length=40), nullable=False),
        sa.Column('to_agent', sa.String(length=40), nullable=True),
        sa.Column('message_type', sa.String(length=50), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('references', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['debate_id'], ['agent_debates.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['merchant_id'], ['merchants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_agent_messages_id'), 'agent_messages', ['id'], unique=False)
    op.create_index(op.f('ix_agent_messages_debate_id'), 'agent_messages', ['debate_id'], unique=False)
    op.create_index(op.f('ix_agent_messages_merchant_id'), 'agent_messages', ['merchant_id'], unique=False)
    op.create_index(op.f('ix_agent_messages_from_agent'), 'agent_messages', ['from_agent'], unique=False)
    op.create_index(op.f('ix_agent_messages_to_agent'), 'agent_messages', ['to_agent'], unique=False)
    op.create_index(op.f('ix_agent_messages_message_type'), 'agent_messages', ['message_type'], unique=False)
    op.create_index('ix_agent_messages_debate_agent', 'agent_messages', ['debate_id', 'from_agent'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_agent_messages_debate_agent', table_name='agent_messages')
    op.drop_index(op.f('ix_agent_messages_message_type'), table_name='agent_messages')
    op.drop_index(op.f('ix_agent_messages_to_agent'), table_name='agent_messages')
    op.drop_index(op.f('ix_agent_messages_from_agent'), table_name='agent_messages')
    op.drop_index(op.f('ix_agent_messages_merchant_id'), table_name='agent_messages')
    op.drop_index(op.f('ix_agent_messages_debate_id'), table_name='agent_messages')
    op.drop_index(op.f('ix_agent_messages_id'), table_name='agent_messages')
    op.drop_table('agent_messages')

    op.drop_index('ix_agent_findings_debate_type', table_name='agent_findings')
    op.drop_index(op.f('ix_agent_findings_finding_type'), table_name='agent_findings')
    op.drop_index(op.f('ix_agent_findings_agent_specialty'), table_name='agent_findings')
    op.drop_index(op.f('ix_agent_findings_merchant_id'), table_name='agent_findings')
    op.drop_index(op.f('ix_agent_findings_task_id'), table_name='agent_findings')
    op.drop_index(op.f('ix_agent_findings_debate_id'), table_name='agent_findings')
    op.drop_index(op.f('ix_agent_findings_id'), table_name='agent_findings')
    op.drop_table('agent_findings')

    op.drop_index('ix_agent_tasks_debate_status', table_name='agent_tasks')
    op.drop_index(op.f('ix_agent_tasks_status'), table_name='agent_tasks')
    op.drop_index(op.f('ix_agent_tasks_assigned_to'), table_name='agent_tasks')
    op.drop_index(op.f('ix_agent_tasks_merchant_id'), table_name='agent_tasks')
    op.drop_index(op.f('ix_agent_tasks_debate_id'), table_name='agent_tasks')
    op.drop_index(op.f('ix_agent_tasks_id'), table_name='agent_tasks')
    op.drop_table('agent_tasks')

    op.drop_index('ix_agent_debates_merchant_status', table_name='agent_debates')
    op.drop_index(op.f('ix_agent_debates_status'), table_name='agent_debates')
    op.drop_index(op.f('ix_agent_debates_merchant_id'), table_name='agent_debates')
    op.drop_index(op.f('ix_agent_debates_id'), table_name='agent_debates')
    op.drop_table('agent_debates')
