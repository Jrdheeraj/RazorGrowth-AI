"""marketing agi tables

Revision ID: e9d4a7c1b2f8
Revises: b8d2f6a9c3e1
Create Date: 2026-09-10 00:00:00.000000

Isolated persistence for the autonomous MarketingAGI module.
The legacy MarketingAgent and its tables are untouched by this revision.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e9d4a7c1b2f8"
down_revision: Union[str, Sequence[str], None] = "b8d2f6a9c3e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "marketing_agi_runs",
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("phase", sa.String(length=40), nullable=False),
        sa.Column("iterations", sa.Integer(), nullable=False),
        sa.Column("tool_call_count", sa.Integer(), nullable=False),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("errors", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("llm_provider", sa.String(length=40), nullable=True),
        sa.Column("llm_model", sa.String(length=120), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_marketing_agi_runs_id"), "marketing_agi_runs", ["id"], unique=False)
    op.create_index(op.f("ix_marketing_agi_runs_merchant_id"), "marketing_agi_runs", ["merchant_id"], unique=False)
    op.create_index(op.f("ix_marketing_agi_runs_status"), "marketing_agi_runs", ["status"], unique=False)
    op.create_index("ix_magi_runs_merchant_status", "marketing_agi_runs", ["merchant_id", "status"], unique=False)

    op.create_table(
        "marketing_agi_events",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(length=40), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["marketing_agi_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_marketing_agi_events_id"), "marketing_agi_events", ["id"], unique=False)
    op.create_index(op.f("ix_marketing_agi_events_run_id"), "marketing_agi_events", ["run_id"], unique=False)
    op.create_index(op.f("ix_marketing_agi_events_merchant_id"), "marketing_agi_events", ["merchant_id"], unique=False)
    op.create_index(op.f("ix_marketing_agi_events_event_type"), "marketing_agi_events", ["event_type"], unique=False)
    op.create_index("ix_magi_events_run_seq", "marketing_agi_events", ["run_id", "seq"], unique=False)

    op.create_table(
        "marketing_agi_campaigns",
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("campaign_key", sa.String(length=140), nullable=False),
        sa.Column("workflow", sa.String(length=60), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("channel", sa.String(length=40), nullable=False),
        sa.Column("integration_status", sa.String(length=30), nullable=False),
        sa.Column("lifecycle", sa.String(length=30), nullable=False),
        sa.Column("audience", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("audience_count", sa.Integer(), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expected_impact", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("estimated_revenue", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("success_metric", sa.String(length=255), nullable=True),
        sa.Column("evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("verification", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("action_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["marketing_agi_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["action_id"], ["agent_actions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merchant_id", "campaign_key", name="uq_magi_campaigns_merchant_key"),
    )
    op.create_index(op.f("ix_marketing_agi_campaigns_id"), "marketing_agi_campaigns", ["id"], unique=False)
    op.create_index(op.f("ix_marketing_agi_campaigns_merchant_id"), "marketing_agi_campaigns", ["merchant_id"], unique=False)
    op.create_index(op.f("ix_marketing_agi_campaigns_run_id"), "marketing_agi_campaigns", ["run_id"], unique=False)
    op.create_index(op.f("ix_marketing_agi_campaigns_workflow"), "marketing_agi_campaigns", ["workflow"], unique=False)
    op.create_index(op.f("ix_marketing_agi_campaigns_lifecycle"), "marketing_agi_campaigns", ["lifecycle"], unique=False)
    op.create_index(op.f("ix_marketing_agi_campaigns_action_id"), "marketing_agi_campaigns", ["action_id"], unique=False)

    op.create_table(
        "marketing_agi_handoffs",
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("specialist", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("request", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["marketing_agi_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_marketing_agi_handoffs_id"), "marketing_agi_handoffs", ["id"], unique=False)
    op.create_index(op.f("ix_marketing_agi_handoffs_merchant_id"), "marketing_agi_handoffs", ["merchant_id"], unique=False)
    op.create_index(op.f("ix_marketing_agi_handoffs_run_id"), "marketing_agi_handoffs", ["run_id"], unique=False)
    op.create_index(op.f("ix_marketing_agi_handoffs_status"), "marketing_agi_handoffs", ["status"], unique=False)

    op.create_table(
        "marketing_agi_learnings",
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=True),
        sa.Column("action_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("expected", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("actual", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("verdict", sa.String(length=40), nullable=True),
        sa.Column("insights", sa.Text(), nullable=True),
        sa.Column("learned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["marketing_agi_campaigns.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_marketing_agi_learnings_id"), "marketing_agi_learnings", ["id"], unique=False)
    op.create_index(op.f("ix_marketing_agi_learnings_merchant_id"), "marketing_agi_learnings", ["merchant_id"], unique=False)
    op.create_index(op.f("ix_marketing_agi_learnings_campaign_id"), "marketing_agi_learnings", ["campaign_id"], unique=False)
    op.create_index(op.f("ix_marketing_agi_learnings_action_id"), "marketing_agi_learnings", ["action_id"], unique=False)


def downgrade() -> None:
    op.drop_table("marketing_agi_learnings")
    op.drop_table("marketing_agi_handoffs")
    op.drop_table("marketing_agi_campaigns")
    op.drop_table("marketing_agi_events")
    op.drop_table("marketing_agi_runs")
