"""Product Pydantic schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ProductBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    category: str = Field(..., min_length=1, max_length=100)
    price: Decimal = Field(..., ge=0)
    sku: str | None = Field(default=None, max_length=100)
    stock_quantity: int = Field(default=0, ge=0)
    active: bool = True


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    category: str | None = Field(default=None, min_length=1, max_length=100)
    price: Decimal | None = Field(default=None, ge=0)
    sku: str | None = Field(default=None, max_length=100)
    stock_quantity: int | None = Field(default=None, ge=0)
    active: bool | None = None


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    merchant_id: uuid.UUID
    name: str
    description: str | None
    category: str
    price: Decimal
    sku: str | None
    stock_quantity: int
    active: bool
    created_at: datetime
    updated_at: datetime


class ProductListResponse(BaseModel):
    products: list[ProductResponse]
    total: int
