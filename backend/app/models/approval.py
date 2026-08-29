"""Approval model — human approval state machine for recommendations."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, UUIDPrimaryKeyMixin
from backend.app.models.enums import RecommendationStatus

if TYPE_CHECKING:
    from backend.app.models.merchant import Merchant
    from backend.app.models.recommendation import Recommendation
    from backend.app.models.user import User


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Approval(UUIDPrimaryKeyMixin, Base):
    """
    Human approval record for a recommendation.

    Immutable once created — tracks the complete approval lifecycle.
    Only authorized humans (owner/admin) can approve/reject.
    """
    __tablename__ = "approvals"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recommendations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Approval state machine
    status: Mapped[RecommendationStatus] = mapped_column(
        String(30),
        nullable=False,
        default=RecommendationStatus.pending_approval,
        server_default=RecommendationStatus.pending_approval.value,
        index=True,
    )

    # Human actor (never an agent)
    approver_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    approver_email: Mapped[str | None] = mapped_column(String(320), nullable=True)

    # Decision details
    decision: Mapped[str | None] = mapped_column(String(30), nullable=True)  # approved/rejected/changes_requested
    comment: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Snapshots at decision time (immutable)
    recommendation_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    simulation_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Version of recommendation that was approved
    approved_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Timestamps (no updated_at — immutable)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )

    # Relationships
    merchant: Mapped[Merchant] = relationship("Merchant")
    recommendation: Mapped[Recommendation] = relationship(
        "Recommendation", back_populates="approval"
    )
    approver: Mapped[User | None] = relationship("User", foreign_keys=[approver_user_id])

    __table_args__ = (
        Index("ix_approvals_merchant_status", "merchant_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<Approval id={self.id} rec={self.recommendation_id} status={self.status}>"