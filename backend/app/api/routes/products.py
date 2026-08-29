"""Product routes."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import MerchantContext, merchant_ctx, operator_ctx
from backend.app.db.session import get_db
from backend.app.schemas.product import (
    ProductCreate,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
)
from backend.app.services.product_service import ProductService

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=ProductListResponse)
def list_products(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    active_only: bool = Query(True),
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """List products for the caller's merchant (tenant-isolated)."""
    svc = ProductService(db)
    products = svc.list_products(
        ctx.merchant_id, active_only=active_only, limit=limit, offset=offset
    )
    return {
        "products": [
            ProductResponse.model_validate(p, from_attributes=True) for p in products
        ],
        "total": len(products),
    }


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(
    product_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Get a single product by ID (tenant-isolated)."""
    try:
        pid = uuid.UUID(product_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid product_id format")

    svc = ProductService(db)
    product = svc.get_product_by_merchant(ctx.merchant_id, pid)
    if not product:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")

    return ProductResponse.model_validate(product, from_attributes=True)


@router.post("", response_model=ProductResponse, status_code=201)
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Create a new product (operator+)."""
    from decimal import Decimal

    svc = ProductService(db)
    try:
        product = svc.create_product(
            merchant_id=ctx.merchant_id,
            name=payload.name,
            category=payload.category,
            price=Decimal(str(payload.price)),
            sku=payload.sku,
            description=payload.description,
            stock_quantity=payload.stock_quantity,
        )
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return ProductResponse.model_validate(product, from_attributes=True)


@router.patch("/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: str,
    payload: ProductUpdate,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Update a product (operator+)."""
    try:
        pid = uuid.UUID(product_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid product_id format")

    from decimal import Decimal

    svc = ProductService(db)
    product = svc.get_product_by_merchant(ctx.merchant_id, pid)
    if not product:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")

    try:
        product = svc.update_product(
            pid,
            name=payload.name,
            description=payload.description,
            category=payload.category,
            price=Decimal(str(payload.price)) if payload.price is not None else None,
            sku=payload.sku,
            stock_quantity=payload.stock_quantity,
            active=payload.active,
        )
        if not product:
            raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return ProductResponse.model_validate(product, from_attributes=True)


@router.delete("/{product_id}", status_code=200)
def delete_product(
    product_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """Delete a product (operator+)."""
    try:
        pid = uuid.UUID(product_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid product_id format")

    svc = ProductService(db)
    product = svc.get_product_by_merchant(ctx.merchant_id, pid)
    if not product:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")

    try:
        deleted = svc.delete_product(pid)
        if not deleted:
            raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"deleted": True, "id": str(pid)}
