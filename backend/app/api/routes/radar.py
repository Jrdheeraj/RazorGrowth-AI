"""Growth Radar + Ranked Opportunities routes — Phase 5."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.models.opportunity import GrowthOpportunity
from backend.app.schemas.phase5 import (
    RadarResponse,
    RankedOpportunitiesResponse,
    SignalOut,
)
from backend.app.services.radar import GrowthRadarService
from backend.app.services.scoring import OpportunityScoringEngine
from sqlalchemy import select

router = APIRouter(tags=["radar"])


def _resolve_merchant(db: Session, merchant_id: uuid.UUID | None) -> uuid.UUID:
    if merchant_id is not None:
        from backend.app.models.merchant import Merchant

        if db.get(Merchant, merchant_id) is None:
            raise HTTPException(status_code=404, detail="MERCHANT_NOT_FOUND")
        return merchant_id
    from backend.app.repositories.merchant import MerchantRepository

    merchants = MerchantRepository(db).list_all(limit=1)
    if not merchants:
        raise HTTPException(status_code=404, detail="MERCHANT_NOT_FOUND")
    return merchants[0].id


@router.get("/radar", response_model=RadarResponse)
def get_radar(
    merchant_id: uuid.UUID | None = None,
    window_days: int = Query(default=30, ge=1, le=365),
    refresh: bool = False,
    db: Session = Depends(get_db),
) -> Any:
    """
    Growth Radar signals. Reads persisted active signals; with
    ?refresh=true re-runs deterministic detection first.
    """
    mid = _resolve_merchant(db, merchant_id)
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
    merchant_id: uuid.UUID | None = None,
    limit: int = Query(default=10, ge=1, le=50),
    status: str = "pending_approval",
    db: Session = Depends(get_db),
) -> Any:
    """
    Deterministically ranked opportunities with full score breakdowns —
    the data behind 'Why did the AI rank this opportunity #1?'.
    """
    mid = _resolve_merchant(db, merchant_id)

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
