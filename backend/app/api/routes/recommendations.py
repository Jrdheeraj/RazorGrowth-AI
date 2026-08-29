"""Recommendation routes — CRUD and workflow."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import MerchantContext, merchant_ctx, approver_ctx
from backend.app.db.session import get_db
from backend.app.models.enums import RecommendationStatus
from backend.app.schemas.recommendation import (
    RecommendationCreate,
    RecommendationListResponse,
    RecommendationResponse,
    RecommendationUpdate,
    ApprovalDecisionRequest,
    ApprovalResponse,
    ApprovalListResponse,
)
from backend.app.services.recommendation_service import RecommendationService
from backend.app.services.approval_service import ApprovalService

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("", response_model=RecommendationListResponse)
def list_recommendations(
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """List recommendations for the caller's merchant (tenant-isolated)."""
    status_enum = RecommendationStatus(status) if status else None
    svc = RecommendationService(db)
    recs = svc.list_recommendations(
        ctx.merchant_id, status=status_enum, limit=limit, offset=offset
    )
    return {
        "recommendations": [
            RecommendationResponse.model_validate(r, from_attributes=True) for r in recs
        ]
    }


@router.get("/{recommendation_id}", response_model=RecommendationResponse)
def get_recommendation(
    recommendation_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Get a single recommendation by ID (tenant-isolated)."""
    try:
        rid = uuid.UUID(recommendation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid recommendation_id format")

    svc = RecommendationService(db)
    rec = svc.get_recommendation(rid)
    if not rec or rec.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="RECOMMENDATION_NOT_FOUND")

    return RecommendationResponse.model_validate(rec, from_attributes=True)


@router.post("", response_model=RecommendationResponse, status_code=201)
def create_recommendation(
    payload: RecommendationCreate,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(approver_ctx),  # operator+ can create
) -> Any:
    """Create a new recommendation (operator+)."""
    svc = RecommendationService(db)
    try:
        rec = svc.create_recommendation(
            merchant_id=ctx.merchant_id,
            opportunity_id=payload.opportunity_id,
            recommendation_key=payload.recommendation_key,
            type=payload.type,
            title=payload.title,
            description=payload.description,
            proposed_action=payload.proposed_action,
            target_segment=payload.target_segment,
            rationale=payload.rationale,
            evidence=payload.evidence,
            confidence=payload.confidence,
            assumptions=payload.assumptions,
            expected_revenue=payload.expected_revenue,
            expected_conversion=payload.expected_conversion,
            estimated_cost=payload.estimated_cost,
            guardrails=payload.guardrails,
            requires_approval=payload.requires_approval,
            simulation_snapshot=payload.simulation_snapshot,
        )
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return RecommendationResponse.model_validate(rec, from_attributes=True)


@router.patch("/{recommendation_id}", response_model=RecommendationResponse)
def update_recommendation(
    recommendation_id: str,
    payload: RecommendationUpdate,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(approver_ctx),
) -> Any:
    """Update a recommendation (only in draft or changes_requested status)."""
    try:
        rid = uuid.UUID(recommendation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid recommendation_id format")

    svc = RecommendationService(db)
    rec = svc.get_recommendation(rid)
    if not rec or rec.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="RECOMMENDATION_NOT_FOUND")

    try:
        rec = svc.update_recommendation(
            rid,
            title=payload.title,
            description=payload.description,
            proposed_action=payload.proposed_action,
            target_segment=payload.target_segment,
            rationale=payload.rationale,
            evidence=payload.evidence,
            confidence=payload.confidence,
            assumptions=payload.assumptions,
            expected_revenue=payload.expected_revenue,
            expected_conversion=payload.expected_conversion,
            estimated_cost=payload.estimated_cost,
            guardrails=payload.guardrails,
            requires_approval=payload.requires_approval,
        )
        if not rec:
            raise HTTPException(status_code=404, detail="RECOMMENDATION_NOT_FOUND")
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return RecommendationResponse.model_validate(rec, from_attributes=True)


@router.post("/{recommendation_id}/submit", response_model=RecommendationResponse)
def submit_for_approval(
    recommendation_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(approver_ctx),
) -> Any:
    """Submit a draft recommendation for approval."""
    try:
        rid = uuid.UUID(recommendation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid recommendation_id format")

    svc = RecommendationService(db)
    rec = svc.get_recommendation(rid)
    if not rec or rec.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="RECOMMENDATION_NOT_FOUND")

    try:
        rec = svc.submit_for_approval(rid)
        if not rec:
            raise HTTPException(status_code=404, detail="RECOMMENDATION_NOT_FOUND")
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return RecommendationResponse.model_validate(rec, from_attributes=True)


@router.post("/{recommendation_id}/new-version", response_model=RecommendationResponse)
def new_version(
    recommendation_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(approver_ctx),
) -> Any:
    """Create a new version after changes_requested."""
    try:
        rid = uuid.UUID(recommendation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid recommendation_id format")

    svc = RecommendationService(db)
    rec = svc.get_recommendation(rid)
    if not rec or rec.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="RECOMMENDATION_NOT_FOUND")

    if rec.status != RecommendationStatus.changes_requested:
        raise HTTPException(
            status_code=400,
            detail="Can only create new version when status is changes_requested",
        )

    rec = svc.new_version(rid)
    if not rec:
        raise HTTPException(status_code=404, detail="RECOMMENDATION_NOT_FOUND")
    db.commit()

    return RecommendationResponse.model_validate(rec, from_attributes=True)


@router.delete("/{recommendation_id}", status_code=200)
def delete_recommendation(
    recommendation_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(approver_ctx),
) -> Any:
    """Delete a recommendation (only in draft status)."""
    try:
        rid = uuid.UUID(recommendation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid recommendation_id format")

    svc = RecommendationService(db)
    rec = svc.get_recommendation(rid)
    if not rec or rec.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="RECOMMENDATION_NOT_FOUND")

    try:
        deleted = svc.delete_recommendation(rid)
        if not deleted:
            raise HTTPException(status_code=404, detail="RECOMMENDATION_NOT_FOUND")
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"deleted": True, "id": str(rid)}


# ─────────────────────────────────────────────────────────────────────────────
# Approval endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{recommendation_id}/approval", response_model=ApprovalResponse)
def get_approval(
    recommendation_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Get the approval record for a recommendation."""
    try:
        rid = uuid.UUID(recommendation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid recommendation_id format")

    svc = ApprovalService(db)
    approval = svc.get_approval_by_recommendation(rid)
    if not approval or approval.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="APPROVAL_NOT_FOUND")

    return ApprovalResponse.model_validate(approval, from_attributes=True)


@router.post("/{recommendation_id}/approval/decision", response_model=ApprovalResponse)
def decide_approval(
    recommendation_id: str,
    payload: ApprovalDecisionRequest,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(approver_ctx),  # owner/admin only
) -> Any:
    """Approve, reject, or request changes for a recommendation (owner/admin only)."""
    try:
        rid = uuid.UUID(recommendation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid recommendation_id format")

    svc = ApprovalService(db)
    approval = svc.get_approval_by_recommendation(rid)
    if not approval or approval.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=404, detail="APPROVAL_NOT_FOUND")

    if approval.status != RecommendationStatus.pending_approval:
        raise HTTPException(
            status_code=400,
            detail=f"Can only decide on pending_approval recommendations, current status: {approval.status.value}",
        )

    if payload.decision not in ("approved", "rejected", "changes_requested"):
        raise HTTPException(
            status_code=422,
            detail="decision must be one of: approved, rejected, changes_requested",
        )

    try:
        if payload.decision == "approved":
            approval = svc.approve(
                approval.id,
                approver_user_id=ctx.user.id,
                approver_email=ctx.user.email,
                comment=payload.comment,
            )
        elif payload.decision == "rejected":
            approval = svc.reject(
                approval.id,
                approver_user_id=ctx.user.id,
                approver_email=ctx.user.email,
                comment=payload.comment,
            )
        else:  # changes_requested
            approval = svc.request_changes(
                approval.id,
                approver_user_id=ctx.user.id,
                approver_email=ctx.user.email,
                comment=payload.comment,
            )

        if not approval:
            raise HTTPException(status_code=404, detail="APPROVAL_NOT_FOUND")
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return ApprovalResponse.model_validate(approval, from_attributes=True)


@router.get("", response_model=ApprovalListResponse)
def list_approvals(
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """List approvals for the caller's merchant (tenant-isolated)."""
    status_enum = RecommendationStatus(status) if status else None
    svc = ApprovalService(db)
    approvals = svc.list_approvals(
        ctx.merchant_id, status=status_enum, limit=limit, offset=offset
    )
    return {
        "approvals": [
            ApprovalResponse.model_validate(a, from_attributes=True) for a in approvals
        ]
    }