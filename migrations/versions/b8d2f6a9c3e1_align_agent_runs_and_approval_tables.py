"""align agent_runs counters and create recommendations/approvals tables

The Phase-5 migration predated several ORM additions: the agent_runs
counter columns (insights_generated, signals_detected, experiments_proposed)
and the recommendations/approvals tables used by the recommendation/
approval workflow. Fresh databases created purely via `alembic upgrade`
were therefore missing them, breaking agent runs and approvals.

Revision ID: b8d2f6a9c3e1
Revises: f1a2b3c4d5e6
Create Date: 2026-09-06

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision = "b8d2f6a9c3e1"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(name)


def _columns_present(table: str, names: set[str]) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(table):
        return False
    existing = {c["name"] for c in insp.get_columns(table)}
    return names.issubset(existing)


def upgrade() -> None:
    # ── agent_runs: counter columns used by the current ORM ───────────
    if not _columns_present("agent_runs", {"insights_generated"}):
        op.add_column("agent_runs", sa.Column("insights_generated", sa.Integer(), nullable=False, server_default="0"))
    if not _columns_present("agent_runs", {"signals_detected"}):
        op.add_column("agent_runs", sa.Column("signals_detected", sa.Integer(), nullable=False, server_default="0"))
    if not _columns_present("agent_runs", {"experiments_proposed"}):
        op.add_column("agent_runs", sa.Column("experiments_proposed", sa.Integer(), nullable=False, server_default="0"))

    # ── recommendations table (mirrors backend.app.models.recommendation) ─
    if not _table_exists("recommendations"):
        op.create_table(
            "recommendations",
            sa.Column("merchant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("opportunity_id", UUID(as_uuid=True), nullable=True),
            sa.Column("recommendation_key", sa.String(length=100), nullable=True),
            sa.Column("type", sa.String(length=50), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("proposed_action", sa.String(length=100), nullable=False),
            sa.Column("target_segment", sa.String(length=100), nullable=True),
            sa.Column("rationale", sa.Text(), nullable=True),
            sa.Column("evidence", JSONB(), nullable=True),
            sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
            sa.Column("assumptions", JSONB(), nullable=True),
            sa.Column("expected_revenue", sa.Numeric(14, 2), nullable=False),
            sa.Column("expected_conversion", sa.Numeric(6, 4), nullable=True),
            sa.Column("estimated_cost", sa.Numeric(14, 2), nullable=True),
            sa.Column("guardrails", JSONB(), nullable=True),
            sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("approved_version", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
            sa.Column("simulation_snapshot", JSONB(), nullable=True),
            sa.Column("id", UUID(as_uuid=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["opportunity_id"], ["growth_opportunities.id"], ondelete="SET NULL"),
            sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_recommendations_confidence_range"),
            sa.CheckConstraint("expected_revenue >= 0", name="ck_recommendations_expected_revenue_non_negative"),
            sa.CheckConstraint("version >= 1", name="ck_recommendations_version_positive"),
        )
        op.create_index(op.f("ix_recommendations_id"), "recommendations", ["id"], unique=False)
        op.create_index(op.f("ix_recommendations_merchant_id"), "recommendations", ["merchant_id"], unique=False)
        op.create_index(op.f("ix_recommendations_opportunity_id"), "recommendations", ["opportunity_id"], unique=False)
        op.create_index(op.f("ix_recommendations_type"), "recommendations", ["type"], unique=False)
        op.create_index(op.f("ix_recommendations_recommendation_key"), "recommendations", ["recommendation_key"], unique=False)
        op.create_index(op.f("ix_recommendations_status"), "recommendations", ["status"], unique=False)
        op.create_index("ix_recommendations_merchant_status", "recommendations", ["merchant_id", "status"], unique=False)
        op.create_index("ix_recommendations_merchant_key", "recommendations", ["merchant_id", "recommendation_key"], unique=True)

    # ── approvals table (mirrors backend.app.models.approval) ──────────
    if not _table_exists("approvals"):
        op.create_table(
            "approvals",
            sa.Column("merchant_id", UUID(as_uuid=True), nullable=False),
            sa.Column("recommendation_id", UUID(as_uuid=True), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("approver_user_id", UUID(as_uuid=True), nullable=True),
            sa.Column("approver_email", sa.String(length=320), nullable=True),
            sa.Column("decision", sa.String(length=30), nullable=True),
            sa.Column("comment", sa.String(length=2000), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("recommendation_snapshot", JSONB(), nullable=True),
            sa.Column("simulation_snapshot", JSONB(), nullable=True),
            sa.Column("approved_version", sa.Integer(), nullable=True),
            sa.Column("id", UUID(as_uuid=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["recommendation_id"], ["recommendations.id"], ondelete="CASCADE"),
        )
        op.create_index(op.f("ix_approvals_id"), "approvals", ["id"], unique=False)
        op.create_index(op.f("ix_approvals_merchant_id"), "approvals", ["merchant_id"], unique=False)
        op.create_index(op.f("ix_approvals_recommendation_id"), "approvals", ["recommendation_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_approvals_recommendation_id"), table_name="approvals")
    op.drop_index(op.f("ix_approvals_merchant_id"), table_name="approvals")
    op.drop_index(op.f("ix_approvals_id"), table_name="approvals")
    op.drop_table("approvals")
    op.drop_index(op.f("ix_recommendations_merchant_key"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_merchant_status"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_status"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_recommendation_key"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_type"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_opportunity_id"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_merchant_id"), table_name="recommendations")
    op.drop_index(op.f("ix_recommendations_id"), table_name="recommendations")
    op.drop_table("recommendations")
    op.drop_column("agent_runs", "experiments_proposed")
    op.drop_column("agent_runs", "signals_detected")
    op.drop_column("agent_runs", "insights_generated")
