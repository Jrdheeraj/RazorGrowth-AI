"""Customer model."""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.app.models.enums import CustomerSegment

if TYPE_CHECKING:
    from backend.app.models.merchant import Merchant
    from backend.app.models.order import Order
    from backend.app.models.customer_insight import CustomerInsight


class Customer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    A customer who has placed orders with a merchant.

    Email uniqueness is enforced per-merchant so the same person can
    shop at multiple merchants on the platform.
    """
    __tablename__ = "customers"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    segment: Mapped[CustomerSegment] = mapped_column(
        String(20),
        nullable=False,
        default=CustomerSegment.new,
        server_default=CustomerSegment.new.value,
        index=True,
    )
    total_orders: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    total_spend: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )

    # ------------------------------------------------------------------ #
    # Relationships
    # ------------------------------------------------------------------ #
    merchant: Mapped[Merchant] = relationship("Merchant", back_populates="customers")
    orders: Mapped[list[Order]] = relationship(
        "Order", back_populates="customer"
    )
    insights: Mapped[list[CustomerInsight]] = relationship(
        "CustomerInsight", back_populates="customer", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("merchant_id", "email", name="uq_customers_merchant_email"),
        CheckConstraint("total_orders >= 0", name="ck_customers_total_orders_non_negative"),
        CheckConstraint("total_spend >= 0", name="ck_customers_total_spend_non_negative"),
    )

    def __repr__(self) -> str:
        return f"<Customer id={self.id} email={self.email!r}>"
