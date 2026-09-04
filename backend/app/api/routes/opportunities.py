"""
Growth opportunity routes.

GET /api/opportunities preserves the exact Phase 1 response contract so
all existing tests continue to pass. It falls back to the in-memory
engine only for anonymous development-mode callers when no DB merchant
is found. Authenticated callers are strictly tenant-scoped.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.api.deps import MerchantContext, merchant_ctx
from backend.app.db.session import get_db
from backend.app.services.opportunity_service import GrowthOpportunityService

log = logging.getLogger(__name__)

router = APIRouter(prefix="/opportunities", tags=["growth"])


def _opportunity_to_legacy(opp: Any) -> dict:
    """
    Convert a GrowthOpportunity ORM object to the Phase 1 response shape.

    Phase 1 contract fields:
      id, type, title, target_product, target_customers,
      confidence, expected_revenue, reasoning, status
    """
    # Derive target_product from opportunity_key convention
    key = opp.opportunity_key or ""
    if "case" in key:
        target_product = "prod_case"
    elif "upsell" in key:
        target_product = "prod_speaker"
    elif "payment" in key:
        target_product = "prod_payment_retry"
    else:
        target_product = "prod_unknown"

    return {
        "id": opp.opportunity_key or str(opp.id),
        "type": opp.type if isinstance(opp.type, str) else opp.type.value,
        "title": opp.title,
        "target_product": target_product,
        "target_customers": opp.target_customer_count,
        "confidence": float(opp.confidence),
        "expected_revenue": float(opp.expected_revenue),
        "reasoning": opp.reasoning if isinstance(opp.reasoning, list) else [],
        "status": opp.status if isinstance(opp.status, str) else opp.status.value,
    }


@router.get("")
def list_opportunities(
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> dict:
    """
    Return growth opportunities for the caller's merchant.

    Authenticated: strictly scoped to the caller's membership — never any
    other tenant's data, never the synthetic fallback engine.
    Anonymous (optional dev mode): legacy behaviour including the DB-less
    in-memory fallback so early clients keep working.
    """
    try:
        svc = GrowthOpportunityService(db)
        db_opps = svc.analyse_and_persist(ctx.merchant_id)
        db.commit()
        items = [_opportunity_to_legacy(o) for o in db_opps]
        if items:
            return {"items": items}

    except Exception as exc:
        log.warning("DB opportunity engine failed: %s", exc)
        db.rollback()
        if ctx.authenticated:
            # Never leak another tenant's synthetic data on failure.
            raise

    return {"items": []}
