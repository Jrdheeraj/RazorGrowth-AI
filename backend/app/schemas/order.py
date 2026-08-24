"""Order and OrderItem Pydantic schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from backend.app.models.enums import Currency, OrderStatus


class OrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    merchant_id: uuid.UUID
    customer_id: uuid.UUID
    order_number: str
    status: OrderStatus
    subtotal: Decimal
    discount: Decimal
    tax: Decimal
    total: Decimal
    currency: Currency
    items: list[OrderItemResponse]
    created_at: datetime
    updated_at: datetime
