"""ApprovalRepository."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.app.models.approval import Approval
from backend.app.models.enums import RecommendationStatus
from backend.app.repositories.base import BaseRepository


class ApprovalRepository(BaseRepository[Approval]):
    model = Approval

    def list_by_merchant(
        self,
        merchant_id: uuid.UUID,
        *,
        status: RecommendationStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Approval]:
        stmt = select(Approval).where(Approval.merchant_id == merchant_id)
        if status:
            stmt = stmt.where(Approval.status == status)
        stmt = stmt.order_by(Approval.created_at.desc()).limit(limit).offset(offset)
        return list(self.db.scalars(stmt).all())

    def get_by_recommendation(self, recommendation_id: uuid.UUID) -> Approval | None:
        stmt = select(Approval).where(Approval.recommendation_id == recommendation_id)
        return self.db.scalars(stmt).first()

    def get_with_recommendation(self, approval_id: uuid.UUID) -> Approval | None:
        stmt = (
            select(Approval)
            .options(selectinload(Approval.recommendation))
            .where(Approval.id == approval_id)
        )
        return self.db.scalars(stmt).first()

    def create(
        self,
        *,
        merchant_id: uuid.UUID,
        recommendation_id: uuid.UUID,
        status: RecommendationStatus = RecommendationStatus.pending_approval,
    ) -> Approval:
        approval = Approval(
            merchant_id=merchant_id,
            recommendation_id=recommendation_id,
            status=status,
        )
        return self.add(approval)