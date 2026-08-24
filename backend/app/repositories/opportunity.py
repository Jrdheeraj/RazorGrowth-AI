"""GrowthOpportunityRepository."""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from backend.app.models.opportunity import GrowthOpportunity
from backend.app.models.enums import OpportunityStatus, OpportunityType
from backend.app.repositories.base import BaseRepository


class GrowthOpportunityRepository(BaseRepository[GrowthOpportunity]):
    model = GrowthOpportunity

    def list_by_merchant(
        self,
        merchant_id: uuid.UUID,
        *,
        status: OpportunityStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[GrowthOpportunity]:
        stmt = (
            select(GrowthOpportunity)
            .where(GrowthOpportunity.merchant_id == merchant_id)
            .order_by(GrowthOpportunity.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if status:
            stmt = stmt.where(GrowthOpportunity.status == status)
        return list(self.db.scalars(stmt).all())

    def get_by_key(
        self, merchant_id: uuid.UUID, opportunity_key: str
    ) -> GrowthOpportunity | None:
        stmt = select(GrowthOpportunity).where(
            GrowthOpportunity.merchant_id == merchant_id,
            GrowthOpportunity.opportunity_key == opportunity_key,
        )
        return self.db.scalars(stmt).first()

    def create(
        self,
        *,
        merchant_id: uuid.UUID,
        opportunity_key: str,
        type: OpportunityType,
        title: str,
        description: str | None = None,
        confidence: Decimal,
        expected_revenue: Decimal,
        target_customer_count: int,
        reasoning: list[Any] | None = None,
        status: OpportunityStatus = OpportunityStatus.pending_approval,
    ) -> GrowthOpportunity:
        opp = GrowthOpportunity(
            merchant_id=merchant_id,
            opportunity_key=opportunity_key,
            type=type,
            title=title,
            description=description,
            confidence=confidence,
            expected_revenue=expected_revenue,
            target_customer_count=target_customer_count,
            reasoning=reasoning,
            status=status,
        )
        return self.add(opp)

    def update_status(
        self, opportunity: GrowthOpportunity, status: OpportunityStatus
    ) -> GrowthOpportunity:
        opportunity.status = status
        self.db.flush()
        return opportunity
