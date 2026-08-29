"""Recommendation Pydantic schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RecommendationBase(BaseModel):
    type: str
    title: str
    description: str | None = None
    proposed_action: str
    target_segment: str | None = None
    rationale: str | None = None
    evidence: list[Any] | None = None
    confidence: Decimal = Field(ge=0, le=1)
    assumptions: list[Any] | None = None
    expected_revenue: Decimal = Field(ge=0)
    expected_conversion: Decimal | None = Field(default=None, ge=0, le=1)
    estimated_cost: Decimal | None = Field(default=None, ge=0)
    guardrails: dict[str, Any] | None = None
    requires_approval: bool = True


class RecommendationCreate(RecommendationBase):
    opportunity_id: uuid.UUID | None = None
    recommendation_key: str | None = None
    simulation_snapshot: dict[str, Any] | None = None


class RecommendationUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    proposed_action: str | None = None
    target_segment: str | None = None
    rationale: str | None = None
    evidence: list[Any] | None = None
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    assumptions: list[Any] | None = None
    expected_revenue: Decimal | None = Field(default=None, ge=0)
    expected_conversion: Decimal | None = Field(default=None, ge=0, le=1)
    estimated_cost: Decimal | None = Field(default=None, ge=0)
    guardrails: dict[str, Any] | None = None
    requires_approval: bool | None = None


class RecommendationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    merchant_id: uuid.UUID
    opportunity_id: uuid.UUID | None
    recommendation_key: str | None
    type: str
    title: str
    description: str | None
    proposed_action: str
    target_segment: str | None
    rationale: str | None
    evidence: list[Any] | None
    confidence: Decimal
    assumptions: list[Any] | None
    expected_revenue: Decimal
    expected_conversion: Decimal | None
    estimated_cost: Decimal | None
    guardrails: dict[str, Any] | None
    requires_approval: bool
    version: int
    approved_version: int | None
    status: str
    simulation_snapshot: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class RecommendationListResponse(BaseModel):
    recommendations: list[RecommendationResponse]


class ApprovalDecisionRequest(BaseModel):
    decision: str  # approved | rejected | changes_requested
    comment: str | None = None


class ApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    merchant_id: uuid.UUID
    recommendation_id: uuid.UUID
    status: str
    approver_user_id: uuid.UUID | None
    approver_email: str | None
    decision: str | None
    comment: str | None
    decided_at: datetime | None
    recommendation_snapshot: dict[str, Any] | None
    simulation_snapshot: dict[str, Any] | None
    approved_version: int | None
    created_at: datetime


class ApprovalListResponse(BaseModel):
    approvals: list[ApprovalResponse]