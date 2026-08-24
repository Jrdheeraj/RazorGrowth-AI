"""GrowthOpportunity Pydantic schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.app.models.enums import OpportunityStatus, OpportunityType


class OpportunityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    merchant_id: uuid.UUID
    opportunity_key: str | None
    type: OpportunityType
    title: str
    description: str | None
    confidence: Decimal
    expected_revenue: Decimal
    target_customer_count: int
    reasoning: list[Any] | None
    status: OpportunityStatus
    created_at: datetime
    updated_at: datetime


class OpportunityLegacyResponse(BaseModel):
    """
    Backwards-compatible response shape matching the Phase 1 API contract.

    The Phase 1 tests assert specific field names (target_product, target_customers,
    reasoning as list, status as string). This schema preserves that contract.
    """
    id: str
    type: str
    title: str
    target_product: str
    target_customers: int
    confidence: float
    expected_revenue: float
    reasoning: list[str]
    status: str
