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
    # Logical action this lifecycle row belongs to (data.action_id);
    # None for run-level execution details (research, tool calls, phases).
    action_id: str | None = None
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
    # MCP tool-call activity for this run (safe metadata only — never
    # credentials, never raw provider bodies).
    mcp_calls: list[dict[str, Any]] = Field(default_factory=list)
    workflow: str | None = None
    plan: list[dict[str, Any]] = Field(default_factory=list)
    campaign_draft: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    prepared_action: dict[str, Any] | None = None
    iterations: int = 0
    tool_call_count: int = 0
    duplicate_tool_calls: int = 0
    errors: list[str] = Field(default_factory=list)
    # LLM reasoning-engine observability (safe metadata only).
    llm_calls: int = 0
    llm_decisions: list[dict[str, Any]] = Field(default_factory=list)
    reasoning_status: str = "idle"
    current_decision: str | None = None
    reasoning_summary: str | None = None
    llm_degraded: bool = False
    timing: dict[str, Any] = Field(default_factory=dict)


class AGIRunResponse(BaseModel):
    id: str
    merchant_id: str
    objective: str
    status: str
    phase: str
    iterations: int
    tool_call_count: int
    analysis_cycle_id: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    # Canonical action timestamps (persisted agent_actions instants).
    # Recent Work MUST render these — never run.started_at — so the row
    # and the Live Activity timeline agree on ONE backend instant.
    action_created_at: str | None = None
    action_updated_at: str | None = None
    action_completed_at: str | None = None
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
    action_status: str | None = None
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
    # MCP — the standardized tool connectivity layer. ``mcp_tools`` is the
    # normalized, policy-declared catalog (read/write, approval, risk,
    # integration requirement) the Marketing Agent reasons over.
    mcp_tools: list[dict[str, Any]] = Field(default_factory=list)
    mcp_policies: list[dict[str, Any]] = Field(default_factory=list)
    mcp_allowlists: dict[str, list[str]] = Field(default_factory=dict)


class AGIMCPToolCall(BaseModel):
    """One MCP invocation as the dashboard shows it."""

    tool: str
    server: str
    provider: str
    status: str
    read_only: bool
    requires_approval: bool
    risk_level: str
    duration_ms: int = 0
    error_code: str | None = None
    error_message: str | None = None
    cached: bool = False
    retries: int = 0
    summary: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    ts: str | None = None


class AGIWorkflowCatalogResponse(BaseModel):
    workflows: list[dict[str, Any]]


class AGIStatusResponse(BaseModel):
    agent: str = "MarketingAGI"
    llm_configured: bool
    llm_provider: str | None = None
    llm_model: str | None = None
    integration_status: dict[str, str]
    marketing_stack: list[dict[str, Any]] = Field(default_factory=list)
    tools_available: int
    workflows_available: int
    # MCP tool-connectivity layer summary (counts + servers only — never
    # credentials, never connection secrets).
    mcp: dict[str, Any] = Field(default_factory=dict)
