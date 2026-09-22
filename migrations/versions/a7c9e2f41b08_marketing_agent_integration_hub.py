"""marketing agent integration hub

Revision ID: a7c9e2f41b08
Revises: e9d4a7c1b2f8
Create Date: 2026-09-21 00:00:00.000000

Per-workspace provider connections for the Marketing Agent integration
hub (email/Resend, Google Ads, Meta Ads, Instagram). Secrets are stored
ONLY as Fernet-encrypted blobs (see core/credential_vault.py) — this
table never holds plaintext tokens.

The legacy MarketingAgent and the 13-agent system are untouched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a7c9e2f41b08"
down_revision: Union[str, Sequence[str], None] = "e9d4a7c1b2f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "integration_connections",
        sa.Column("merchant_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("integration_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("account_id", sa.String(length=255), nullable=True),
        sa.Column("account_name", sa.String(length=255), nullable=True),
        sa.Column("encrypted_credentials", sa.Text(), nullable=True),
        sa.Column("connection_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merchant_id", "provider", name="uq_integration_conn_merchant_provider"),
    )
    op.create_index(op.f("ix_integration_connections_id"), "integration_connections", ["id"], unique=False)
    op.create_index(op.f("ix_integration_connections_merchant_id"), "integration_connections", ["merchant_id"], unique=False)
    op.create_index(op.f("ix_integration_connections_provider"), "integration_connections", ["provider"], unique=False)
    op.create_index(op.f("ix_integration_connections_status"), "integration_connections", ["status"], unique=False)
    op.create_index("ix_integration_conn_merchant_status", "integration_connections", ["merchant_id", "status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_integration_conn_merchant_status", table_name="integration_connections")
    op.drop_index(op.f("ix_integration_connections_status"), table_name="integration_connections")
    op.drop_index(op.f("ix_integration_connections_provider"), table_name="integration_connections")
    op.drop_index(op.f("ix_integration_connections_merchant_id"), table_name="integration_connections")
    op.drop_index(op.f("ix_integration_connections_id"), table_name="integration_connections")
    op.drop_table("integration_connections")
