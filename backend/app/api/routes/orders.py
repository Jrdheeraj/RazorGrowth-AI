"""Order routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import MerchantContext, merchant_ctx
from backend.app.db.session import get_db
from backend.app.schemas.order import OrderResponse
from backend.app.services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("", response_model=list[OrderResponse])
def list_orders(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> list[OrderResponse]:
    """List orders for the caller's merchant (tenant-isolated)."""
    svc = OrderService(db)
    return svc.list_orders(ctx.merchant_id, limit=limit, offset=offset)
