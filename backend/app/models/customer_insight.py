"""CustomerInsight model — Phase 5 customer intelligence + churn risk.

Metrics are computed with deterministic SQL aggregates; the LLM may add a
human-readable strategy but never supplies the numbers.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.app.models.enums import ChurnRiskLevel, InsightType

if TYPE_CHECKING:
    from backend.app.models.customer import Customer
    from backend.app.models.merchant import Merchant


class CustomerInsight(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Deterministic intelligence record for one customer of one merchant.

    insight_key = sha256(merchant_id:customer_id) → idempotent refreshes.
    """

    __tablename__ = "customer_insights"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    insight_key: Mapped[str] = mapped_column(String(120), nullable=False)

    primary_segment: Mapped[InsightType] = mapped_column(String(40), nullable=False)
    segments: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)

    # Deterministic metrics (real data only)
    order_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lifetime_value: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=0
    )
    avg_order_value: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=0
    )
    recency_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_interval_days: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    payment_success_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, default=0
    )
    failed_payment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Churn engine output (deterministic heuristics)
    churn_risk_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=0
    )
    churn_risk_level: Mapped[ChurnRiskLevel] = mapped_column(
        String(20), nullable=False, default=ChurnRiskLevel.minimal.value
    )
    churn_reasons: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    churn_evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Optional LLM interpretation (never numeric truth)
    strategy_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    customer: Mapped[Customer] = relationship("Customer", back_populates="insights")
    merchant: Mapped["Merchant"] = relationship(
        "Merchant", foreign_keys=[merchant_id], back_populates="customer_insights"
    )

    __table_args__ = (
        Index(
            "ix_customer_insights_merchant_customer",
            "merchant_id",
            "customer_id",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<CustomerInsight customer={self.customer_id} "
            f"segment={self.primary_segment} churn={self.churn_risk_score}>"
        )
