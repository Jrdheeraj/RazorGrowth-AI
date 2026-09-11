"""MarketingAGI API schemas — request/response contracts."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AGIStartRequest(BaseModel):
    objective: str = Field(
        default="Find and prepare the highest-impact marketing work for this business",
        min_length=4,
        max_length=300,
    )
    merchant_id: str | None = None  # validated against membership; never trusted


class AGIStartResponse(BaseModel):
    run_id: str
    status: str
    objective: str


class AGIRunEvent(BaseModel):
    id: str
    run_id: str
    seq: int
    phase: str
    event_type: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class AGIStateSummary(BaseModel):
    objective: str | None = None
    observations: list[str] = Field(default_factory=list)
    hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_gaps: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    retrieval_log: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    workflow: str | None = None
    plan: list[dict[str, Any]] = Field(default_factory=list)
    campaign_draft: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    prepared_action: dict[str, Any] | None = None
    iterations: int = 0
    tool_call_count: int = 0
    duplicate_tool_calls: int = 0
    errors: list[str] = Field(default_factory=list)


class AGIRunResponse(BaseModel):
    id: str
    merchant_id: str
    objective: str
    status: str
    phase: str
    iterations: int
    tool_call_count: int
    started_at: str | None = None
    completed_at: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    state: AGIStateSummary
    result: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)


class AGIRunListResponse(BaseModel):
    runs: list[AGIRunResponse]


class AGIEventsResponse(BaseModel):
    run_id: str
    events: list[AGIRunEvent]


class AGICampaignResponse(BaseModel):
    id: str
    run_id: str | None = None
    campaign_key: str
    workflow: str
    name: str
    objective: str
    channel: str
    integration_status: str
    lifecycle: str
    audience_count: int
    audience: dict[str, Any] | None = None
    content: dict[str, Any] | None = None
    expected_impact: dict[str, Any] | None = None
    estimated_revenue_inr: float | None = None
    success_metric: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    verification: dict[str, Any] | None = None
    action_id: str | None = None
    created_at: str


class AGICampaignListResponse(BaseModel):
    campaigns: list[AGICampaignResponse]


class AGILearningResponse(BaseModel):
    id: str
    campaign_id: str | None = None
    action_id: str | None = None
    status: str
    expected: dict[str, Any] | None = None
    actual: dict[str, Any] | None = None
    verdict: str | None = None
    insights: str | None = None
    created_at: str


class AGILearningListResponse(BaseModel):
    learnings: list[AGILearningResponse]


class AGIHandoffResponse(BaseModel):
    id: str
    run_id: str | None = None
    specialist: str
    status: str
    request: dict[str, Any] | None = None
    response: dict[str, Any] | None = None
    responded_at: str | None = None
    created_at: str


class AGIHandoffListResponse(BaseModel):
    handoffs: list[AGIHandoffResponse]


class AGIToolCatalogResponse(BaseModel):
    tools: list[dict[str, Any]]


class AGIWorkflowCatalogResponse(BaseModel):
    workflows: list[dict[str, Any]]


class AGIStatusResponse(BaseModel):
    agent: str = "MarketingAGI"
    llm_configured: bool
    llm_provider: str | None = None
    llm_model: str | None = None
    integration_status: dict[str, str]
    tools_available: int
    workflows_available: int
