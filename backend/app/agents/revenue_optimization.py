"""
RevenueOptimizationAgent — Phase 5 Feature wrapper around scoring +
simulation: picks the top open opportunity, simulates discount /
campaign scenarios, and proposes ONE bounded Phase 4 action.
"""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.agents.base import AgentContext, AgentResult, BaseGrowthAgent
from backend.app.agents.permissions import AGENT_PERMISSIONS, PROPOSE_ACTION
from backend.app.models.opportunity import GrowthOpportunity
from backend.app.core.config import get_settings
from backend.app.services.action_service import create_action
from backend.app.services.scoring import OpportunityScoringEngine

log = logging.getLogger(__name__)


class RevenueOptimizationAgent(BaseGrowthAgent):
    NAME = "RevenueOptimizationAgent"
    DESCRIPTION = (
        "Ranks open opportunities deterministically and proposes the "
        "highest-impact bounded action (discount or campaign proposal)."
    )
    PERMISSIONS = AGENT_PERMISSIONS[NAME]
    TOOLS = ("opportunity_ranking", "what_if_simulation", "phase4_propose")

    def _run(self, ctx: AgentContext, result: AgentResult) -> None:
        db: Session = ctx.db
        merchant_id: uuid.UUID = ctx.merchant_id

        opportunities = list(
            db.scalars(
                select(GrowthOpportunity)
                .where(GrowthOpportunity.merchant_id == merchant_id)
                .order_by(GrowthOpportunity.expected_revenue.desc())
                .limit(20)
            ).all()
        )
        if not opportunities:
            result.output["note"] = "No opportunities available to optimize."
            return

        engine = OpportunityScoringEngine()
        scored = []
        for opp in opportunities:
            breakdown = engine.score(
                expected_revenue=float(opp.expected_revenue),
                confidence=float(opp.confidence),
                target_customer_count=int(opp.target_customer_count or 0),
                evidence_items=max(1, len(opp.reasoning or [])),
                risk_score=0.2,
            )
            scored.append((breakdown.opportunity_score, opp, breakdown))
        scored.sort(key=lambda t: t[0], reverse=True)
        best_score, best_opp, best_breakdown = scored[0]

        result.output["ranking"] = [
            {
                "opportunity_id": str(opp.id),
                "title": opp.title,
                "score": score,
                "top_factors": {
                    k: getattr(bd, k)
                    for k in ("revenue_potential", "confidence_score", "urgency_score")
                },
            }
            for score, opp, bd in scored[:5]
        ]

        # Simulate a bounded discount scenario on the winner
        settings = get_settings()
        max_pct = min(float(settings.DISCOUNT_MAX_PERCENTAGE), 15.0)
        from backend.app.services.simulation import SimulationEngine

        sim_engine = SimulationEngine(db)
        simulation = sim_engine.simulate_discount(
            discount_percentage=max_pct,
            target_customers=int(best_opp.target_customer_count or 10),
            expected_conversion=0.10,           # documented assumption
            avg_order_value=max(float(best_opp.expected_revenue), 1.0) / 10.0,
        )
        sim_engine.persist(
            simulation,
            merchant_id=merchant_id,
            opportunity_id=best_opp.id,
            created_by_agent=self.NAME,
        )
        result.output["simulation"] = simulation.to_dict()

        if bool(ctx.params.get("propose_action", False)):
            self._require(PROPOSE_ACTION)
            action = create_action(
                db,
                merchant_id=merchant_id,
                action_type="create_discount",
                input_payload={
                    "percentage": max_pct,
                    "proposed_amount": min(
                        float(simulation.estimated_cost),
                        float(settings.GUARDRAIL_MAX_AMOUNT_INR),
                    ),
                    "target_customer_ids": [],
                    "metadata": {
                        "source_opportunity_id": str(best_opp.id),
                        "opportunity_score": best_score,
                        "scoring_breakdown": best_breakdown.to_dict(),
                        "simulation_is_estimate": True,
                    },
                },
                requested_by=f"agent:{self.NAME}",
            )
            result.actions_proposed += 1
            result.output["proposed_action"] = {
                "action_id": str(action.id),
                "status": str(action.status),
            }
