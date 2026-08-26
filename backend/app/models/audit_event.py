"""
AuditEvent model — immutable append-only event log.

Audit events must never be updated in normal application flow.
They form the authoritative history of every significant action.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, UUIDPrimaryKeyMixin
from backend.app.models.enums import ActorType, AuditEventType

if TYPE_CHECKING:
    from backend.app.models.merchant import Merchant


def _utcnow() -> datetime:
    """Python-side UTC default — works on both PostgreSQL and SQLite."""
    return datetime.now(timezone.utc)


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    """
    Immutable audit log entry.

    No updated_at — these records must never change.
    created_at is the authoritative event timestamp.

    Uses a Python-side default (datetime.now(timezone.utc)) in addition to
    server_default=func.now() so that SQLite (test environment) receives an
    actual datetime object rather than the literal string 'now()'.
    """
    __tablename__ = "audit_events"

    # Phase 6: nullable to allow platform-level events (e.g. Razorpay
    # webhook deliveries) that are not attributable to a single merchant.
    merchant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    actor_type: Mapped[ActorType] = mapped_column(String(30), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_type: Mapped[AuditEventType] = mapped_column(
        String(60), nullable=False, index=True
    )
    entity_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Python-side default ensures SQLite gets a real datetime; PostgreSQL uses
    # server_default=func.now() for DB-generated timestamps on bulk inserts.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )

    # ------------------------------------------------------------------ #
    # Relationships
    # ------------------------------------------------------------------ #
    merchant: Mapped[Merchant] = relationship(
        "Merchant", back_populates="audit_events"
    )

    __table_args__ = (
        Index("ix_audit_events_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<AuditEvent id={self.id} event_type={self.event_type} "
            f"actor={self.actor_type}>"
        )
