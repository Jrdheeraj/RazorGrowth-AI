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


class SingleAgentRunRequest(BaseModel):
    """
    Launch ONE registered specialist directly from the AI Team workspace.

    Deliberately narrower than ``AgentRunRequest``: a single-agent launch has
    no orchestration mode, because there is no plan to execute.
    """

    params: dict[str, Any] | None = None
    merchant_id: uuid.UUID | None = None
    #: Correlates this run with an existing orchestrator cycle when the
    #: dashboard drives several specialists under one analysis.
    correlation_id: str | None = Field(default=None, max_length=64)


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
    orchestrator_run_id: str | None = None
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


# ── Manager Agent: goal intake, validated plan, workflow report ─────────────
#
# Planning is deliberately SEPARATE from execution. Creating a plan validates
# and freezes the delegation decision but never runs an agent, never creates
# an action and never approves anything. Execution goes through the existing
# orchestrator modes afterwards.


class ManagerPlanRequest(BaseModel):
    """Merchant goal intake for the central Manager Agent."""

    objective: str = Field(min_length=3, max_length=500)
    window_days: int = Field(default=30, ge=1, le=365)
    merchant_id: uuid.UUID | None = None
    #: Optional constraints the merchant stated explicitly. They are recorded
    #: verbatim; they can never widen a guardrail.
    constraints: list[str] = Field(default_factory=list, max_length=12)
    budget: float | None = Field(default=None, ge=0)
    deadline: str | None = Field(default=None, max_length=64)
    #: Untrusted, model-shaped task proposals. Every field is validated
    #: deterministically server-side; unknown agents, duplicate ids, circular
    #: dependencies, unregistered tools and model-issued permissions are
    #: rejected rather than executed.
    proposed_tasks: list[dict[str, Any]] | None = None


class ManagerGoalOut(BaseModel):
    goal: str
    themes: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    time_horizon_days: int = 30
    evidence_status: str = "unknown"
    success_criteria: list[str] = Field(default_factory=list)
    requires_human_approval: bool = True
    blocked_reasons: list[str] = Field(default_factory=list)
    selection_rationale: str | None = None


class ManagerAgentSelectionOut(BaseModel):
    agent_id: str
    reason: str
    matched_tools: list[str] = Field(default_factory=list)


class ManagerTaskOut(BaseModel):
    task_id: str
    agent_id: str
    description: str
    expected_output: str
    depends_on: list[str] = Field(default_factory=list)
    required_inputs: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    priority: str = "normal"
    approval_required: bool = True
    completion_criteria: list[str] = Field(default_factory=list)


class ManagerPlanValidationOut(BaseModel):
    valid: bool
    rejections: list[str] = Field(default_factory=list)
    validated_at: str


class ManagerUnavailableSpecialistOut(BaseModel):
    """An on-topic specialist that exposes no implemented catalog tool.

    Disclosed rather than dropped, so a goal is never silently narrowed.
    """

    agent_id: str
    reason: str
    unimplemented_tools: list[str] = Field(default_factory=list)
    detail: list[dict[str, Any]] = Field(default_factory=list)
    reachable_via: str = "its own workspace endpoint, not the agent tool catalog"


class ManagerPlanLimitsOut(BaseModel):
    max_steps: int
    max_retries: int
    max_replan: int
    max_agents: int


class ManagerPlanResponse(BaseModel):
    model_config = {"extra": "allow"}

    workflow_id: str
    merchant_id: str
    goal: ManagerGoalOut
    selected_agents: list[str] = Field(default_factory=list)
    tasks: list[ManagerTaskOut] = Field(default_factory=list)
    limits: ManagerPlanLimitsOut
    validation: ManagerPlanValidationOut
    #: On-topic specialists that could not be selected, with the reason. A
    #: disclosed limitation, never a silent narrowing of the plan.
    limitations: list[ManagerUnavailableSpecialistOut] = Field(default_factory=list)
    status: str
    #: The plan is a proposal only. Execution is a separate, explicit step.
    executed: bool = False
    requires_human_approval_for_actions: bool = True


class ManagerRosterEntryOut(BaseModel):
    agent_id: str
    description: str
    permissions: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    unimplemented_tools: list[str] = Field(default_factory=list)
    fully_implemented: bool = False
    selectable: bool = False
    can_approve: bool = False
    can_execute: bool = False
    #: Per-tool explanation for why each unresolved name is unresolved.
    unavailable_reasons: list[dict[str, Any]] = Field(default_factory=list)


class ManagerRosterResponse(BaseModel):
    """Live registry contents. The count is never hardcoded."""

    agent_count: int
    agents: list[ManagerRosterEntryOut]
    main_growth_team: list[str] = Field(default_factory=list)
    domain_specialists: list[str] = Field(default_factory=list)


class ManagerAgentEvaluationOut(BaseModel):
    agent_id: str
    status: str
    failure_kind: str | None = None
    detail: str = ""
    errors: list[str] = Field(default_factory=list)
    actions_proposed: int = 0
    latency_ms: int | None = None
    tools_used: list[str] = Field(default_factory=list)
    retryable: bool = False


class ManagerWorkflowReportResponse(BaseModel):
    """
    Workflow status assembled from the REAL AgentRun audit rows.

    Progress rows are reported as progress rows: they are evidence that a run
    happened, not proof of crash-resumable checkpointing.
    """

    model_config = {"extra": "allow"}

    workflow_id: str
    merchant_id: str
    mode: str | None = None
    status: str = "unknown"
    objective: str | None = None
    agents_run: list[AgentRunSummary] = Field(default_factory=list)
    totals: dict[str, int] = Field(default_factory=dict)
    plan: ManagerPlanResponse | None = None
    evaluation: dict[str, Any] = Field(default_factory=dict)
    report: dict[str, Any] = Field(default_factory=dict)
    #: Explicitly honest about what the store does and does not guarantee.
    durable_checkpoint: bool = False
    recoverable_after_restart: bool = False
    recovery_note: str = (
        "AgentRun rows are progress records. They are not a resumable checkpoint; "
        "an interrupted cycle is not automatically continued after a process restart."
    )


class ManagerMetricsResponse(BaseModel):
    """Every figure is computed from real rows, or reported as null."""

    merchant_id: str
    agents_coordinated: int
    tasks_completed: int
    awaiting_approval: int
    active_workflows: int
    total_workflows: int
    window_days: int = 30
    metrics_available: bool = True
    unavailable_reasons: list[str] = Field(default_factory=list)


class ManagerActionsResponse(BaseModel):
    """Pending proposals with their real originating agent and workflow."""

    merchant_id: str
    actions: list[dict[str, Any]] = Field(default_factory=list)
    pending_count: int = 0


# ── growth brief ────────────────────────────────────────────────────────────


class GrowthBriefResponse(BaseModel):
    model_config = {"extra": "allow"}

    merchant_id: str
    window_days: int
    generated_at: str
