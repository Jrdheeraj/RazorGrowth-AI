"""Analytics Service — tenant-scoped analytics for merchant dashboard."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from backend.app.models.agent_run import AgentRun
from backend.app.models.agent_action import AgentAction
from backend.app.models.enums import (
    AgentActionStatus,
    AgentRunStatus,
    ExperimentStatus,
    OpportunityStatus,
    OrderStatus,
    PaymentStatus,
    RecommendationStatus,
)
from backend.app.models.customer import Customer
from backend.app.models.enums import CustomerSegment
from backend.app.models.experiment import Experiment, ExperimentResult
from backend.app.models.opportunity import GrowthOpportunity
from backend.app.models.order import Order
from backend.app.models.payment import Payment
from backend.app.models.recommendation import Recommendation


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _period_start(days: int) -> datetime:
    return _utcnow() - timedelta(days=days)


def _previous_period_start(days: int) -> datetime:
    return _utcnow() - timedelta(days=days * 2)


class AnalyticsService:
    """Tenant-scoped analytics service."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_overview(
        self,
        merchant_id: uuid.UUID,
        period_days: int = 30,
    ) -> dict[str, Any]:
        """Get comprehensive analytics overview for a merchant."""
        now = _utcnow()
        period_start = now - timedelta(days=period_days)
        prev_start = now - timedelta(days=period_days * 2)

        # Revenue analytics
        revenue = self._get_revenue_analytics(merchant_id, period_start, prev_start)

        # Order analytics
        orders = self._get_order_analytics(merchant_id, period_start)

        # Customer analytics
        customers = self._get_customer_analytics(merchant_id)

        # Opportunity analytics
        opportunities = self._get_opportunity_analytics(merchant_id, period_start)

        # Recommendation analytics
        recommendations = self._get_recommendation_analytics(merchant_id, period_start)

        # Execution analytics
        executions = self._get_execution_analytics(merchant_id, period_start)

        # Agent activity analytics
        agent_activity = self._get_agent_activity_analytics(merchant_id, period_start)

        # Experiment analytics
        experiments = self._get_experiment_analytics(merchant_id, period_start)

        # Predicted vs Actual
        predicted_vs_actual = self._get_predicted_vs_actual(merchant_id, period_start)

        return {
            "merchant_id": str(merchant_id),
            "period_days": period_days,
            "generated_at": now,
            "revenue": revenue,
            "orders": orders,
            "customers": customers,
            "opportunities": opportunities,
            "recommendations": recommendations,
            "executions": executions,
            "agent_activity": agent_activity,
            "experiments": experiments,
            "predicted_vs_actual": predicted_vs_actual,
        }

    def _get_revenue_analytics(
        self,
        merchant_id: uuid.UUID,
        period_start: datetime,
        prev_start: datetime,
    ) -> dict[str, Any]:
        # Current period revenue
        cur_rev = self.db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .join(Order, Payment.order_id == Order.id)
            .where(Payment.merchant_id == merchant_id)
            .where(Payment.status == PaymentStatus.captured.value)
            .where(Order.status == OrderStatus.paid.value)
            .where(Order.created_at >= period_start)
        ).scalar_one()

        # Previous period revenue
        prev_rev = self.db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .join(Order, Payment.order_id == Order.id)
            .where(Payment.merchant_id == merchant_id)
            .where(Payment.status == PaymentStatus.captured.value)
            .where(Order.status == OrderStatus.paid.value)
            .where(Order.created_at >= prev_start)
            .where(Order.created_at < period_start)
        ).scalar_one()

        cur_rev = Decimal(str(cur_rev))
        prev_rev = Decimal(str(prev_rev))

        change_pct = None
        if prev_rev > 0:
            change_pct = float(((cur_rev - prev_rev) / prev_rev) * 100)

        trend = "flat"
        if change_pct is not None:
            if change_pct > 5:
                trend = "up"
            elif change_pct < -5:
                trend = "down"

        return {
            "current_period": cur_rev,
            "previous_period": prev_rev,
            "change_percentage": change_pct,
            "trend": trend,
        }

    def _get_order_analytics(
        self,
        merchant_id: uuid.UUID,
        period_start: datetime,
    ) -> dict[str, Any]:
        # Total orders in period
        total = self.db.execute(
            select(func.count(Order.id))
            .where(Order.merchant_id == merchant_id)
            .where(Order.created_at >= period_start)
        ).scalar_one()

        # Orders by status
        status_rows = self.db.execute(
            select(Order.status, func.count(Order.id))
            .where(Order.merchant_id == merchant_id)
            .where(Order.created_at >= period_start)
            .group_by(Order.status)
        ).all()

        by_status = {str(status): int(count) for status, count in status_rows}

        completed = by_status.get("paid", 0) + by_status.get("delivered", 0)
        cancelled = by_status.get("cancelled", 0) + by_status.get("refunded", 0)

        # Average order value
        aov_row = self.db.execute(
            select(func.coalesce(func.avg(Order.total), 0))
            .where(Order.merchant_id == merchant_id)
            .where(Order.created_at >= period_start)
            .where(Order.status.in_([OrderStatus.paid.value, OrderStatus.delivered.value]))
        ).scalar_one()

        return {
            "total_orders": int(total),
            "completed_orders": completed,
            "cancelled_orders": cancelled,
            "average_order_value": Decimal(str(aov_row)),
            "orders_by_status": by_status,
        }

    def _get_customer_analytics(self, merchant_id: uuid.UUID) -> dict[str, Any]:
        # Total customers
        total = self.db.execute(
            select(func.count(Customer.id))
            .where(Customer.merchant_id == merchant_id)
        ).scalar_one()

        # Customers by segment
        segment_rows = self.db.execute(
            select(Customer.segment, func.count(Customer.id))
            .where(Customer.merchant_id == merchant_id)
            .group_by(Customer.segment)
        ).all()

        segment_counts = {str(seg): int(count) for seg, count in segment_rows}

        new_cust = segment_counts.get("new", 0)
        returning = segment_counts.get("returning", 0)
        repeat = segment_counts.get("repeat_customer", 0)  # This is from InsightType
        at_risk = segment_counts.get("at_risk", 0)
        churned = segment_counts.get("churned", 0)

        # Average LTV
        avg_ltv = self.db.execute(
            select(func.coalesce(func.avg(Customer.total_spend), 0))
            .where(Customer.merchant_id == merchant_id)
        ).scalar_one()

        return {
            "total_customers": int(total),
            "new_customers": new_cust,
            "returning_customers": returning,
            "repeat_customers": repeat,
            "at_risk_customers": at_risk,
            "churned_customers": churned,
            "average_ltv": Decimal(str(avg_ltv)),
        }

    def _get_opportunity_analytics(
        self,
        merchant_id: uuid.UUID,
        period_start: datetime,
    ) -> dict[str, Any]:
        # Total opportunities
        total = self.db.execute(
            select(func.count(GrowthOpportunity.id))
            .where(GrowthOpportunity.merchant_id == merchant_id)
            .where(GrowthOpportunity.created_at >= period_start)
        ).scalar_one()

        # By status
        status_rows = self.db.execute(
            select(GrowthOpportunity.status, func.count(GrowthOpportunity.id))
            .where(GrowthOpportunity.merchant_id == merchant_id)
            .where(GrowthOpportunity.created_at >= period_start)
            .group_by(GrowthOpportunity.status)
        ).all()

        by_status = {str(s): int(c) for s, c in status_rows}

        # By type
        type_rows = self.db.execute(
            select(GrowthOpportunity.type, func.count(GrowthOpportunity.id))
            .where(GrowthOpportunity.merchant_id == merchant_id)
            .where(GrowthOpportunity.created_at >= period_start)
            .group_by(GrowthOpportunity.type)
        ).all()

        by_type = {str(t): int(c) for t, c in type_rows}

        # Average score (using confidence as proxy)
        avg_score = self.db.execute(
            select(func.coalesce(func.avg(GrowthOpportunity.confidence), 0))
            .where(GrowthOpportunity.merchant_id == merchant_id)
            .where(GrowthOpportunity.created_at >= period_start)
        ).scalar_one()

        return {
            "total_opportunities": int(total),
            "pending_approval": by_status.get("pending_approval", 0),
            "approved": by_status.get("approved", 0),
            "rejected": by_status.get("rejected", 0),
            "executing": by_status.get("executing", 0),
            "completed": by_status.get("completed", 0),
            "failed": by_status.get("failed", 0),
            "average_score": float(avg_score) * 100 if avg_score else None,
            "by_type": by_type,
        }

    def _get_recommendation_analytics(
        self,
        merchant_id: uuid.UUID,
        period_start: datetime,
    ) -> dict[str, Any]:
        # Total recommendations
        total = self.db.execute(
            select(func.count(Recommendation.id))
            .where(Recommendation.merchant_id == merchant_id)
            .where(Recommendation.created_at >= period_start)
        ).scalar_one()

        # By status
        status_rows = self.db.execute(
            select(Recommendation.status, func.count(Recommendation.id))
            .where(Recommendation.merchant_id == merchant_id)
            .where(Recommendation.created_at >= period_start)
            .group_by(Recommendation.status)
        ).all()

        by_status = {str(s): int(c) for s, c in status_rows}

        # Average confidence
        avg_conf = self.db.execute(
            select(func.coalesce(func.avg(Recommendation.confidence), 0))
            .where(Recommendation.merchant_id == merchant_id)
            .where(Recommendation.created_at >= period_start)
        ).scalar_one()

        return {
            "total_recommendations": int(total),
            "draft": by_status.get("draft", 0),
            "pending_approval": by_status.get("pending_approval", 0),
            "changes_requested": by_status.get("changes_requested", 0),
            "approved": by_status.get("approved", 0),
            "rejected": by_status.get("rejected", 0),
            "executing": by_status.get("executing", 0),
            "completed": by_status.get("completed", 0),
            "failed": by_status.get("failed", 0),
            "average_confidence": float(avg_conf) if avg_conf else None,
        }

    def _get_execution_analytics(
        self,
        merchant_id: uuid.UUID,
        period_start: datetime,
    ) -> dict[str, Any]:
        # Total executions (completed + failed + idempotent)
        total = self.db.execute(
            select(func.count(AgentAction.id))
            .where(AgentAction.merchant_id == merchant_id)
            .where(AgentAction.created_at >= period_start)
        ).scalar_one()

        # By status
        status_rows = self.db.execute(
            select(AgentAction.status, func.count(AgentAction.id))
            .where(AgentAction.merchant_id == merchant_id)
            .where(AgentAction.created_at >= period_start)
            .group_by(AgentAction.status)
        ).all()

        by_status = {str(s): int(c) for s, c in status_rows}

        successful = by_status.get("completed", 0)
        failed = by_status.get("failed", 0)
        idempotent = by_status.get("requested", 0)  # Actually we need to check audit for skipped

        # By action type
        type_rows = self.db.execute(
            select(AgentAction.action_type, func.count(AgentAction.id))
            .where(AgentAction.merchant_id == merchant_id)
            .where(AgentAction.created_at >= period_start)
            .group_by(AgentAction.action_type)
        ).all()

        by_type = {str(t): int(c) for t, c in type_rows}

        return {
            "total_executions": int(total),
            "successful": successful,
            "failed": failed,
            "idempotent_skipped": idempotent,
            "by_action_type": by_type,
        }

    def _get_agent_activity_analytics(
        self,
        merchant_id: uuid.UUID,
        period_start: datetime,
    ) -> dict[str, Any]:
        # Total agent runs
        total_runs = self.db.execute(
            select(func.count(AgentRun.id))
            .where(AgentRun.merchant_id == merchant_id)
            .where(AgentRun.started_at >= period_start)
        ).scalar_one()

        # By status
        status_rows = self.db.execute(
            select(AgentRun.status, func.count(AgentRun.id))
            .where(AgentRun.merchant_id == merchant_id)
            .where(AgentRun.started_at >= period_start)
            .group_by(AgentRun.status)
        ).all()

        completed_runs = sum(c for s, c in status_rows if str(s) == "completed")
        failed_runs = sum(c for s, c in status_rows if str(s) == "failed")

        # Aggregated totals
        totals = self.db.execute(
            select(
                func.coalesce(func.sum(AgentRun.opportunities_created), 0),
                func.coalesce(func.sum(AgentRun.actions_proposed), 0),
                func.coalesce(func.sum(AgentRun.insights_generated), 0),
                func.coalesce(func.sum(AgentRun.experiments_proposed), 0),
            )
            .where(AgentRun.merchant_id == merchant_id)
            .where(AgentRun.started_at >= period_start)
        ).one()

        # By agent
        agent_rows = self.db.execute(
            select(
                AgentRun.agent_name,
                func.count(AgentRun.id),
                func.coalesce(func.sum(AgentRun.opportunities_created), 0),
                func.coalesce(func.sum(AgentRun.actions_proposed), 0),
                func.coalesce(func.sum(AgentRun.insights_generated), 0),
                func.coalesce(func.sum(AgentRun.experiments_proposed), 0),
            )
            .where(AgentRun.merchant_id == merchant_id)
            .where(AgentRun.started_at >= period_start)
            .group_by(AgentRun.agent_name)
        ).all()

        by_agent = {}
        for name, runs, opps, actions, insights, exps in agent_rows:
            by_agent[name] = {
                "runs": int(runs),
                "opportunities_created": int(opps),
                "actions_proposed": int(actions),
                "insights_generated": int(insights),
                "experiments_proposed": int(exps),
            }

        return {
            "total_runs": int(total_runs),
            "completed_runs": int(completed_runs),
            "failed_runs": int(failed_runs),
            "total_opportunities_created": int(totals[0]),
            "total_actions_proposed": int(totals[1]),
            "total_insights_generated": int(totals[2]),
            "total_experiments_proposed": int(totals[3]),
            "by_agent": by_agent,
        }

    def _get_experiment_analytics(
        self,
        merchant_id: uuid.UUID,
        period_start: datetime,
    ) -> dict[str, Any]:
        # Total experiments
        total = self.db.execute(
            select(func.count(Experiment.id))
            .where(Experiment.merchant_id == merchant_id)
            .where(Experiment.created_at >= period_start)
        ).scalar_one()

        # By status
        status_rows = self.db.execute(
            select(Experiment.status, func.count(Experiment.id))
            .where(Experiment.merchant_id == merchant_id)
            .where(Experiment.created_at >= period_start)
            .group_by(Experiment.status)
        ).all()

        by_status = {str(s): int(c) for s, c in status_rows}

        # Experiments with significant results
        sig_count = self.db.execute(
            select(func.count(ExperimentResult.id))
            .join(Experiment, ExperimentResult.experiment_id == Experiment.id)
            .where(Experiment.merchant_id == merchant_id)
            .where(ExperimentResult.statistical_status != "measurement_pending")
        ).scalar_one()

        return {
            "total_experiments": int(total),
            "proposed": by_status.get("proposed", 0),
            "running": by_status.get("running", 0),
            "completed": by_status.get("completed", 0),
            "measurement_pending": by_status.get("measurement_pending", 0),
            "cancelled": by_status.get("cancelled", 0),
            "with_significant_results": int(sig_count),
        }

    def _get_predicted_vs_actual(
        self,
        merchant_id: uuid.UUID,
        period_start: datetime,
    ) -> list[dict[str, Any]]:
        """Compare predicted vs actual for completed executions."""
        results = []

        # Get completed actions with simulation snapshots
        actions = self.db.execute(
            select(AgentAction)
            .where(AgentAction.merchant_id == merchant_id)
            .where(AgentAction.status == AgentActionStatus.completed.value)
            .where(AgentAction.completed_at >= period_start)
            .where(AgentAction.output_payload.isnot(None))
        ).scalars().all()

        for action in actions:
            output = action.output_payload or {}
            # Try to extract predicted from simulation snapshot or metadata
            predicted = None
            actual = None
            metric = "revenue"

            if "estimated_revenue" in output:
                predicted = Decimal(str(output["estimated_revenue"]))
            elif "result" in output and isinstance(output["result"], dict):
                predicted = Decimal(str(output["result"].get("estimated_revenue", 0)))

            # For actual, we'd need to measure post-execution
            # This is a placeholder - real implementation would query actual results
            actual = None

            variance = None
            variance_pct = None
            outcome = None

            if predicted and actual:
                variance = float(actual - predicted)
                variance_pct = float((actual - predicted) / predicted * 100) if predicted > 0 else None
                if variance > 0:
                    outcome = "exceeded"
                elif variance == 0:
                    outcome = "met"
                else:
                    outcome = "missed"

            results.append({
                "metric": metric,
                "baseline": Decimal("0"),  # Would need historical data
                "predicted": predicted,
                "actual": actual,
                "variance": variance,
                "variance_percentage": variance_pct,
                "outcome": outcome,
            })

        return results