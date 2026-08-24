"""
Growth opportunity routes.

GET /api/opportunities preserves the exact Phase 1 response contract so
all existing tests continue to pass. It falls back to the in-memory
engine when no DB merchant is found, ensuring the endpoint always returns
at least one opportunity regardless of DB state.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.services.opportunity_service import GrowthOpportunityService

# Phase 1 in-memory fallback (preserved)
from backend.app.services.growth_engine import generate_opportunities

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
def list_opportunities(db: Session = Depends(get_db)) -> dict:
    """
    Return growth opportunities.

    Attempts to use the DB-backed engine. Falls back to in-memory synthetic
    data if the DB has no merchants yet (e.g. before seeding).
    """
    try:
        # Find the first available merchant
        from backend.app.repositories.merchant import MerchantRepository
        merchant_repo = MerchantRepository(db)
        merchants = merchant_repo.list_all(limit=1)

        if merchants:
            svc = GrowthOpportunityService(db)
            db_opps = svc.analyse_and_persist(merchants[0].id)
            db.commit()
            items = [_opportunity_to_legacy(o) for o in db_opps]
            if items:
                return {"items": items}

    except Exception as exc:
        log.warning("DB opportunity engine failed, falling back to in-memory: %s", exc)
        db.rollback()

    # Phase 1 fallback — always works without a DB
    return {"items": generate_opportunities()}
