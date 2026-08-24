"""Campaign model."""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.app.models.enums import CampaignStatus, CampaignType

if TYPE_CHECKING:
    from backend.app.models.merchant import Merchant
    from backend.app.models.opportunity import GrowthOpportunity


class Campaign(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An AI-generated or merchant-created marketing campaign."""
    __tablename__ = "campaigns"

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
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[CampaignType] = mapped_column(
        String(30), nullable=False, index=True
    )
    status: Mapped[CampaignStatus] = mapped_column(
        String(20),
        nullable=False,
        default=CampaignStatus.draft,
        server_default=CampaignStatus.draft.value,
        index=True,
    )
    target_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    estimated_revenue: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    actual_revenue: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    starts_at: Mapped[uuid.UUID | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ends_at: Mapped[uuid.UUID | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ------------------------------------------------------------------ #
    # Relationships
    # ------------------------------------------------------------------ #
    merchant: Mapped[Merchant] = relationship("Merchant", back_populates="campaigns")
    opportunity: Mapped[GrowthOpportunity | None] = relationship(
        "GrowthOpportunity", back_populates="campaigns"
    )

    __table_args__ = (
        # FK columns use index=True; no duplicate Index() entries needed.
    )

    def __repr__(self) -> str:
        return f"<Campaign id={self.id} name={self.name!r} status={self.status}>"
