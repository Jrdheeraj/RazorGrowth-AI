"""Recommendation model — human-in-the-loop growth recommendations."""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.app.models.enums import RecommendationStatus, RecommendationType

if TYPE_CHECKING:
    from backend.app.models.merchant import Merchant
    from backend.app.models.opportunity import GrowthOpportunity
    from backend.app.models.approval import Approval


class Recommendation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    A growth recommendation produced by the AI Growth Team.

    Every recommendation references an opportunity, includes evidence,
    guardrails, and requires human approval before execution.
    Immutable once approved — execution uses the approved version snapshot.
    """
    __tablename__ = "recommendations"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("growth_opportunities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Stable key for idempotent upserts
    recommendation_key: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )

    type: Mapped[RecommendationType] = mapped_column(
        String(50), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Core recommendation data
    proposed_action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_segment: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Evidence & confidence
    evidence: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    assumptions: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)

    # Impact estimates (always marked as estimates)
    expected_revenue: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    expected_conversion: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    # Guardrails
    guardrails: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    requires_approval: Mapped[bool] = mapped_column(nullable=False, default=True)

    # Version control
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approved_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Status & workflow
    status: Mapped[RecommendationStatus] = mapped_column(
        String(30),
        nullable=False,
        default=RecommendationStatus.draft,
        server_default=RecommendationStatus.draft.value,
        index=True,
    )

    # Snapshot of simulation at approval time
    simulation_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    merchant: Mapped[Merchant] = relationship("Merchant")
    opportunity: Mapped[GrowthOpportunity | None] = relationship("GrowthOpportunity")
    approval: Mapped["Approval"] = relationship(
        "Approval", back_populates="recommendation", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_recommendations_confidence_range",
        ),
        CheckConstraint(
            "expected_revenue >= 0",
            name="ck_recommendations_expected_revenue_non_negative",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_recommendations_version_positive",
        ),
        Index("ix_recommendations_merchant_status", "merchant_id", "status"),
        Index("ix_recommendations_merchant_key", "merchant_id", "recommendation_key", unique=True),
    )

    def __repr__(self) -> str:
        return f"<Recommendation id={self.id} type={self.type} status={self.status} v={self.version}>"