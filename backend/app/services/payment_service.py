"""PaymentService."""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from backend.app.models.payment import Payment
from backend.app.repositories.payment import PaymentRepository
from backend.app.core.logging import get_logger

log = get_logger(__name__)


class PaymentService:
    def __init__(self, db: Session) -> None:
        self._repo = PaymentRepository(db)

    def list_payments(
        self,
        merchant_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Payment]:
        return self._repo.list_by_merchant(
            merchant_id, limit=limit, offset=offset
        )

    def get_payment(self, payment_id: uuid.UUID) -> Payment | None:
        return self._repo.get_by_id(payment_id)

    def list_failed_payments(self, merchant_id: uuid.UUID) -> list[Payment]:
        return self._repo.list_failed_by_merchant(merchant_id)
