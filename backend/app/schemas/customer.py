"""Customer Pydantic schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from backend.app.models.enums import CustomerSegment


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    merchant_id: uuid.UUID
    name: str
    email: str
    segment: CustomerSegment
    total_orders: int
    total_spend: Decimal
    created_at: datetime
    updated_at: datetime
