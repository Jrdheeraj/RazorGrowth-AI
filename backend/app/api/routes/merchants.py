"""Merchant routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.schemas.merchant import MerchantResponse
from backend.app.services.merchant_service import MerchantService

router = APIRouter(prefix="/merchants", tags=["merchants"])


@router.get("", response_model=list[MerchantResponse])
def list_merchants(
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[MerchantResponse]:
    """List all merchants."""
    svc = MerchantService(db)
    return svc.list_merchants(limit=limit, offset=offset)
