"""Add marketing-email consent suppression to ``customers``.

WHY
---
The campaign executor resolved recipients straight from ``Customer.email``
with no consent check, so an approved campaign would have mailed a customer
who had opted out. Nothing recorded that choice, so it could not be enforced.

``email_opt_out`` is the suppression flag the executor filters on. It is
NULLABLE and defaults to ``false`` rather than defaulting to "opted out":
defaulting a suppression flag to True would silently stop every existing
campaign the moment this migration ran, which is a data-loss-shaped
surprise, not a safe default.

``email_opt_out_at`` records WHEN the decision was made so a consent change
is auditable rather than invisible.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c4a1f9e2b770"
down_revision = "b7e2d4c19a55"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column(
            "email_opt_out",
            sa.Boolean(),
            nullable=True,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "customers",
        sa.Column("email_opt_out_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_customers_email_opt_out", "customers", ["email_opt_out"]
    )


def downgrade() -> None:
    op.drop_index("ix_customers_email_opt_out", table_name="customers")
    op.drop_column("customers", "email_opt_out_at")
    op.drop_column("customers", "email_opt_out")