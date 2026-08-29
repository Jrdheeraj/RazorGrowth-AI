"""RecommendationService — business logic for recommendations."""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from backend.app.models.enums import RecommendationStatus, RecommendationType
from backend.app.models.recommendation import Recommendation
from backend.app.repositories.recommendation import RecommendationRepository
from backend.app.repositories.approval import ApprovalRepository
from backend.app.core.logging import get_logger

log = get_logger(__name__)


class RecommendationService:
    def __init__(self, db: Session) -> None:
        self._repo = RecommendationRepository(db)
        self._approval_repo = ApprovalRepository(db)
        self._db = db

    def list_recommendations(
        self,
        merchant_id: uuid.UUID,
        *,
        status: RecommendationStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Recommendation]:
        return self._repo.list_by_merchant(
            merchant_id, status=status, limit=limit, offset=offset
        )

    def get_recommendation(self, recommendation_id: uuid.UUID) -> Recommendation | None:
        return self._repo.get_with_approval(recommendation_id)

    def create_recommendation(
        self,
        *,
        merchant_id: uuid.UUID,
        opportunity_id: uuid.UUID | None,
        recommendation_key: str | None,
        type: RecommendationType,
        title: str,
        description: str | None,
        proposed_action: str,
        target_segment: str | None,
        rationale: str | None,
        evidence: list[Any] | None,
        confidence: Decimal,
        assumptions: list[Any] | None,
        expected_revenue: Decimal,
        expected_conversion: Decimal | None,
        estimated_cost: Decimal | None,
        guardrails: dict[str, Any] | None,
        requires_approval: bool,
        simulation_snapshot: dict[str, Any] | None = None,
    ) -> Recommendation:
        # Check idempotency key
        if recommendation_key:
            existing = self._repo.get_by_key(merchant_id, recommendation_key)
            if existing:
                log.info(
                    "Recommendation already exists for key %s, returning existing",
                    recommendation_key,
                )
                return existing

        rec = self._repo.create(
            merchant_id=merchant_id,
            opportunity_id=opportunity_id,
            recommendation_key=recommendation_key,
            type=type.value,
            title=title,
            description=description,
            proposed_action=proposed_action,
            target_segment=target_segment,
            rationale=rationale,
            evidence=evidence,
            confidence=float(confidence),
            assumptions=assumptions,
            expected_revenue=float(expected_revenue),
            expected_conversion=float(expected_conversion) if expected_conversion else None,
            estimated_cost=float(estimated_cost) if estimated_cost else None,
            guardrails=guardrails,
            requires_approval=requires_approval,
            simulation_snapshot=simulation_snapshot,
        )
        self._db.flush()

        # Create approval record if requires approval
        if requires_approval:
            self._approval_repo.create(
                merchant_id=merchant_id,
                recommendation_id=rec.id,
                status=RecommendationStatus.pending_approval,
            )
            self._db.flush()

        log.info(
            "Recommendation created. id=%s merchant=%s type=%s status=%s",
            str(rec.id), merchant_id, type.value, rec.status,
        )
        return rec

    def update_recommendation(
        self,
        recommendation_id: uuid.UUID,
        *,
        title: str | None = None,
        description: str | None = None,
        proposed_action: str | None = None,
        target_segment: str | None = None,
        rationale: str | None = None,
        evidence: list[Any] | None = None,
        confidence: Decimal | None = None,
        assumptions: list[Any] | None = None,
        expected_revenue: Decimal | None = None,
        expected_conversion: Decimal | None = None,
        estimated_cost: Decimal | None = None,
        guardrails: dict[str, Any] | None = None,
        requires_approval: bool | None = None,
    ) -> Recommendation | None:
        rec = self._repo.get_by_id(recommendation_id)
        if not rec:
            return None

        # Only allow updates in draft or changes_requested status
        if rec.status not in (RecommendationStatus.draft, RecommendationStatus.changes_requested):
            raise ValueError(
                f"Cannot update recommendation in status {rec.status.value}"
            )

        if title is not None:
            rec.title = title
        if description is not None:
            rec.description = description
        if proposed_action is not None:
            rec.proposed_action = proposed_action
        if target_segment is not None:
            rec.target_segment = target_segment
        if rationale is not None:
            rec.rationale = rationale
        if evidence is not None:
            rec.evidence = evidence
        if confidence is not None:
            rec.confidence = confidence
        if assumptions is not None:
            rec.assumptions = assumptions
        if expected_revenue is not None:
            rec.expected_revenue = expected_revenue
        if expected_conversion is not None:
            rec.expected_conversion = expected_conversion
        if estimated_cost is not None:
            rec.estimated_cost = estimated_cost
        if guardrails is not None:
            rec.guardrails = guardrails
        if requires_approval is not None:
            rec.requires_approval = requires_approval

        self._db.flush()
        return rec

    def submit_for_approval(self, recommendation_id: uuid.UUID) -> Recommendation | None:
        rec = self._repo.get_with_approval(recommendation_id)
        if not rec:
            return None

        if rec.status != RecommendationStatus.draft:
            raise ValueError(
                f"Can only submit draft recommendations for approval, current status: {rec.status.value}"
            )

        rec.status = RecommendationStatus.pending_approval
        if rec.approval:
            rec.approval.status = RecommendationStatus.pending_approval
        self._db.flush()
        return rec

    def request_changes(self, recommendation_id: uuid.UUID) -> Recommendation | None:
        rec = self._repo.get_with_approval(recommendation_id)
        if not rec:
            return None

        if rec.status != RecommendationStatus.pending_approval:
            raise ValueError(
                f"Can only request changes for pending_approval recommendations, current status: {rec.status.value}"
            )

        rec.status = RecommendationStatus.changes_requested
        if rec.approval:
            rec.approval.status = RecommendationStatus.changes_requested
        self._db.flush()
        return rec

    def new_version(self, recommendation_id: uuid.UUID) -> Recommendation | None:
        """Create a new version of the recommendation (for changes_requested flow)."""
        return self._repo.increment_version(recommendation_id)

    def delete_recommendation(self, recommendation_id: uuid.UUID) -> bool:
        rec = self._repo.get_by_id(recommendation_id)
        if not rec:
            return False

        # Only allow deletion in draft status
        if rec.status != RecommendationStatus.draft:
            raise ValueError(
                f"Can only delete draft recommendations, current status: {rec.status.value}"
            )

        self._repo.delete(rec)
        self._db.flush()
        return True