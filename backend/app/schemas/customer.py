"""Customer Pydantic schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


EMAIL_REGEX = re.compile(r"^[^@]+@[^@]+\.[^@]+$")


class CustomerBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., max_length=320)
    phone: str | None = Field(default=None, max_length=30)
    segment: str = Field(default="new", max_length=20)

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not EMAIL_REGEX.match(v):
            raise ValueError("Invalid email format")
        return v


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=30)
    segment: str | None = Field(default=None, max_length=20)

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str | None) -> str | None:
        if v is not None and not EMAIL_REGEX.match(v):
            raise ValueError("Invalid email format")
        return v


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    merchant_id: uuid.UUID
    name: str
    email: str
    phone: str | None
    segment: str
    total_orders: int
    total_spend: Decimal
    created_at: datetime
    updated_at: datetime


class CustomerListResponse(BaseModel):
    customers: list[CustomerResponse]
    total: int
