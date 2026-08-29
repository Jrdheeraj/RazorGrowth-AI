"""GrowthOpportunity model."""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    Enum,
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
from backend.app.models.enums import OpportunityStatus, OpportunityType

if TYPE_CHECKING:
    from backend.app.models.merchant import Merchant
    from backend.app.models.campaign import Campaign
    from backend.app.models.agent_action import AgentAction


class GrowthOpportunity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    An AI- or rule-generated growth opportunity for a merchant.

    reasoning is stored as JSONB so structured lists of insights can be
    queried without deserialising application-side.
    """
    __tablename__ = "growth_opportunities"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Stable deterministic key — allows idempotent upserts
    opportunity_key: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    type: Mapped[OpportunityType] = mapped_column(
        Enum(OpportunityType, native_enum=False, validate_strings=True),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    expected_revenue: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    target_customer_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # JSON list of reasoning strings / structured objects
    reasoning: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[OpportunityStatus] = mapped_column(
        Enum(OpportunityStatus, native_enum=False, validate_strings=True),
        nullable=False,
        default=OpportunityStatus.pending_approval,
        server_default=OpportunityStatus.pending_approval.value,
        index=True,
    )

    # ------------------------------------------------------------------ #
    # Relationships
    # ------------------------------------------------------------------ #
    merchant: Mapped[Merchant] = relationship(
        "Merchant", back_populates="opportunities"
    )
    campaigns: Mapped[list[Campaign]] = relationship(
        "Campaign", back_populates="opportunity"
    )
    agent_actions: Mapped[list[AgentAction]] = relationship(
        "AgentAction", back_populates="opportunity"
    )

    __table_args__ = (
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_opportunities_confidence_range",
        ),
        CheckConstraint(
            "expected_revenue >= 0",
            name="ck_opportunities_expected_revenue_non_negative",
        ),
        CheckConstraint(
            "target_customer_count >= 0",
            name="ck_opportunities_target_count_non_negative",
        ),
    )

    def __repr__(self) -> str:
        return f"<GrowthOpportunity id={self.id} type={self.type} status={self.status}>"
