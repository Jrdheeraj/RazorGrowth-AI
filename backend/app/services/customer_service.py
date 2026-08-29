"""CustomerService."""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.customer import Customer
from backend.app.models.enums import CustomerSegment
from backend.app.repositories.customer import CustomerRepository
from backend.app.core.logging import get_logger

log = get_logger(__name__)


class CustomerService:
    def __init__(self, db: Session) -> None:
        self._repo = CustomerRepository(db)
        self._db = db

    def list_customers(
        self,
        merchant_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Customer]:
        return self._repo.list_by_merchant(
            merchant_id, limit=limit, offset=offset
        )

    def get_customer(self, customer_id: uuid.UUID) -> Customer | None:
        return self._repo.get_by_id(customer_id)

    def get_customer_by_merchant(self, merchant_id: uuid.UUID, customer_id: uuid.UUID) -> Customer | None:
        customer = self._repo.get_by_id(customer_id)
        if customer and customer.merchant_id == merchant_id:
            return customer
        return None

    def create_customer(
        self,
        *,
        merchant_id: uuid.UUID,
        name: str,
        email: str,
        phone: str | None = None,
        segment: CustomerSegment = CustomerSegment.new,
    ) -> Customer:
        # Check for duplicate email
        existing = self._repo.get_by_email(merchant_id, email)
        if existing:
            raise ValueError(f"Customer with email {email} already exists for this merchant")

        customer = self._repo.create(
            merchant_id=merchant_id,
            name=name,
            email=email,
            phone=phone,
            segment=segment,
        )
        self._db.flush()
        log.info("Customer created. id=%s merchant=%s email=%s", str(customer.id), merchant_id, email)
        return customer

    def update_customer(
        self,
        customer_id: uuid.UUID,
        *,
        name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        segment: CustomerSegment | None = None,
    ) -> Customer | None:
        customer = self._repo.get_by_id(customer_id)
        if not customer:
            return None

        if email is not None and email != customer.email:
            existing = self._repo.get_by_email(customer.merchant_id, email)
            if existing:
                raise ValueError(f"Customer with email {email} already exists for this merchant")
            customer.email = email

        if name is not None:
            customer.name = name
        if phone is not None:
            customer.phone = phone
        if segment is not None:
            customer.segment = segment

        self._db.flush()
        log.info("Customer updated. id=%s", str(customer_id))
        return customer

    def delete_customer(self, customer_id: uuid.UUID) -> bool:
        customer = self._repo.get_by_id(customer_id)
        if not customer:
            return False

        # Check if customer has orders
        if customer.orders:
            raise ValueError("Cannot delete customer with existing orders")

        self._repo.delete(customer)
        self._db.flush()
        log.info("Customer deleted. id=%s", str(customer_id))
        return True
