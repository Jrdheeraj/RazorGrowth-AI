"""Order and OrderItem models."""
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
from backend.app.models.enums import Currency, OrderStatus

if TYPE_CHECKING:
    from backend.app.models.merchant import Merchant
    from backend.app.models.customer import Customer
    from backend.app.models.product import Product
    from backend.app.models.payment import Payment


class Order(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    A customer order placed with a merchant.

    Monetary columns use Numeric(14, 2) — never float.
    order_number uniqueness is enforced per-merchant.
    """
    __tablename__ = "orders"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    order_number: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        String(20),
        nullable=False,
        default=OrderStatus.pending,
        server_default=OrderStatus.pending.value,
        index=True,
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    discount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    tax: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[Currency] = mapped_column(
        String(3),
        nullable=False,
        default=Currency.INR,
        server_default=Currency.INR.value,
    )

    # ------------------------------------------------------------------ #
    # Relationships
    # ------------------------------------------------------------------ #
    merchant: Mapped[Merchant] = relationship("Merchant", back_populates="orders")
    customer: Mapped[Customer] = relationship("Customer", back_populates="orders")
    items: Mapped[list[OrderItem]] = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )
    payments: Mapped[list[Payment]] = relationship(
        "Payment", back_populates="order"
    )

    __table_args__ = (
        UniqueConstraint("merchant_id", "order_number", name="uq_orders_merchant_order_number"),
        CheckConstraint("subtotal >= 0", name="ck_orders_subtotal_non_negative"),
        CheckConstraint("discount >= 0", name="ck_orders_discount_non_negative"),
        CheckConstraint("tax >= 0", name="ck_orders_tax_non_negative"),
        CheckConstraint("total >= 0", name="ck_orders_total_non_negative"),
    )

    def __repr__(self) -> str:
        return f"<Order id={self.id} order_number={self.order_number!r} status={self.status}>"


class OrderItem(UUIDPrimaryKeyMixin, Base):
    """
    A single line item within an order.

    unit_price captures the price at purchase time — independent of any
    future product price changes.
    """
    __tablename__ = "order_items"

    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    # ------------------------------------------------------------------ #
    # Relationships
    # ------------------------------------------------------------------ #
    order: Mapped[Order] = relationship("Order", back_populates="items")
    product: Mapped[Product] = relationship("Product", back_populates="order_items")

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="ck_order_items_unit_price_non_negative"),
        CheckConstraint("line_total >= 0", name="ck_order_items_line_total_non_negative"),
    )

    def __repr__(self) -> str:
        return (
            f"<OrderItem id={self.id} product_id={self.product_id} qty={self.quantity}>"
        )
