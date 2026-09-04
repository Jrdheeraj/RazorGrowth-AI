"""Payment routes."""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
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


class CheckoutSessionRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, description="Amount in INR")
    currency: str = Field(default="INR", min_length=3, max_length=3)
    description: str | None = Field(default=None, max_length=255)
    customer_email: str | None = Field(default=None, pattern=r"^[^@]+@[^@]+\.[^@]+$")
    customer_contact: str | None = Field(default=None, max_length=20)
    receipt: str | None = Field(default=None, max_length=100)
    notes: dict[str, str] | None = None
    callback_url: str | None = Field(default=None, max_length=500)


class CheckoutSessionResponse(BaseModel):
    razorpay_order_id: str
    razorpay_payment_link_id: str | None = None
    short_url: str | None = None
    amount: float
    currency: str
    key_id: str


class PaymentVerificationRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class PaymentVerificationResponse(BaseModel):
    verified: bool
    payment_id: str | None = None


@router.post("/checkout", response_model=CheckoutSessionResponse)
def create_checkout_session(
    payload: CheckoutSessionRequest,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Create a Razorpay TEST checkout session.
    
    Creates a Razorpay order for TEST MODE checkout.
    Returns the data needed by the frontend to open Razorpay Checkout.
    
    Requires operator+ role. The checkout is TEST MODE only — uses
    Razorpay TEST credentials and does not process real money.
    """
    svc = PaymentService(db)
    try:
        result = svc.create_checkout_session(
            merchant_id=ctx.merchant_id,
            amount=payload.amount,
            currency=payload.currency,
            description=payload.description,
            customer_email=payload.customer_email,
            customer_contact=payload.customer_contact,
            receipt=payload.receipt,
            notes=payload.notes,
            callback_url=payload.callback_url,
        )
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    
    return CheckoutSessionResponse(**result)


@router.post("/verify", response_model=PaymentVerificationResponse)
def verify_payment(
    payload: PaymentVerificationRequest,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Verify a Razorpay payment signature.
    
    Verifies the Razorpay payment signature server-side.
    If valid, updates the local payment record with the Razorpay payment ID.
    
    Requires operator+ role and tenant isolation.
    """
    svc = PaymentService(db)
    try:
        result = svc.verify_payment_signature(
            merchant_id=ctx.merchant_id,
            razorpay_order_id=payload.razorpay_order_id,
            razorpay_payment_id=payload.razorpay_payment_id,
            razorpay_signature=payload.razorpay_signature,
        )
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    
    return PaymentVerificationResponse(**result)


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
