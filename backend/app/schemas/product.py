"""Product Pydantic schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from backend.app.models.enums import Currency


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    merchant_id: uuid.UUID
    name: str
    description: str | None
    category: str
    price: Decimal
    currency: Currency
    sku: str | None
    stock_quantity: int
    active: bool
    created_at: datetime
    updated_at: datetime
