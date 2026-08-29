"""RecommendationRepository."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.app.models.recommendation import Recommendation
from backend.app.models.enums import RecommendationStatus
from backend.app.repositories.base import BaseRepository

if TYPE_CHECKING:
    from backend.app.models.approval import Approval


class RecommendationRepository(BaseRepository[Recommendation]):
    model = Recommendation

    def list_by_merchant(
        self,
        merchant_id: uuid.UUID,
        *,
        status: RecommendationStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Recommendation]:
        stmt = select(Recommendation).where(Recommendation.merchant_id == merchant_id)
        if status:
            stmt = stmt.where(Recommendation.status == status)
        stmt = stmt.order_by(Recommendation.created_at.desc()).limit(limit).offset(offset)
        return list(self.db.scalars(stmt).all())

    def get_by_key(self, merchant_id: uuid.UUID, recommendation_key: str) -> Recommendation | None:
        stmt = select(Recommendation).where(
            Recommendation.merchant_id == merchant_id,
            Recommendation.recommendation_key == recommendation_key,
        )
        return self.db.scalars(stmt).first()

    def get_with_approval(self, recommendation_id: uuid.UUID) -> Recommendation | None:
        stmt = (
            select(Recommendation)
            .options(selectinload(Recommendation.approval))
            .where(Recommendation.id == recommendation_id)
        )
        return self.db.scalars(stmt).first()

    def create(
        self,
        *,
        merchant_id: uuid.UUID,
        opportunity_id: uuid.UUID | None,
        recommendation_key: str | None,
        type: str,
        title: str,
        description: str | None,
        proposed_action: str,
        target_segment: str | None,
        rationale: str | None,
        evidence: list | None,
        confidence: float,
        assumptions: list | None,
        expected_revenue: float,
        expected_conversion: float | None,
        estimated_cost: float | None,
        guardrails: dict | None,
        requires_approval: bool,
        version: int = 1,
        simulation_snapshot: dict | None = None,
    ) -> Recommendation:
        rec = Recommendation(
            merchant_id=merchant_id,
            opportunity_id=opportunity_id,
            recommendation_key=recommendation_key,
            type=type,
            title=title,
            description=description,
            proposed_action=proposed_action,
            target_segment=target_segment,
            rationale=rationale,
            evidence=evidence,
            confidence=confidence,
            assumptions=assumptions,
            expected_revenue=expected_revenue,
            expected_conversion=expected_conversion,
            estimated_cost=estimated_cost,
            guardrails=guardrails,
            requires_approval=requires_approval,
            version=version,
            simulation_snapshot=simulation_snapshot,
            status=RecommendationStatus.draft,
        )
        return self.add(rec)

    def increment_version(self, recommendation_id: uuid.UUID) -> Recommendation | None:
        rec = self.get_by_id(recommendation_id)
        if rec:
            rec.version += 1
            rec.status = RecommendationStatus.draft
            self.db.flush()
        return rec