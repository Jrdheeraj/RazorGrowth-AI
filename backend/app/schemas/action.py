"""
Pydantic schemas for Phase 4 agent actions.

Defines typed payloads for each action type, used for validation
at ingestion and execution time. Never trust arbitrary JSON stored
in AgentAction.input_payload — validate against these schemas.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Base schemas
# ---------------------------------------------------------------------------


class BaseActionPayload(BaseModel):
    """Base payload shared by all action types."""

    merchant_id: str = Field(..., description="Merchant UUID as string")

    @field_validator("merchant_id")
    @classmethod
    def merchant_must_be_valid_uuid(cls, v: str) -> str:
        import uuid as _uuid
        try:
            _uuid.UUID(v)
        except ValueError:
            raise ValueError("merchant_id must be a valid UUID string")
        return v


# ---------------------------------------------------------------------------
# Action-type‑specific payloads
# ---------------------------------------------------------------------------

class SendCampaignPayload(BaseActionPayload):
    """Payload for send_campaign actions."""

    campaign_type: str = Field(..., description="email | sms | push | discount")
    target: Dict[str, Any] = Field(
        ..., description="Target audience specification"
    )
    target_count: int = Field(
        default=0, ge=0, description="Number of targets"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )

    @field_validator("campaign_type")
    @classmethod
    def campaign_type_must_be_valid(cls, v: str) -> str:
        valid = {"email", "sms", "push", "discount"}
        if v not in valid:
            raise ValueError(
                f"campaign_type must be one of {valid}, got '{v}'"
            )
        return v


class CreateDiscountPayload(BaseActionPayload):
    """Payload for create_discount actions."""

    percentage: Decimal = Field(
        ..., ge=0, le=100, description="Discount percentage (0-100)"
    )
    proposed_amount: Optional[Decimal] = Field(
        default=None,
        ge=0,
        description="Optional proposed amount in INR",
    )
    target_customer_ids: List[str] = Field(
        default_factory=list,
        description="Optional list of target customer UUIDs",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )

    @field_validator("percentage")
    @classmethod
    def percentage_must_be_between_0_and_100(cls, v: Decimal) -> Decimal:
        if v < 0 or v > 100:
            raise ValueError("percentage must be between 0 and 100")
        return v


class RetryPaymentPayload(BaseActionPayload):
    """Payload for retry_payment actions."""

    payment_id: str = Field(..., description="Razorpay payment ID to retry")
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )


class GenerateOpportunityPayload(BaseActionPayload):
    """Payload for generate_opportunity actions."""

    opportunity_type: str = Field(
        default="upsell",
        description="Type of opportunity: upsell | cross_sell | campaign | ...",
    )
    title: str = Field(..., description="Human-readable opportunity title")
    description: str = Field(
        default="", description="Optional description"
    )
    confidence: Decimal = Field(
        default=Decimal("0.8"),
        ge=0,
        le=1,
        description="Confidence score 0-1",
    )
    expected_revenue: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        description="Expected revenue in INR",
    )
    target_customer_count: int = Field(
        default=0, ge=0, description="Target customer count"
    )
    reasoning: List[str] = Field(
        default_factory=list, description="Reasoning sentences"
    )
    opportunity_key: Optional[str] = Field(
        default=None,
        description="Idempotency key — if provided, duplicate prevention applies",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )


# -------------------------------------------------------------------------
# Payload validation helpers
# -------------------------------------------------------------------------


class ActionResponse(BaseModel):
    """Response schema for a single action."""

    id: str
    action_type: str
    status: str
    requested_by: str | None = None
    approved_by: str | None = None
    input_payload: dict | None = None
    output_payload: dict | None = None
    error_code: str | None = None
    error_message: str | None = None
    completed_at: str | None = None
    created_at: str
    merchant_id: str


class ActionListResponse(BaseModel):
    """Response schema for listing actions."""

    actions: List[ActionResponse]


class ActionTransitionResponse(BaseModel):
    """Response schema for approve/reject transitions."""

    id: str
    action_type: str
    status: str
    requested_by: str | None = None
    approved_by: str | None = None
    rejected_by: str | None = None
    merchant_id: str
    created_at: str


class AuditEventListResponse(BaseModel):
    """Response schema for listing audit events."""

    audit_events: List[AuditEventResponse]


class ExecutionResponse(BaseModel):
    """Response schema for action execution."""

    action_id: str
    action_type: str
    status: str
    result: dict | None = None
    message: str


class AuditEventResponse(BaseModel):
    """Response schema for an audit event."""

    id: str
    event_type: str
    actor_type: str
    actor_id: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    payload: dict | None = None
    created_at: str


def validate_action_payload(
    action_type: str, raw_payload: Dict[str, Any]
) -> tuple[BaseModel | None, str | None]:
    """
    Validate a raw payload against the schema for the given action type.

    Returns (schema_instance, error_message).
    If validation succeeds, error_message is None.
    If validation fails, schema_instance is None and error_message describes the failure.
    """
    from decimal import Decimal as D

    validators: dict[str, type[BaseModel]] = {
        "send_campaign": SendCampaignPayload,
        "create_discount": CreateDiscountPayload,
        "retry_payment": RetryPaymentPayload,
        "generate_opportunity": GenerateOpportunityPayload,
    }

    schema_class = validators.get(action_type)
    if schema_class is None:
        return None, f"Unknown action type: {action_type}"

    try:
        # Convert merchant_id to string if it's a UUID object
        payload = dict(raw_payload)
        if "merchant_id" in payload and not isinstance(payload["merchant_id"], str):
            payload["merchant_id"] = str(payload["merchant_id"])
        instance = schema_class(**payload)
        return instance, None
    except Exception as exc:
        return None, f"Payload validation failed for {action_type}: {exc}"