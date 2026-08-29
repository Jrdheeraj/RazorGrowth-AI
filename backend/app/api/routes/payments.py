"""Payment routes."""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import MerchantContext, merchant_ctx, operator_ctx
from backend.app.db.session import get_db
from backend.app.schemas.payment import (
    PaymentCreate,
    PaymentListResponse,
    PaymentResponse,
    PaymentUpdate,
)
from backend.app.services.payment_service import PaymentService

router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("", response_model=PaymentListResponse)
def list_payments(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """List payments for the caller's merchant (tenant-isolated)."""
    svc = PaymentService(db)
    payments = svc.list_payments(ctx.merchant_id, limit=limit, offset=offset)
    return {
        "payments": [
            PaymentResponse.model_validate(p, from_attributes=True) for p in payments
        ],
        "total": len(payments),
    }


@router.get("/{payment_id}", response_model=PaymentResponse)
def get_payment(
    payment_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Get a single payment by ID (tenant-isolated)."""
    try:
        pid = uuid.UUID(payment_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payment_id format")

    svc = PaymentService(db)
    payment = svc.get_payment_by_merchant(ctx.merchant_id, pid)
    if not payment:
        raise HTTPException(status_code=404, detail="PAYMENT_NOT_FOUND")

    return PaymentResponse.model_validate(payment, from_attributes=True)


@router.post("", response_model=PaymentResponse, status_code=201)
def create_payment(
    payload: PaymentCreate,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Create a new payment (operator+)."""
    svc = PaymentService(db)
    try:
        payment = svc.create_payment(
            merchant_id=ctx.merchant_id,
            order_id=payload.order_id,
            provider=payload.provider,
            provider_payment_id=payload.provider_payment_id,
            amount=Decimal(str(payload.amount)),
            currency=payload.currency,
            status=payload.status,
            failure_code=payload.failure_code,
            failure_reason=payload.failure_reason,
        )
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return PaymentResponse.model_validate(payment, from_attributes=True)


@router.patch("/{payment_id}", response_model=PaymentResponse)
def update_payment(
    payment_id: str,
    payload: PaymentUpdate,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Update a payment (operator+)."""
    try:
        pid = uuid.UUID(payment_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payment_id format")

    svc = PaymentService(db)
    payment = svc.get_payment_by_merchant(ctx.merchant_id, pid)
    if not payment:
        raise HTTPException(status_code=404, detail="PAYMENT_NOT_FOUND")

    try:
        payment = svc.update_payment(
            pid,
            provider_payment_id=payload.provider_payment_id,
            status=payload.status,
            failure_code=payload.failure_code,
            failure_reason=payload.failure_reason,
        )
        if not payment:
            raise HTTPException(status_code=404, detail="PAYMENT_NOT_FOUND")
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return PaymentResponse.model_validate(payment, from_attributes=True)


@router.delete("/{payment_id}", status_code=200)
def delete_payment(
    payment_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Delete a payment (operator+)."""
    try:
        pid = uuid.UUID(payment_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payment_id format")

    svc = PaymentService(db)
    payment = svc.get_payment_by_merchant(ctx.merchant_id, pid)
    if not payment:
        raise HTTPException(status_code=404, detail="PAYMENT_NOT_FOUND")

    try:
        deleted = svc.delete_payment(pid)
        if not deleted:
            raise HTTPException(status_code=404, detail="PAYMENT_NOT_FOUND")
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"deleted": True, "id": str(pid)}
