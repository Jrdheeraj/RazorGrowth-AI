"""Customer routes."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.schemas.customer import CustomerResponse
from backend.app.services.customer_service import CustomerService

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", response_model=list[CustomerResponse])
def list_customers(
    merchant_id: uuid.UUID = Query(..., description="Merchant UUID"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[CustomerResponse]:
    """List customers for a merchant."""
    svc = CustomerService(db)
    return svc.list_customers(merchant_id, limit=limit, offset=offset)
