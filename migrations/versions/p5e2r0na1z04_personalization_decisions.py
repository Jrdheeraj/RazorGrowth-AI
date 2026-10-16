"""personalization decisions — per-customer next-best action

Revision ID: p5e2r0na1z04
Revises: h4n0d0ff2a11
Create Date: 2026-10-14 20:05:00.000000

Stores one explainable next-best-action decision per (merchant, customer,
action), with a deterministic treatment/control cohort split so the effect of
a decision can be measured against a real holdout instead of assumed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "p5e2r0na1z04"
down_revision: Union[str, Sequence[str], None] = "h4n0d0ff2a11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "personalization_decisions",
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("recommended_action", sa.String(length=40), nullable=False),
        sa.Column(
            "cohort", sa.String(length=12), nullable=False, server_default="treatment"
        ),
        sa.Column(
            "score", sa.Numeric(precision=8, scale=5), nullable=False, server_default="0"
        ),
        sa.Column("rationale", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "recommended_product_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("assignment_key", sa.String(length=64), nullable=False),
        sa.Column("decision_key", sa.String(length=80), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="proposed"
        ),
        sa.Column("observed_revenue", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_personalization_decisions_merchant_id",
        "personalization_decisions",
        ["merchant_id"],
    )
    op.create_index(
        "ix_personalization_decisions_customer_id",
        "personalization_decisions",
        ["customer_id"],
    )
    op.create_index(
        "ix_personalization_decisions_recommended_action",
        "personalization_decisions",
        ["recommended_action"],
    )
    op.create_index(
        "ix_personalization_decisions_assignment_key",
        "personalization_decisions",
        ["assignment_key"],
    )
    op.create_index(
        "ix_personalization_decisions_decision_key",
        "personalization_decisions",
        ["decision_key"],
    )
    op.create_index(
        "ix_personalization_decisions_merchant_status",
        "personalization_decisions",
        ["merchant_id", "status"],
    )
    op.create_index(
        "uq_personalization_decision_key",
        "personalization_decisions",
        ["merchant_id", "decision_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_personalization_decision_key", table_name="personalization_decisions")
    op.drop_index(
        "ix_personalization_decisions_merchant_status",
        table_name="personalization_decisions",
    )
    op.drop_index(
        "ix_personalization_decisions_decision_key",
        table_name="personalization_decisions",
    )
    op.drop_index(
        "ix_personalization_decisions_assignment_key",
        table_name="personalization_decisions",
    )
    op.drop_index(
        "ix_personalization_decisions_recommended_action",
        table_name="personalization_decisions",
    )
    op.drop_index(
        "ix_personalization_decisions_customer_id",
        table_name="personalization_decisions",
    )
    op.drop_index(
        "ix_personalization_decisions_merchant_id",
        table_name="personalization_decisions",
    )
    op.drop_table("personalization_decisions")