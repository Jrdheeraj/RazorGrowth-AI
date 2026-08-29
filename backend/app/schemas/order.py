"""Order and OrderItem Pydantic schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OrderItemBase(BaseModel):
    product_id: uuid.UUID
    quantity: int = Field(..., gt=0)
    unit_price: Decimal = Field(..., ge=0)


class OrderItemCreate(OrderItemBase):
    pass


class OrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class OrderBase(BaseModel):
    customer_id: uuid.UUID
    order_number: str = Field(..., min_length=1, max_length=100)
    status: str = Field(default="pending", max_length=20)
    subtotal: Decimal = Field(..., ge=0)
    discount: Decimal = Field(default=Decimal("0.00"), ge=0)
    tax: Decimal = Field(default=Decimal("0.00"), ge=0)
    total: Decimal = Field(..., ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    items: list[OrderItemCreate]


class OrderCreate(OrderBase):
    pass


class OrderUpdate(BaseModel):
    status: str | None = Field(default=None, max_length=20)
    subtotal: Decimal | None = Field(default=None, ge=0)
    discount: Decimal | None = Field(default=None, ge=0)
    tax: Decimal | None = Field(default=None, ge=0)
    total: Decimal | None = Field(default=None, ge=0)
    items: list[OrderItemCreate] | None = None


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    merchant_id: uuid.UUID
    customer_id: uuid.UUID
    order_number: str
    status: str
    subtotal: Decimal
    discount: Decimal
    tax: Decimal
    total: Decimal
    currency: str
    items: list[OrderItemResponse]
    created_at: datetime
    updated_at: datetime


class OrderListResponse(BaseModel):
    orders: list[OrderResponse]
    total: int
