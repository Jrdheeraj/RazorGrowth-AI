"""ApprovalService — human approval workflow for recommendations."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.app.models.enums import RecommendationStatus
from backend.app.models.approval import Approval
from backend.app.models.recommendation import Recommendation
from backend.app.repositories.approval import ApprovalRepository
from backend.app.repositories.recommendation import RecommendationRepository
from backend.app.core.logging import get_logger

log = get_logger(__name__)


class ApprovalService:
    def __init__(self, db: Session) -> None:
        self._approval_repo = ApprovalRepository(db)
        self._rec_repo = RecommendationRepository(db)
        self._db = db

    def list_approvals(
        self,
        merchant_id: uuid.UUID,
        *,
        status: RecommendationStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Approval]:
        return self._approval_repo.list_by_merchant(
            merchant_id, status=status, limit=limit, offset=offset
        )

    def get_approval(self, approval_id: uuid.UUID) -> Approval | None:
        return self._approval_repo.get_with_recommendation(approval_id)

    def get_approval_by_recommendation(self, recommendation_id: uuid.UUID) -> Approval | None:
        return self._approval_repo.get_by_recommendation(recommendation_id)

    def approve(
        self,
        approval_id: uuid.UUID,
        approver_user_id: uuid.UUID,
        approver_email: str,
        comment: str | None = None,
    ) -> Approval | None:
        approval = self._approval_repo.get_with_recommendation(approval_id)
        if not approval:
            return None

        if approval.status != RecommendationStatus.pending_approval:
            raise ValueError(
                f"Can only approve pending_approval recommendations, current status: {approval.status.value}"
            )

        rec = approval.recommendation
        if not rec:
            raise ValueError("Recommendation not found")

        # Snapshot the recommendation and simulation at approval time
        recommendation_snapshot = {
            "id": str(rec.id),
            "type": rec.type,
            "title": rec.title,
            "description": rec.description,
            "proposed_action": rec.proposed_action,
            "target_segment": rec.target_segment,
            "rationale": rec.rationale,
            "evidence": rec.evidence,
            "confidence": float(rec.confidence),
            "assumptions": rec.assumptions,
            "expected_revenue": float(rec.expected_revenue),
            "expected_conversion": float(rec.expected_conversion) if rec.expected_conversion else None,
            "estimated_cost": float(rec.estimated_cost) if rec.estimated_cost else None,
            "guardrails": rec.guardrails,
            "requires_approval": rec.requires_approval,
            "version": rec.version,
        }

        approval.status = RecommendationStatus.approved
        approval.decision = "approved"
        approval.comment = comment
        approval.approver_user_id = approver_user_id
        approval.approver_email = approver_email
        approval.decided_at = datetime.now(timezone.utc)
        approval.recommendation_snapshot = recommendation_snapshot
        approval.simulation_snapshot = rec.simulation_snapshot
        approval.approved_version = rec.version

        # Update recommendation status
        rec.status = RecommendationStatus.approved
        rec.approved_version = rec.version

        self._db.flush()
        log.info(
            "Recommendation approved. approval=%s rec=%s approver=%s",
            str(approval_id), str(rec.id), str(approver_user_id),
        )
        return approval

    def reject(
        self,
        approval_id: uuid.UUID,
        approver_user_id: uuid.UUID,
        approver_email: str,
        comment: str | None = None,
    ) -> Approval | None:
        approval = self._approval_repo.get_with_recommendation(approval_id)
        if not approval:
            return None

        if approval.status != RecommendationStatus.pending_approval:
            raise ValueError(
                f"Can only reject pending_approval recommendations, current status: {approval.status.value}"
            )

        rec = approval.recommendation
        if not rec:
            raise ValueError("Recommendation not found")

        approval.status = RecommendationStatus.rejected
        approval.decision = "rejected"
        approval.comment = comment
        approval.approver_user_id = approver_user_id
        approval.approver_email = approver_email
        approval.decided_at = datetime.now(timezone.utc)

        rec.status = RecommendationStatus.rejected

        self._db.flush()
        log.info(
            "Recommendation rejected. approval=%s rec=%s approver=%s",
            str(approval_id), str(rec.id), str(approver_user_id),
        )
        return approval

    def request_changes(
        self,
        approval_id: uuid.UUID,
        approver_user_id: uuid.UUID,
        approver_email: str,
        comment: str | None = None,
    ) -> Approval | None:
        approval = self._approval_repo.get_with_recommendation(approval_id)
        if not approval:
            return None

        if approval.status != RecommendationStatus.pending_approval:
            raise ValueError(
                f"Can only request changes for pending_approval recommendations, current status: {approval.status.value}"
            )

        rec = approval.recommendation
        if not rec:
            raise ValueError("Recommendation not found")

        approval.status = RecommendationStatus.changes_requested
        approval.decision = "changes_requested"
        approval.comment = comment
        approval.approver_user_id = approver_user_id
        approval.approver_email = approver_email
        approval.decided_at = datetime.now(timezone.utc)

        rec.status = RecommendationStatus.changes_requested

        self._db.flush()
        log.info(
            "Changes requested for recommendation. approval=%s rec=%s approver=%s",
            str(approval_id), str(rec.id), str(approver_user_id),
        )
        return approval