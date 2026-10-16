"""agent handoffs — real cross-agent collaboration

Revision ID: h4n0d0ff2a11
Revises: c2e7a41f9b60
Create Date: 2026-10-14 19:45:00.000000

Creates ``agent_handoffs`` so a cross-agent delegation is a durable,
dispatchable record rather than a row that sits in ``pending`` forever.

Deliberately NOT stored in ``agent_actions``: a handoff is an internal
orchestration record, and putting it in the money-action table would have
made it visible in (and theoretically approvable through) the merchant
Actions console.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "h4n0d0ff2a11"
down_revision: Union[str, Sequence[str], None] = "c2e7a41f9b60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_handoffs",
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("source_agent", sa.String(length=64), nullable=False),
        sa.Column("destination_agent", sa.String(length=64), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "dispatched", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["merchant_id"], ["merchants.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_handoffs_merchant_id", "agent_handoffs", ["merchant_id"]
    )
    op.create_index(
        "ix_agent_handoffs_source_agent", "agent_handoffs", ["source_agent"]
    )
    op.create_index(
        "ix_agent_handoffs_destination_agent",
        "agent_handoffs",
        ["destination_agent"],
    )
    op.create_index("ix_agent_handoffs_status", "agent_handoffs", ["status"])
    op.create_index("ix_agent_handoffs_fingerprint", "agent_handoffs", ["fingerprint"])
    op.create_index(
        "ix_agent_handoffs_correlation_id", "agent_handoffs", ["correlation_id"]
    )
    op.create_index(
        "ix_agent_handoffs_merchant_status",
        "agent_handoffs",
        ["merchant_id", "status"],
    )
    op.create_index(
        "ix_agent_handoffs_merchant_fingerprint",
        "agent_handoffs",
        ["merchant_id", "fingerprint"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_handoffs_merchant_fingerprint", table_name="agent_handoffs")
    op.drop_index("ix_agent_handoffs_merchant_status", table_name="agent_handoffs")
    op.drop_index("ix_agent_handoffs_correlation_id", table_name="agent_handoffs")
    op.drop_index("ix_agent_handoffs_fingerprint", table_name="agent_handoffs")
    op.drop_index("ix_agent_handoffs_status", table_name="agent_handoffs")
    op.drop_index("ix_agent_handoffs_destination_agent", table_name="agent_handoffs")
    op.drop_index("ix_agent_handoffs_source_agent", table_name="agent_handoffs")
    op.drop_index("ix_agent_handoffs_merchant_id", table_name="agent_handoffs")
    op.drop_table("agent_handoffs")