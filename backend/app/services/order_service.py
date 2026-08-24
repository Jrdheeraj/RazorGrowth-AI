"""OrderService."""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from backend.app.models.order import Order
from backend.app.repositories.order import OrderRepository
from backend.app.core.logging import get_logger

log = get_logger(__name__)


class OrderService:
    def __init__(self, db: Session) -> None:
        self._repo = OrderRepository(db)

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
