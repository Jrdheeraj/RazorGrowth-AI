"""CustomerService."""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from backend.app.models.customer import Customer
from backend.app.repositories.customer import CustomerRepository
from backend.app.core.logging import get_logger

log = get_logger(__name__)


class CustomerService:
    def __init__(self, db: Session) -> None:
        self._repo = CustomerRepository(db)

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
