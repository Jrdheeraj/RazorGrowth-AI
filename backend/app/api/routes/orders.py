"""Order routes."""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import MerchantContext, merchant_ctx, operator_ctx
from backend.app.db.session import get_db
from backend.app.schemas.order import (
    OrderCreate,
    OrderItemCreate,
    OrderListResponse,
    OrderResponse,
    OrderUpdate,
)
from backend.app.services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("", response_model=OrderListResponse)
def list_orders(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """List orders for the caller's merchant (tenant-isolated)."""
    svc = OrderService(db)
    orders = svc.list_orders(ctx.merchant_id, limit=limit, offset=offset)
    return {
        "orders": [
            OrderResponse.model_validate(o, from_attributes=True) for o in orders
        ],
        "total": len(orders),
    }


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Get a single order by ID (tenant-isolated)."""
    try:
        oid = uuid.UUID(order_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid order_id format")

    svc = OrderService(db)
    order = svc.get_order_by_merchant(ctx.merchant_id, oid)
    if not order:
        raise HTTPException(status_code=404, detail="ORDER_NOT_FOUND")

    return OrderResponse.model_validate(order, from_attributes=True)


@router.post("", response_model=OrderResponse, status_code=201)
def create_order(
    payload: OrderCreate,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Create a new order (operator+)."""
    from backend.app.models.enums import OrderStatus

    svc = OrderService(db)
    try:
        order = svc.create_order(
            merchant_id=ctx.merchant_id,
            customer_id=payload.customer_id,
            order_number=payload.order_number,
            status=OrderStatus(payload.status) if payload.status else OrderStatus.pending,
            subtotal=Decimal(str(payload.subtotal)),
            discount=Decimal(str(payload.discount)),
            tax=Decimal(str(payload.tax)),
            total=Decimal(str(payload.total)),
            currency=payload.currency,
            items=[item.model_dump() for item in payload.items],
        )
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return OrderResponse.model_validate(order, from_attributes=True)


@router.patch("/{order_id}", response_model=OrderResponse)
def update_order(
    order_id: str,
    payload: OrderUpdate,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Update an order (operator+)."""
    try:
        oid = uuid.UUID(order_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid order_id format")

    from backend.app.models.enums import OrderStatus

    svc = OrderService(db)
    order = svc.get_order_by_merchant(ctx.merchant_id, oid)
    if not order:
        raise HTTPException(status_code=404, detail="ORDER_NOT_FOUND")

    try:
        items_data = [item.model_dump() for item in payload.items] if payload.items else None
        order = svc.update_order(
            oid,
            status=OrderStatus(payload.status) if payload.status else None,
            subtotal=Decimal(str(payload.subtotal)) if payload.subtotal is not None else None,
            discount=Decimal(str(payload.discount)) if payload.discount is not None else None,
            tax=Decimal(str(payload.tax)) if payload.tax is not None else None,
            total=Decimal(str(payload.total)) if payload.total is not None else None,
            items=items_data,
        )
        if not order:
            raise HTTPException(status_code=404, detail="ORDER_NOT_FOUND")
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return OrderResponse.model_validate(order, from_attributes=True)


@router.delete("/{order_id}", status_code=200)
def delete_order(
    order_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Delete an order (operator+)."""
    try:
        oid = uuid.UUID(order_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid order_id format")

    svc = OrderService(db)
    order = svc.get_order_by_merchant(ctx.merchant_id, oid)
    if not order:
        raise HTTPException(status_code=404, detail="ORDER_NOT_FOUND")

    try:
        deleted = svc.delete_order(oid)
        if not deleted:
            raise HTTPException(status_code=404, detail="ORDER_NOT_FOUND")
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"deleted": True, "id": str(oid)}
