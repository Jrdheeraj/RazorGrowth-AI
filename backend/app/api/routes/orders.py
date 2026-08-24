"""Order routes."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.schemas.order import OrderResponse
from backend.app.services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("", response_model=list[OrderResponse])
def list_orders(
    merchant_id: uuid.UUID = Query(..., description="Merchant UUID"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[OrderResponse]:
    """List orders for a merchant."""
    svc = OrderService(db)
    return svc.list_orders(merchant_id, limit=limit, offset=offset)
