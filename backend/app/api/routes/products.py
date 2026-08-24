"""Product routes."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.schemas.product import ProductResponse
from backend.app.services.product_service import ProductService

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[ProductResponse])
def list_products(
    merchant_id: uuid.UUID = Query(..., description="Merchant UUID"),
    active_only: bool = Query(True),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[ProductResponse]:
    """List products for a merchant."""
    svc = ProductService(db)
    return svc.list_products(
        merchant_id, active_only=active_only, limit=limit, offset=offset
    )
