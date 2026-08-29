"""PaymentService."""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.models.payment import Payment
from backend.app.repositories.payment import PaymentRepository
from backend.app.core.logging import get_logger

log = get_logger(__name__)


class PaymentService:
    def __init__(self, db: Session) -> None:
        self._repo = PaymentRepository(db)
        self._db = db

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

    def get_payment_by_merchant(self, merchant_id: uuid.UUID, payment_id: uuid.UUID) -> Payment | None:
        payment = self._repo.get_by_id(payment_id)
        if payment and payment.merchant_id == merchant_id:
            return payment
        return None

    def create_payment(
        self,
        *,
        merchant_id: uuid.UUID,
        order_id: uuid.UUID,
        provider: str = "synthetic",
        provider_payment_id: str | None = None,
        amount: Decimal,
        currency: str = "INR",
        status: str = "pending",
        failure_code: str | None = None,
        failure_reason: str | None = None,
    ) -> Payment:
        payment = Payment(
            merchant_id=merchant_id,
            order_id=order_id,
            provider=provider,
            provider_payment_id=provider_payment_id,
            amount=amount,
            currency=currency,
            status=status,
            failure_code=failure_code,
            failure_reason=failure_reason,
        )
        self._db.add(payment)
        self._db.flush()
        log.info("Payment created. id=%s merchant=%s order=%s amount=%s", str(payment.id), merchant_id, order_id, amount)
        return payment

    def update_payment(
        self,
        payment_id: uuid.UUID,
        *,
        provider_payment_id: str | None = None,
        status: str | None = None,
        failure_code: str | None = None,
        failure_reason: str | None = None,
    ) -> Payment | None:
        payment = self._repo.get_by_id(payment_id)
        if not payment:
            return None

        if provider_payment_id is not None:
            payment.provider_payment_id = provider_payment_id
        if status is not None:
            payment.status = status
        if failure_code is not None:
            payment.failure_code = failure_code
        if failure_reason is not None:
            payment.failure_reason = failure_reason

        self._db.flush()
        log.info("Payment updated. id=%s", str(payment_id))
        return payment

    def delete_payment(self, payment_id: uuid.UUID) -> bool:
        payment = self._repo.get_by_id(payment_id)
        if not payment:
            return False

        self._repo.delete(payment)
        self._db.flush()
        log.info("Payment deleted. id=%s", str(payment_id))
        return True

    def list_failed_payments(self, merchant_id: uuid.UUID) -> list[Payment]:
        return self._repo.list_failed_by_merchant(merchant_id)
