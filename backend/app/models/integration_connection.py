"""IntegrationConnection persistence — the Marketing Agent integration hub.

One row per (merchant, provider). Holds ONLY encrypted credential blobs
(Fernet, see core/credential_vault) plus safe, displayable metadata:
account identity, capabilities, verification timestamps. Secrets are never
stored in plaintext and never leave the backend except inside provider
HTTPS calls made server-side.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IntegrationConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A merchant's connection to one external marketing provider."""

    __tablename__ = "integration_connections"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Provider key: resend | google_ads | meta_ads | instagram
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    # Integration family: email | ads | social
    integration_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # Lifecycle: connected | error | disconnected
    # "connected" is set ONLY after a successful live verification call.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="disconnected", index=True
    )
    # Safe, displayable account identity (no secrets, ever).
    account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Fernet-encrypted JSON blob of credentials ("vault1:..." prefix).
    encrypted_credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Safe non-secret metadata: sender identity, scopes, token expiry,
    # developer-token presence flag (never the token itself), etc.
    connection_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    # Declared provider capabilities (read/write lists for the UI).
    capabilities: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    merchant = relationship("Merchant")

    __table_args__ = (
        UniqueConstraint(
            "merchant_id", "provider", name="uq_integration_conn_merchant_provider"
        ),
        Index("ix_integration_conn_merchant_status", "merchant_id", "status"),
    )
