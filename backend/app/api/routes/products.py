"""Product routes."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import MerchantContext, merchant_ctx
from backend.app.db.session import get_db
from backend.app.schemas.product import ProductResponse
from backend.app.services.product_service import ProductService

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[ProductResponse])
def list_products(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    active_only: bool = Query(True),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> list[ProductResponse]:
    """List products for the caller's merchant (tenant-isolated)."""
    svc = ProductService(db)
    return svc.list_products(
        ctx.merchant_id, active_only=active_only, limit=limit, offset=offset
    )
