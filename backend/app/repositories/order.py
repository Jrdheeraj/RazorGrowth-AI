"""OrderRepository."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.app.models.order import Order, OrderItem
from backend.app.models.enums import OrderStatus
from backend.app.repositories.base import BaseRepository


class OrderRepository(BaseRepository[Order]):
    model = Order

    def list_by_merchant(
        self,
        merchant_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Order]:
        stmt = (
            select(Order)
            .where(Order.merchant_id == merchant_id)
            .options(selectinload(Order.items))
            .order_by(Order.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.scalars(stmt).all())

    def list_by_customer(self, customer_id: uuid.UUID) -> list[Order]:
        stmt = (
            select(Order)
            .where(Order.customer_id == customer_id)
            .options(selectinload(Order.items))
            .order_by(Order.created_at.desc())
        )
        return list(self.db.scalars(stmt).all())

    def list_by_status(
        self, merchant_id: uuid.UUID, status: OrderStatus
    ) -> list[Order]:
        stmt = (
            select(Order)
            .where(
                Order.merchant_id == merchant_id,
                Order.status == status,
            )
            .order_by(Order.created_at.desc())
        )
        return list(self.db.scalars(stmt).all())

    def get_customer_ids_for_product(
        self, merchant_id: uuid.UUID, product_id: uuid.UUID
    ) -> set[uuid.UUID]:
        """Return the set of customer IDs who have purchased the given product."""
        stmt = (
            select(Order.customer_id)
            .join(OrderItem, OrderItem.order_id == Order.id)
            .where(
                Order.merchant_id == merchant_id,
                OrderItem.product_id == product_id,
            )
            .distinct()
        )
        return set(self.db.scalars(stmt).all())
