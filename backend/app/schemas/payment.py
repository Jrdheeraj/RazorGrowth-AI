"""Payment Pydantic schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from backend.app.models.enums import Currency, PaymentProvider, PaymentStatus


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    merchant_id: uuid.UUID
    order_id: uuid.UUID
    provider: PaymentProvider
    provider_payment_id: str | None
    amount: Decimal
    currency: Currency
    status: PaymentStatus
    failure_code: str | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime
