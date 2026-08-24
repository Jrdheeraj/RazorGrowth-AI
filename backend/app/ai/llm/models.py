"""
Pydantic models for structured LLM outputs.

All AI-generated data must pass through these schemas before reaching
application logic. Validation failures are caught and handled safely —
they never become financial actions.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class EvidenceItem(BaseModel):
    """A single piece of evidence supporting an AI insight."""
    source_type: str = Field(description="Entity type: product, customer, order, payment, opportunity")
    source_id: str = Field(description="Stable identifier of the source record")
    description: str = Field(description="Human-readable description of what this evidence shows")
    relevance: str = Field(description="Why this evidence is relevant to the insight")


class GrowthInsight(BaseModel):
    """
    Structured AI output for a single growth opportunity insight.

    Revenue figures must be grounded in retrieved data — the LLM must
    not invent numbers.  If evidence is insufficient the confidence field
    should be low and expected_revenue should be null.

    All fields map directly to the GrowthOpportunity DB model so the
    analysis service can persist them without any transformation.
    """
    insight_type: str = Field(
        description=(
            "One of: cross_sell, upsell, failed_payment_recovery, "
            "campaign, checkout_optimization, customer_segment, product_opportunity, "
            "revenue_leakage"
        )
    )
    title: str = Field(max_length=255, description="Concise insight title")
    summary: str = Field(description="Clear explanation of the opportunity and its basis")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0–1")
    expected_revenue: float | None = Field(
        default=None,
        description=(
            "Expected revenue uplift in INR, derived from evidence only. "
            "Null if insufficient data."
        ),
    )
    affected_customer_count: int | None = Field(
        default=None, ge=0, description="Number of customers affected, from evidence"
    )
    target_segment: str | None = Field(
        default=None,
        description=(
            "Target customer segment: new, returning, vip, at_risk, churned, or 'all'"
        ),
    )
    evidence: list[EvidenceItem] = Field(
        default_factory=list,
        description="Evidence items supporting this insight — must reference real data",
    )
    recommended_action: str = Field(description="Specific, actionable recommendation")
    risk_level: str = Field(
        default="low",
        description="Risk level of the recommended action: low, medium, high, critical",
    )
    risks: list[str] = Field(
        default_factory=list,
        description="Potential risks or caveats",
    )
    reasoning_summary: str = Field(
        description="Concise summary of the reasoning steps taken (NOT raw chain-of-thought)"
    )
    # Status is set by the application layer after guardrail evaluation —
    # the LLM should not set this field.
    status: str = Field(
        default="pending_approval",
        description="Lifecycle status — always 'pending_approval' from the LLM",
    )

    @field_validator("insight_type")
    @classmethod
    def validate_insight_type(cls, v: str) -> str:
        allowed = {
            "cross_sell", "upsell", "failed_payment_recovery",
            "campaign", "checkout_optimization",
            "customer_segment", "product_opportunity", "revenue_leakage",
        }
        if v not in allowed:
            raise ValueError(f"insight_type must be one of {allowed}, got {v!r}")
        return v

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("confidence must be between 0 and 1")
        return round(v, 4)

    @field_validator("risk_level")
    @classmethod
    def validate_risk_level(cls, v: str) -> str:
        allowed = {"low", "medium", "high", "critical"}
        if v not in allowed:
            raise ValueError(f"risk_level must be one of {allowed}, got {v!r}")
        return v


class GrowthAnalysisResult(BaseModel):
    """Container for one or more insights from a growth analysis run."""
    insights: list[GrowthInsight] = Field(default_factory=list)
    insufficient_evidence: bool = Field(
        default=False,
        description="True when there is not enough data to produce reliable insights",
    )
    evidence_summary: str = Field(
        default="",
        description="Summary of what evidence was retrieved and used",
    )
