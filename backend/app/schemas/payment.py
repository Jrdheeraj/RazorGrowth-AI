"""Payment Pydantic schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PaymentBase(BaseModel):
    order_id: uuid.UUID
    provider: str = Field(default="synthetic", max_length=30)
    provider_payment_id: str | None = Field(default=None, max_length=100)
    amount: Decimal = Field(..., gt=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    status: str = Field(default="pending", max_length=20)
    failure_code: str | None = Field(default=None, max_length=100)
    failure_reason: str | None = None


class PaymentCreate(PaymentBase):
    pass


class PaymentUpdate(BaseModel):
    provider_payment_id: str | None = Field(default=None, max_length=100)
    status: str | None = Field(default=None, max_length=20)
    failure_code: str | None = Field(default=None, max_length=100)
    failure_reason: str | None = None


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    merchant_id: uuid.UUID
    order_id: uuid.UUID
    provider: str
    provider_payment_id: str | None
    amount: Decimal
    currency: str
    status: str
    failure_code: str | None
    failure_reason: str | None
    paid_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PaymentListResponse(BaseModel):
    payments: list[PaymentResponse]
    total: int
