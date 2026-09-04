"""
Pydantic schemas for Phase 5 Agentic Growth Intelligence APIs.

All response models are structured and JSON-safe. Numeric business values
are floats at the API boundary; every estimate/projection carries an
explicit `is_estimate` / `is_projection` marker so simulated numbers can
never masquerade as measured ones.
"""
from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field


# ── agents ──────────────────────────────────────────────────────────────────


class AgentCapabilityInfo(BaseModel):
    name: str
    description: str
    permissions: list[str]
    tools: list[str]
    can_approve: bool = False
    can_execute: bool = False
    forbidden_capabilities: list[str]


class AgentsListResponse(BaseModel):
    agents: list[AgentCapabilityInfo]
    observability: dict[str, Any] | None = None


class AgentRunRequest(BaseModel):
    objective: str | None = Field(default=None, max_length=500)
    mode: str = Field(default="team", description="'fast', 'deep', 'growth_team', or 'team'")
    window_days: int = Field(default=30, ge=1, le=365)
    merchant_id: uuid.UUID | None = None
    propose_actions: bool = True
    params: dict[str, Any] | None = None


class AgentRunSummary(BaseModel):
    agent: str
    status: str
    opportunities_created: int = 0
    actions_proposed: int = 0
    signals_detected: int = 0
    errors: list[str] = Field(default_factory=list)
    latency_ms: dict[str, int] = Field(default_factory=dict)


class OrchestratorRunResponse(BaseModel):
    orchestrator_run_id: str
    merchant_id: str
    mode: str
    status: str
    totals: dict[str, int]
    debate_id: str | None = None
    action_plan: dict[str, Any] | None = None
    agents: list[dict[str, Any]] = Field(default_factory=list)
    ranked_opportunities: list[dict[str, Any]] = Field(default_factory=list)


class AgentRunRecord(BaseModel):
    id: str
    merchant_id: str | None
    agent_name: str
    status: str
    mode: str
    started_at: str
    completed_at: str | None
    total_latency_ms: int
    llm_latency_ms: int
    db_latency_ms: int
    tool_latency_ms: int
    opportunities_created: int
    actions_proposed: int
    llm_provider: str | None = None
    llm_model: str | None = None
    tools_used: list[Any] | None = None
    errors: list[Any] | None = None


class AgentRunsResponse(BaseModel):
    runs: list[AgentRunRecord]


# ── radar / ranked ──────────────────────────────────────────────────────────


class SignalOut(BaseModel):
    id: str
    signal_type: str
    title: str
    metric: str
    current_value: float
    comparison_value: float
    change_percentage: float | None
    window_days: int
    confidence: float
    evidence: dict[str, Any] | None
    detected_at: str


class RadarResponse(BaseModel):
    merchant_id: str
    signals: list[SignalOut]


class GrowthRadarMetrics(BaseModel):
    captured_revenue: float
    captured_transactions: int
    successful_payments: int
    failed_payments: int
    total_customers: int
    repeat_customers: int
    total_orders: int
    average_order_value: float


class GrowthRadarSufficiency(BaseModel):
    status: str
    message: str
    minimum_required: int
    available: int


class GrowthRadarSignal(BaseModel):
    signal: str
    title: str
    observed_data: dict[str, Any]
    calculated_metric: str
    opportunity: str
    confidence: float
    reason: str
    recommended_action: str


class GrowthRadarResponse(BaseModel):
    merchant_id: str
    generated_at: str
    overall_health: str
    metrics: GrowthRadarMetrics
    data_sufficiency: GrowthRadarSufficiency
    signals: list[GrowthRadarSignal]


class RankedOpportunity(BaseModel):
    rank: int
    opportunity_id: str
    title: str
    type: str
    status: str
    opportunity_score: float
    expected_revenue: float
    confidence: float
    score_breakdown: dict[str, Any]


class RankedOpportunitiesResponse(BaseModel):
    merchant_id: str
    opportunities: list[RankedOpportunity]


# ── customer intelligence ───────────────────────────────────────────────────


class CustomerInsightOut(BaseModel):
    customer_id: str
    primary_segment: str
    segments: list[Any] | None
    order_count: int
    lifetime_value: float
    avg_order_value: float
    recency_days: int | None
    payment_success_rate: float
    failed_payment_count: int
    churn_risk_score: float
    churn_risk_level: str
    churn_reasons: list[Any] | None
    strategy_note: str | None = None


class CustomerInsightsResponse(BaseModel):
    merchant_id: str
    count: int
    insights: list[CustomerInsightOut]


# ── simulations ─────────────────────────────────────────────────────────────


class SimulationRequest(BaseModel):
    scenario_type: str = Field(description="'discount' | 'campaign' | 'payment_recovery'")
    discount_percentage: float | None = None
    target_customers: int | None = Field(default=None, ge=0)
    expected_conversion: float | None = Field(default=None, ge=0, le=1)
    avg_order_value: float | None = Field(default=None, ge=0)
    cost_per_target: float | None = Field(default=None, ge=0)
    failed_payment_value: float | None = Field(default=None, ge=0)
    recovery_rate: float | None = Field(default=None, ge=0, le=1)
    merchant_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None


class SimulationOut(BaseModel):
    id: str
    scenario_type: str
    estimated_revenue: float
    estimated_cost: float
    estimated_profit: float
    expected_conversion: float
    expected_roi: float | None
    confidence_low: float | None
    confidence_high: float | None
    assumptions: list[Any] | None
    is_estimate: bool
    created_by_agent: str | None
    created_at: str


class SimulationsResponse(BaseModel):
    merchant_id: str
    simulations: list[SimulationOut]


# ── experiments ─────────────────────────────────────────────────────────────


class ExperimentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    hypothesis: str | None = Field(default=None, max_length=2000)
    control_group: dict[str, Any] | None = None
    treatment_group: dict[str, Any] | None = None
    target_population_size: int = Field(default=0, ge=0)
    merchant_id: uuid.UUID | None = None


class ExperimentResultOut(BaseModel):
    statistical_status: str
    uplift_percentage: float | None
    control_size: int
    treatment_size: int


class ExperimentOut(BaseModel):
    id: str
    name: str
    status: str
    hypothesis: str | None
    control_group: dict[str, Any] | None
    treatment_group: dict[str, Any] | None
    target_population_size: int
    latest_result: ExperimentResultOut | None = None


class ExperimentsResponse(BaseModel):
    merchant_id: str
    experiments: list[ExperimentOut]


# ── memory ──────────────────────────────────────────────────────────────────


class MemoryEntryOut(BaseModel):
    id: str
    memory_type: str
    content: str
    importance: float
    outcome_variance_pct: float | None
    created_at: str


class GrowthMemoryResponse(BaseModel):
    merchant_id: str
    memories: list[MemoryEntryOut]


# ── growth brief ────────────────────────────────────────────────────────────


class GrowthBriefResponse(BaseModel):
    model_config = {"extra": "allow"}

    merchant_id: str
    window_days: int
    generated_at: str
