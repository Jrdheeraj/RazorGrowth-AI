"""Payment routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import MerchantContext, merchant_ctx
from backend.app.db.session import get_db
from backend.app.schemas.payment import PaymentResponse
from backend.app.services.payment_service import PaymentService

router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("", response_model=list[PaymentResponse])
def list_payments(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> list[PaymentResponse]:
    """List payments for the caller's merchant (tenant-isolated)."""
    svc = PaymentService(db)
    return svc.list_payments(ctx.merchant_id, limit=limit, offset=offset)
