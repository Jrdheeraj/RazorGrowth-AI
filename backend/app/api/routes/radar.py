"""Growth Radar + Ranked Opportunities routes — Phase 5.

All endpoints are tenant-scoped to the authenticated caller's membership.
Refresh operations mutate signal state and require operator role or above.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import MerchantContext, merchant_ctx
from backend.app.core.roles import can_run_operations
from backend.app.db.session import get_db
from backend.app.models.opportunity import GrowthOpportunity
from backend.app.schemas.phase5 import (
    RadarResponse,
    RankedOpportunitiesResponse,
)
from backend.app.services.radar import GrowthRadarService
from backend.app.services.scoring import OpportunityScoringEngine
from sqlalchemy import select

router = APIRouter(tags=["radar"])


@router.get("/radar", response_model=RadarResponse)
def get_radar(
    window_days: int = Query(default=30, ge=1, le=365),
    refresh: bool = False,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """
    Growth Radar signals for the caller's merchant. Reads persisted active
    signals; ?refresh=true re-runs deterministic detection first and is
    restricted to operator role and above.
    """
    if refresh and ctx.authenticated and not (
        ctx.membership and can_run_operations(ctx.membership.role)
    ):
        raise HTTPException(status_code=403, detail="INSUFFICIENT_ROLE")
    mid = ctx.merchant_id
    if refresh:
        try:
            GrowthRadarService(db).detect(mid, window_days=window_days)
            db.commit()
        except Exception:
            db.rollback()
            raise HTTPException(status_code=500, detail="RADAR_REFRESH_FAILED")
    signals = GrowthRadarService(db).list_signals(mid, limit=100)
    return {
        "merchant_id": str(mid),
        "signals": [
            {
                "id": str(s.id),
                "signal_type": str(getattr(s.signal_type, "value", s.signal_type)),
                "title": s.title,
                "metric": s.metric,
                "current_value": float(s.current_value),
                "comparison_value": float(s.comparison_value),
                "change_percentage": (
                    float(s.change_percentage) if s.change_percentage is not None else None
                ),
                "window_days": s.window_days,
                "confidence": float(s.confidence),
                "evidence": s.evidence,
                "detected_at": str(s.detected_at),
            }
            for s in signals
        ],
    }


@router.get("/opportunities/ranked", response_model=RankedOpportunitiesResponse)
def get_ranked_opportunities(
    limit: int = Query(default=10, ge=1, le=50),
    status: str = "pending_approval",
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """
    Deterministically ranked opportunities with full score breakdowns —
    the data behind 'Why did the AI rank this opportunity #1?'.
    Strictly tenant-scoped to the authenticated membership.
    """
    mid = ctx.merchant_id

    stmt = (
        select(GrowthOpportunity)
        .where(GrowthOpportunity.merchant_id == mid)
        .limit(200)
    )
    if status:
        if status not in {"pending_approval", "approved", "rejected",
                          "executing", "completed", "failed", "expired"}:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
        stmt = stmt.where(GrowthOpportunity.status == status)

    opportunities = list(db.scalars(stmt).all())
    engine = OpportunityScoringEngine()
    scored = []
    for opp in opportunities:
        breakdown = engine.score(
            expected_revenue=float(opp.expected_revenue),
            confidence=float(opp.confidence),
            target_customer_count=int(opp.target_customer_count or 0),
            evidence_items=max(1, len(opp.reasoning or [])),
        )
        scored.append((breakdown.opportunity_score, opp, breakdown))
    scored.sort(key=lambda t: t[0], reverse=True)

    return {
        "merchant_id": str(mid),
        "opportunities": [
            {
                "rank": i + 1,
                "opportunity_id": str(opp.id),
                "title": opp.title,
                "type": str(getattr(opp.type, "value", opp.type)),
                "status": str(getattr(opp.status, "value", opp.status)),
                "opportunity_score": score,
                "expected_revenue": float(opp.expected_revenue),
                "confidence": float(opp.confidence),
                "score_breakdown": bd.to_dict(),
            }
            for i, (score, opp, bd) in enumerate(scored[:limit])
        ],
    }
