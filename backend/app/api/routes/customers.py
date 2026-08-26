"""Customer routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import MerchantContext, merchant_ctx
from backend.app.db.session import get_db
from backend.app.schemas.customer import CustomerResponse
from backend.app.services.customer_service import CustomerService

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", response_model=list[CustomerResponse])
def list_customers(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> list[CustomerResponse]:
    """List customers for the caller's merchant (tenant-isolated)."""
    svc = CustomerService(db)
    return svc.list_customers(ctx.merchant_id, limit=limit, offset=offset)
