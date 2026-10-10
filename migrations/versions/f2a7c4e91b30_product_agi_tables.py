"""product agi tables

Revision ID: f2a7c4e91b30
Revises: d4e5f6a7b8c9
Create Date: 2026-10-08 00:00:00.000000

Adds the Product Agent's isolated workspace: runs, the real event feed,
evidence-backed findings and evidence-backed recommendations.

Design notes that matter for review:

  * Four new tables only. Nothing existing is altered, so every Marketing
    AGI table, index and migration stays exactly as it was.
  * There is deliberately no ``product_agent_actions`` table. A
    recommendation becomes work through the existing ``agent_actions``
    pipeline (FK ``action_id`` -> ``agent_actions.id``, ON DELETE SET NULL),
    so approval, verification, execution and audit remain in one place.
  * All four tables are tenant-scoped by a non-null ``merchant_id`` FK to
    ``merchants.id`` with ``ON DELETE CASCADE``, matching every other
    merchant-owned table in the schema.
  * JSONB is used for evidence/metrics/state blobs, consistent with
    marketing_agi_runs.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f2a7c4e91b30"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    # ── product_agent_runs ────────────────────────────────────────────────
    op.create_table(
        "product_agent_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("merchant_id", sa.UUID(), nullable=False),
        sa.Column("analysis_cycle_id", sa.String(length=64), nullable=True),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("current_stage", sa.String(length=40), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("metrics", JSONB, nullable=True),
        sa.Column("approval_status", sa.String(length=24), nullable=True),
        sa.Column("state", JSONB, nullable=True),
        sa.Column("result", JSONB, nullable=True),
        sa.Column("errors", JSONB, nullable=True),
        sa.Column("llm_provider", sa.String(length=40), nullable=True),
        sa.Column("llm_model", sa.String(length=120), nullable=True),
        sa.Column("products_analyzed", sa.Integer(), nullable=False),
        sa.Column("opportunities_found", sa.Integer(), nullable=False),
        sa.Column("recommendations_created", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["merchant_id"], ["merchants.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_agent_runs_id", "product_agent_runs", ["id"])
    op.create_index(
        "ix_product_agent_runs_merchant_id", "product_agent_runs", ["merchant_id"]
    )
    op.create_index(
        "ix_product_agent_runs_analysis_cycle_id",
        "product_agent_runs",
        ["analysis_cycle_id"],
    )
    op.create_index("ix_product_agent_runs_status", "product_agent_runs", ["status"])
    op.create_index(
        "ix_product_agent_runs_current_stage", "product_agent_runs", ["current_stage"]
    )
    op.create_index("ix_pa_runs_merchant_status", "product_agent_runs",
                    ["merchant_id", "status"])

    # ── product_agent_events ──────────────────────────────────────────────
    op.create_table(
        "product_agent_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("merchant_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=40), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["product_agent_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["merchant_id"], ["merchants.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_agent_events_id", "product_agent_events", ["id"])
    op.create_index("ix_product_agent_events_run_id", "product_agent_events", ["run_id"])
    op.create_index(
        "ix_product_agent_events_merchant_id", "product_agent_events", ["merchant_id"]
    )
    op.create_index(
        "ix_product_agent_events_event_type", "product_agent_events", ["event_type"]
    )
    op.create_index("ix_pa_events_run_seq", "product_agent_events", ["run_id", "seq"])

    # ── product_agent_findings ────────────────────────────────────────────
    op.create_table(
        "product_agent_findings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("merchant_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("evidence", JSONB, nullable=True),
        sa.Column("product_ids", JSONB, nullable=True),
        sa.Column("data", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["product_agent_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["merchant_id"], ["merchants.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_agent_findings_id", "product_agent_findings", ["id"])
    op.create_index(
        "ix_product_agent_findings_run_id", "product_agent_findings", ["run_id"]
    )
    op.create_index(
        "ix_product_agent_findings_merchant_id", "product_agent_findings", ["merchant_id"]
    )
    op.create_index(
        "ix_product_agent_findings_type", "product_agent_findings", ["type"]
    )
    op.create_index(
        "ix_product_agent_findings_severity", "product_agent_findings", ["severity"]
    )
    op.create_index(
        "ix_pa_findings_run_type", "product_agent_findings", ["run_id", "type"]
    )

    # ── product_agent_recommendations ─────────────────────────────────────
    op.create_table(
        "product_agent_recommendations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("merchant_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("problem", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("why_now", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence", JSONB, nullable=True),
        sa.Column("expected_impact", JSONB, nullable=True),
        sa.Column("risk", sa.Text(), nullable=True),
        sa.Column("affected_products", JSONB, nullable=True),
        sa.Column("basis", sa.String(length=80), nullable=True),
        sa.Column("action_required", sa.Boolean(), nullable=False),
        sa.Column("approval_required", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("action_id", sa.UUID(), nullable=True),
        sa.Column("data", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # The existing action pipeline owns approval + execution. SET NULL
        # so deleting an action never destroys the evidence trail.
        sa.ForeignKeyConstraint(
            ["action_id"], ["agent_actions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["product_agent_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["merchant_id"], ["merchants.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_product_agent_recommendations_id", "product_agent_recommendations", ["id"]
    )
    op.create_index(
        "ix_product_agent_recommendations_run_id",
        "product_agent_recommendations",
        ["run_id"],
    )
    op.create_index(
        "ix_product_agent_recommendations_merchant_id",
        "product_agent_recommendations",
        ["merchant_id"],
    )
    op.create_index(
        "ix_product_agent_recommendations_type",
        "product_agent_recommendations",
        ["type"],
    )
    op.create_index(
        "ix_product_agent_recommendations_status",
        "product_agent_recommendations",
        ["status"],
    )
    op.create_index(
        "ix_product_agent_recommendations_action_id",
        "product_agent_recommendations",
        ["action_id"],
    )
    op.create_index(
        "ix_pa_recs_run_type",
        "product_agent_recommendations",
        ["run_id", "type"],
    )


def downgrade() -> None:
    op.drop_index("ix_pa_recs_run_type", table_name="product_agent_recommendations")
    op.drop_index("ix_product_agent_recommendations_action_id",
                  table_name="product_agent_recommendations")
    op.drop_index("ix_product_agent_recommendations_status",
                  table_name="product_agent_recommendations")
    op.drop_index("ix_product_agent_recommendations_type",
                  table_name="product_agent_recommendations")
    op.drop_index("ix_product_agent_recommendations_merchant_id",
                  table_name="product_agent_recommendations")
    op.drop_index("ix_product_agent_recommendations_run_id",
                  table_name="product_agent_recommendations")
    op.drop_index("ix_product_agent_recommendations_id",
                  table_name="product_agent_recommendations")
    op.drop_table("product_agent_recommendations")

    op.drop_index("ix_pa_findings_run_type", table_name="product_agent_findings")
    op.drop_index("ix_product_agent_findings_severity",
                  table_name="product_agent_findings")
    op.drop_index("ix_product_agent_findings_type", table_name="product_agent_findings")
    op.drop_index("ix_product_agent_findings_merchant_id",
                  table_name="product_agent_findings")
    op.drop_index("ix_product_agent_findings_run_id", table_name="product_agent_findings")
    op.drop_index("ix_product_agent_findings_id", table_name="product_agent_findings")
    op.drop_table("product_agent_findings")

    op.drop_index("ix_pa_events_run_seq", table_name="product_agent_events")
    op.drop_index("ix_product_agent_events_event_type",
                  table_name="product_agent_events")
    op.drop_index("ix_product_agent_events_merchant_id",
                  table_name="product_agent_events")
    op.drop_index("ix_product_agent_events_run_id", table_name="product_agent_events")
    op.drop_index("ix_product_agent_events_id", table_name="product_agent_events")
    op.drop_table("product_agent_events")

    op.drop_index("ix_pa_runs_merchant_status", table_name="product_agent_runs")
    op.drop_index("ix_product_agent_runs_current_stage",
                  table_name="product_agent_runs")
    op.drop_index("ix_product_agent_runs_status", table_name="product_agent_runs")
    op.drop_index("ix_product_agent_runs_analysis_cycle_id",
                  table_name="product_agent_runs")
    op.drop_index("ix_product_agent_runs_merchant_id", table_name="product_agent_runs")
    op.drop_index("ix_product_agent_runs_id", table_name="product_agent_runs")
    op.drop_table("product_agent_runs")