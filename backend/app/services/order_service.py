"""OrderService."""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from backend.app.models.order import Order, OrderItem
from backend.app.models.enums import OrderStatus
from backend.app.repositories.order import OrderRepository
from backend.app.core.logging import get_logger

log = get_logger(__name__)


class OrderService:
    def __init__(self, db: Session) -> None:
        self._repo = OrderRepository(db)
        self._db = db

    def list_orders(
        self,
        merchant_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Order]:
        return self._repo.list_by_merchant(
            merchant_id, limit=limit, offset=offset
        )

    def get_order(self, order_id: uuid.UUID) -> Order | None:
        return self._repo.get_by_id(order_id)

    def get_order_by_merchant(self, merchant_id: uuid.UUID, order_id: uuid.UUID) -> Order | None:
        order = self._repo.get_by_id(order_id)
        if order and order.merchant_id == merchant_id:
            return order
        return None

    def create_order(
        self,
        *,
        merchant_id: uuid.UUID,
        customer_id: uuid.UUID,
        order_number: str,
        status: OrderStatus = OrderStatus.pending,
        subtotal: Decimal,
        discount: Decimal = Decimal("0.00"),
        tax: Decimal = Decimal("0.00"),
        total: Decimal,
        currency: str = "INR",
        items: list[dict[str, Any]],
    ) -> Order:
        # Check for duplicate order_number
        existing = self._db.execute(
            select(Order).where(
                Order.merchant_id == merchant_id,
                Order.order_number == order_number,
            )
        ).scalar_one_or_none()
        if existing:
            raise ValueError(f"Order with number {order_number} already exists for this merchant")

        order = Order(
            merchant_id=merchant_id,
            customer_id=customer_id,
            order_number=order_number,
            status=status,
            subtotal=subtotal,
            discount=discount,
            tax=tax,
            total=total,
            currency=currency,
        )
        self._db.add(order)
        self._db.flush()

        # Create order items
        for item_data in items:
            item = OrderItem(
                order_id=order.id,
                product_id=item_data["product_id"],
                quantity=item_data["quantity"],
                unit_price=item_data["unit_price"],
                line_total=item_data["line_total"],
            )
            self._db.add(item)

        self._db.flush()
        log.info("Order created. id=%s merchant=%s order_number=%s", str(order.id), merchant_id, order_number)
        return order

    def update_order(
        self,
        order_id: uuid.UUID,
        *,
        status: OrderStatus | None = None,
        subtotal: Decimal | None = None,
        discount: Decimal | None = None,
        tax: Decimal | None = None,
        total: Decimal | None = None,
        items: list[dict[str, Any]] | None = None,
    ) -> Order | None:
        order = self._repo.get_by_id(order_id)
        if not order:
            return None

        if status is not None:
            order.status = status
        if subtotal is not None:
            order.subtotal = subtotal
        if discount is not None:
            order.discount = discount
        if tax is not None:
            order.tax = tax
        if total is not None:
            order.total = total

        if items is not None:
            # Delete existing items
            for item in order.items:
                self._db.delete(item)
            self._db.flush()

            # Create new items
            for item_data in items:
                item = OrderItem(
                    order_id=order.id,
                    product_id=item_data["product_id"],
                    quantity=item_data["quantity"],
                    unit_price=item_data["unit_price"],
                    line_total=item_data["line_total"],
                )
                self._db.add(item)

        self._db.flush()
        log.info("Order updated. id=%s", str(order_id))
        return order

    def delete_order(self, order_id: uuid.UUID) -> bool:
        order = self._repo.get_by_id(order_id)
        if not order:
            return False

        # Delete order items first (cascade should handle this, but be explicit)
        for item in order.items:
            self._db.delete(item)

        self._repo.delete(order)
        self._db.flush()
        log.info("Order deleted. id=%s", str(order_id))
        return True


from sqlalchemy import select
