"""Customer routes."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import MerchantContext, merchant_ctx, operator_ctx
from backend.app.db.session import get_db
from backend.app.schemas.customer import (
    CustomerCreate,
    CustomerListResponse,
    CustomerResponse,
    CustomerUpdate,
)
from backend.app.services.customer_service import CustomerService

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", response_model=CustomerListResponse)
def list_customers(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """List customers for the caller's merchant (tenant-isolated)."""
    svc = CustomerService(db)
    customers = svc.list_customers(ctx.merchant_id, limit=limit, offset=offset)
    return {
        "customers": [
            CustomerResponse.model_validate(c, from_attributes=True) for c in customers
        ],
        "total": len(customers),
    }


@router.get("/{customer_id}", response_model=CustomerResponse)
def get_customer(
    customer_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Get a single customer by ID (tenant-isolated)."""
    try:
        cid = uuid.UUID(customer_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid customer_id format")

    svc = CustomerService(db)
    customer = svc.get_customer_by_merchant(ctx.merchant_id, cid)
    if not customer:
        raise HTTPException(status_code=404, detail="CUSTOMER_NOT_FOUND")

    return CustomerResponse.model_validate(customer, from_attributes=True)


@router.post("", response_model=CustomerResponse, status_code=201)
def create_customer(
    payload: CustomerCreate,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Create a new customer (operator+)."""
    from backend.app.models.enums import CustomerSegment

    svc = CustomerService(db)
    try:
        segment = CustomerSegment(payload.segment) if payload.segment else CustomerSegment.new
        customer = svc.create_customer(
            merchant_id=ctx.merchant_id,
            name=payload.name,
            email=payload.email,
            phone=payload.phone,
            segment=segment,
        )
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return CustomerResponse.model_validate(customer, from_attributes=True)


@router.patch("/{customer_id}", response_model=CustomerResponse)
def update_customer(
    customer_id: str,
    payload: CustomerUpdate,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Update a customer (operator+)."""
    try:
        cid = uuid.UUID(customer_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid customer_id format")

    from backend.app.models.enums import CustomerSegment

    svc = CustomerService(db)
    customer = svc.get_customer_by_merchant(ctx.merchant_id, cid)
    if not customer:
        raise HTTPException(status_code=404, detail="CUSTOMER_NOT_FOUND")

    try:
        segment = CustomerSegment(payload.segment) if payload.segment else None
        customer = svc.update_customer(
            cid,
            name=payload.name,
            email=payload.email,
            phone=payload.phone,
            segment=segment,
        )
        if not customer:
            raise HTTPException(status_code=404, detail="CUSTOMER_NOT_FOUND")
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return CustomerResponse.model_validate(customer, from_attributes=True)


@router.delete("/{customer_id}", status_code=200)
def delete_customer(
    customer_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Delete a customer (operator+)."""
    try:
        cid = uuid.UUID(customer_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid customer_id format")

    svc = CustomerService(db)
    customer = svc.get_customer_by_merchant(ctx.merchant_id, cid)
    if not customer:
        raise HTTPException(status_code=404, detail="CUSTOMER_NOT_FOUND")

    try:
        deleted = svc.delete_customer(cid)
        if not deleted:
            raise HTTPException(status_code=404, detail="CUSTOMER_NOT_FOUND")
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"deleted": True, "id": str(cid)}
