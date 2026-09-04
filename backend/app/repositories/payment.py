"""PaymentRepository."""
from __future__ import annotations

import uuid

from sqlalchemy import select

from backend.app.models.payment import Payment
from backend.app.models.enums import PaymentStatus
from backend.app.repositories.base import BaseRepository


class PaymentRepository(BaseRepository[Payment]):
    model = Payment

    def list_by_merchant(
        self,
        merchant_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Payment]:
        stmt = (
            select(Payment)
            .where(Payment.merchant_id == merchant_id)
            .order_by(Payment.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.scalars(stmt).all())

    def list_failed_by_merchant(self, merchant_id: uuid.UUID) -> list[Payment]:
        stmt = (
            select(Payment)
            .where(
                Payment.merchant_id == merchant_id,
                Payment.status == PaymentStatus.failed,
            )
            .order_by(Payment.created_at.desc())
        )
        return list(self.db.scalars(stmt).all())

    def list_by_order(self, order_id: uuid.UUID) -> list[Payment]:
        stmt = (
            select(Payment)
            .where(Payment.order_id == order_id)
            .order_by(Payment.created_at.desc())
        )
        return list(self.db.scalars(stmt).all())

    def get_by_provider_payment_id(self, merchant_id: uuid.UUID, provider_payment_id: str) -> Payment | None:
        stmt = select(Payment).where(
            Payment.merchant_id == merchant_id,
            Payment.provider_payment_id == provider_payment_id,
        )
        return self.db.execute(stmt).scalar_one_or_none()
