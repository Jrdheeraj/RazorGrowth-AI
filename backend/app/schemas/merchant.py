"""Merchant Pydantic schemas."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr

from backend.app.models.enums import Currency, MerchantStatus


class MerchantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    email: str
    status: MerchantStatus
    currency: Currency
    created_at: datetime
    updated_at: datetime
