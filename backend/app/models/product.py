"""Product model."""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.app.models.enums import Currency

if TYPE_CHECKING:
    from backend.app.models.merchant import Merchant
    from backend.app.models.order import OrderItem


class Product(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    A product belonging to a merchant.

    Monetary values use Numeric(12, 2) — never float.
    SKU uniqueness is enforced per-merchant.
    """
    __tablename__ = "products"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    currency: Mapped[Currency] = mapped_column(
        String(3),
        nullable=False,
        default=Currency.INR,
        server_default=Currency.INR.value,
    )
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stock_quantity: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true", index=True
    )

    # ------------------------------------------------------------------ #
    # Relationships
    # ------------------------------------------------------------------ #
    merchant: Mapped[Merchant] = relationship("Merchant", back_populates="products")
    order_items: Mapped[list[OrderItem]] = relationship(
        "OrderItem", back_populates="product"
    )

    __table_args__ = (
        # Per-merchant SKU uniqueness (NULL SKUs are excluded from the constraint)
        UniqueConstraint("merchant_id", "sku", name="uq_products_merchant_sku"),
        CheckConstraint("price >= 0", name="ck_products_price_non_negative"),
        CheckConstraint("stock_quantity >= 0", name="ck_products_stock_non_negative"),
        # index=True on columns above already creates individual indexes;
        # no duplicate explicit Index() entries needed here.
    )

    def __repr__(self) -> str:
        return f"<Product id={self.id} sku={self.sku!r} name={self.name!r}>"
