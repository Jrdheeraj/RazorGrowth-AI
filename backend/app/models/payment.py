"""Payment model — ready for Razorpay integration in Phase 3."""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.app.models.enums import Currency, PaymentProvider, PaymentStatus

if TYPE_CHECKING:
    from backend.app.models.merchant import Merchant
    from backend.app.models.order import Order


class Payment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    A payment attempt for an order.

    provider_payment_id is nullable because synthetic/seed payments have
    no real provider ID. It will be set by the Razorpay adapter in Phase 3.
    """
    __tablename__ = "payments"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider: Mapped[PaymentProvider] = mapped_column(
        String(30),
        nullable=False,
        default=PaymentProvider.synthetic,
        server_default=PaymentProvider.synthetic.value,
    )
    # Nullable — will be set when provider confirms payment
    provider_payment_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[Currency] = mapped_column(
        String(3),
        nullable=False,
        default=Currency.INR,
        server_default=Currency.INR.value,
    )
    status: Mapped[PaymentStatus] = mapped_column(
        String(20),
        nullable=False,
        default=PaymentStatus.pending,
        server_default=PaymentStatus.pending.value,
        index=True,
    )
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_at: Mapped[uuid.UUID | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ------------------------------------------------------------------ #
    # Relationships
    # ------------------------------------------------------------------ #
    merchant: Mapped[Merchant] = relationship("Merchant", back_populates="payments")
    order: Mapped[Order] = relationship("Order", back_populates="payments")

    __table_args__ = ()  # index=True on columns handles all individual indexes

    def __repr__(self) -> str:
        return f"<Payment id={self.id} status={self.status} amount={self.amount}>"
