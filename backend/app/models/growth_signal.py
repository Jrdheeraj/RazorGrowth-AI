"""GrowthSignal model — Phase 5 Growth Radar detections.

Every signal MUST reference real database evidence: metric name, current
value, comparison value, time window, and confidence. Signals are never
fabricated — the radar service only persists a signal when the underlying
SQL aggregate produces one.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.app.models.enums import GrowthSignalType, SignalStatus

if TYPE_CHECKING:
    from backend.app.models.merchant import Merchant


class GrowthSignal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A detected business signal produced deterministically from commerce data."""

    __tablename__ = "growth_signals"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Deterministic idempotency key:
    #   {signal_type}:{merchant_id}:{window_days}:{bucket}
    signal_key: Mapped[str] = mapped_column(String(200), nullable=False)
    signal_type: Mapped[GrowthSignalType] = mapped_column(
        String(60), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[SignalStatus] = mapped_column(
        String(20),
        nullable=False,
        default=SignalStatus.active,
        server_default=SignalStatus.active.value,
        index=True,
    )

    # Structured evidence (all values derived from real rows):
    metric: Mapped[str] = mapped_column(String(100), nullable=False)
    current_value: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    comparison_value: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    change_percentage: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, default=Decimal("0.5")
    )
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    detected_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)

    merchant: Mapped[Merchant] = relationship("Merchant", back_populates="growth_signals")

    __table_args__ = (
        Index("ix_growth_signals_merchant_key", "merchant_id", "signal_key", unique=True),
    )

    def __repr__(self) -> str:
        return f"<GrowthSignal {self.signal_type} key={self.signal_key}>"
