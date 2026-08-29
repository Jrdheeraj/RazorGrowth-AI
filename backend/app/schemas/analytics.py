"""Analytics Pydantic schemas."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class RevenueAnalytics(BaseModel):
    current_period: Decimal
    previous_period: Decimal
    change_percentage: float | None
    trend: str  # up, down, flat


class OrderAnalytics(BaseModel):
    total_orders: int
    completed_orders: int
    cancelled_orders: int
    average_order_value: Decimal
    orders_by_status: dict[str, int]


class CustomerAnalytics(BaseModel):
    total_customers: int
    new_customers: int
    returning_customers: int
    repeat_customers: int
    at_risk_customers: int
    churned_customers: int
    average_ltv: Decimal


class OpportunityAnalytics(BaseModel):
    total_opportunities: int
    pending_approval: int
    approved: int
    rejected: int
    executing: int
    completed: int
    failed: int
    average_score: float | None
    by_type: dict[str, int]


class RecommendationAnalytics(BaseModel):
    total_recommendations: int
    draft: int
    pending_approval: int
    changes_requested: int
    approved: int
    rejected: int
    executing: int
    completed: int
    failed: int
    average_confidence: float | None


class ExecutionAnalytics(BaseModel):
    total_executions: int
    successful: int
    failed: int
    idempotent_skipped: int
    by_action_type: dict[str, int]


class AgentActivityAnalytics(BaseModel):
    total_runs: int
    completed_runs: int
    failed_runs: int
    total_opportunities_created: int
    total_actions_proposed: int
    total_insights_generated: int
    total_experiments_proposed: int
    by_agent: dict[str, dict[str, int]]


class ExperimentAnalytics(BaseModel):
    total_experiments: int
    proposed: int
    running: int
    completed: int
    measurement_pending: int
    cancelled: int
    with_significant_results: int


class PredictedVsActualAnalytics(BaseModel):
    metric: str
    baseline: Decimal
    predicted: Decimal | None
    actual: Decimal | None
    variance: float | None
    variance_percentage: float | None
    outcome: str | None  # exceeded, met, missed


class AnalyticsOverviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    merchant_id: str
    period_days: int
    generated_at: datetime
    revenue: RevenueAnalytics
    orders: OrderAnalytics
    customers: CustomerAnalytics
    opportunities: OpportunityAnalytics
    recommendations: RecommendationAnalytics
    executions: ExecutionAnalytics
    agent_activity: AgentActivityAnalytics
    experiments: ExperimentAnalytics
    predicted_vs_actual: list[PredictedVsActualAnalytics]


class TimeSeriesPoint(BaseModel):
    date: str
    value: Decimal


class RevenueTimeSeriesResponse(BaseModel):
    merchant_id: str
    period_days: int
    data: list[TimeSeriesPoint]


class OrderTimeSeriesResponse(BaseModel):
    merchant_id: str
    period_days: int
    data: list[TimeSeriesPoint]


class CustomerTimeSeriesResponse(BaseModel):
    merchant_id: str
    period_days: int
    data: list[TimeSeriesPoint]