"""CustomerRepository."""
from __future__ import annotations

import uuid

from sqlalchemy import select

from backend.app.models.customer import Customer
from backend.app.models.enums import CustomerSegment
from backend.app.repositories.base import BaseRepository


class CustomerRepository(BaseRepository[Customer]):
    model = Customer

    def list_by_merchant(
        self,
        merchant_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Customer]:
        stmt = (
            select(Customer)
            .where(Customer.merchant_id == merchant_id)
            .order_by(Customer.name)
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.scalars(stmt).all())

    def get_by_email(self, merchant_id: uuid.UUID, email: str) -> Customer | None:
        stmt = select(Customer).where(
            Customer.merchant_id == merchant_id,
            Customer.email == email,
        )
        return self.db.scalars(stmt).first()

    def list_by_segment(
        self, merchant_id: uuid.UUID, segment: CustomerSegment
    ) -> list[Customer]:
        stmt = (
            select(Customer)
            .where(
                Customer.merchant_id == merchant_id,
                Customer.segment == segment,
            )
            .order_by(Customer.total_spend.desc())
        )
        return list(self.db.scalars(stmt).all())

    def list_high_value_returning(
        self, merchant_id: uuid.UUID, min_orders: int = 3, limit: int = 50
    ) -> list[Customer]:
        stmt = (
            select(Customer)
            .where(
                Customer.merchant_id == merchant_id,
                Customer.segment == CustomerSegment.returning,
                Customer.total_orders >= min_orders,
            )
            .order_by(Customer.total_spend.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())

    def create(
        self,
        *,
        merchant_id: uuid.UUID,
        name: str,
        email: str,
        phone: str | None = None,
        segment: CustomerSegment = CustomerSegment.new,
    ) -> Customer:
        customer = Customer(
            merchant_id=merchant_id,
            name=name,
            email=email,
            phone=phone,
            segment=segment,
        )
        return self.add(customer)
