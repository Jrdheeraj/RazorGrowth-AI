"""
Pydantic schemas for the AI analysis API.

These types define the *public* contract of POST /api/ai/analyze.
Internal implementation details (raw LLM responses, chain-of-thought,
DB row objects) are never exposed here.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AnalysisToolCallSummary(BaseModel):
    """One tool invocation recorded during an agentic run."""
    model_config = ConfigDict(from_attributes=False)

    step: int
    tool: str
    result_summary: str
    items_retrieved: int


class AnalysisInsight(BaseModel):
    """
    A single growth insight returned in the analysis response.

    Mirrors GrowthInsight but uses only safe, serialisable types and
    excludes any internal LLM implementation details.
    """
    model_config = ConfigDict(from_attributes=False)

    insight_type: str
    title: str
    summary: str
    confidence: float
    expected_revenue: float | None
    affected_customer_count: int | None
    target_segment: str | None
    recommended_action: str
    risk_level: str
    risks: list[str]
    reasoning_summary: str
    status: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class AnalysisResponse(BaseModel):
    """
    Response body for POST /api/ai/analyze.

    Schema is deterministic — all fields are always present.
    Optional fields default to None / empty collections so clients
    can rely on the shape regardless of outcome.
    """
    model_config = ConfigDict(from_attributes=False)

    analysis_id: str = Field(description="Unique run identifier")
    status: str = Field(
        description="completed | failed | insufficient_evidence | running"
    )
    goal: str
    merchant_id: str | None = None

    # Insights are present only when status == "completed"
    insights: list[AnalysisInsight] = Field(default_factory=list)

    # Retrieval metadata
    retrieval_steps: int = 0
    tool_calls: list[AnalysisToolCallSummary] = Field(default_factory=list)
    evidence_summary: str = ""

    # Failure info
    insufficient_evidence: bool = False
    error: str | None = None
