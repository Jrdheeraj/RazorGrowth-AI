"""
CampaignStrategistAgent — Phase 5 Feature 7.

Builds a full campaign strategy for a growth opportunity from REAL data:
segment sizes come from persisted customer insights, revenue estimates
come from the deterministic simulation engine with explicit assumptions,
and the campaign itself is proposed as a Phase 4 send_campaign action in
'requested' state. The agent CANNOT execute campaigns.
"""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.agents.base import AgentContext, AgentResult, BaseGrowthAgent
from backend.app.agents.permissions import AGENT_PERMISSIONS, PROPOSE_ACTION
from backend.app.models.customer_insight import CustomerInsight
from backend.app.models.opportunity import GrowthOpportunity
from backend.app.services.action_service import create_action
from backend.app.services.simulation import SimulationEngine

log = logging.getLogger(__name__)

DEFAULT_CAMPAIGN_CONVERSION = 0.08   # documented assumption
CAMPAIGN_COST_PER_TARGET = Decimal("0.50")


class CampaignStrategistAgent(BaseGrowthAgent):
    NAME = "CampaignStrategistAgent"
    DESCRIPTION = (
        "Designs campaigns (segment, objective, channel, offer) from real "
        "customer data and proposes them as human-approved Phase 4 actions."
    )
    PERMISSIONS = AGENT_PERMISSIONS[NAME]
    TOOLS = ("segment_lookup", "campaign_simulation", "phase4_propose")

    def _run(self, ctx: AgentContext, result: AgentResult) -> None:
        db: Session = ctx.db
        merchant_id: uuid.UUID = ctx.merchant_id

        opportunity = self._pick_opportunity(db, ctx)
        if opportunity is None:
            result.output["note"] = "No open campaign-type opportunity to strategise."
            return

        segment, target_size, avg_ltv = self._resolve_segment(db, ctx)
        if target_size < 1:
            result.output["note"] = (
                f"Segment '{segment}' has no members yet — no campaign proposed "
                "(no fabricated audience)."
            )
            return

        # Deterministic estimate; LLM may refine copy only when configured
        conversion = float(ctx.params.get("expected_conversion", DEFAULT_CAMPAIGN_CONVERSION))
        aov = avg_ltv if avg_ltv > 0 else 500.0
        sim_engine = SimulationEngine(db)
        simulation = sim_engine.simulate_campaign(
            target_customers=target_size,
            expected_conversion=conversion,
            avg_order_value=round(aov, 2),
            cost_per_target=float(CAMPAIGN_COST_PER_TARGET),
        )
        sim_engine.persist(
            simulation,
            merchant_id=merchant_id,
            opportunity_id=opportunity.id,
            created_by_agent=self.NAME,
            inputs={"segment": segment, "conversion_assumption": conversion},
        )
        result.output["simulation"] = simulation.to_dict()

        message_strategy = (
            f"Evidence-based message: {opportunity.title}. Offer tied to the "
            f"detected signal; no invented claims."
        )
        if ctx.llm is not None and ctx.mode == "deep":
            try:
                raw = ctx.llm.generate(
                    system_prompt=(
                        "Draft one short campaign message for the merchant's "
                        "customers. Use only facts provided; never invent "
                        "discounts or statistics."
                    ),
                    user_prompt=f"Opportunity: {opportunity.title}; segment: {segment}",
                )
                message_strategy = str(raw)[:800]
            except Exception as exc:
                result.errors.append(f"llm_copy_skipped: {exc}")

        payload = {
            "campaign_type": str(ctx.params.get("channel", "email")),
            "target": {"segment": segment, "size": target_size},
            "target_count": target_size,
            "metadata": {
                "objective": "revenue_recovery" if "Recover" in opportunity.title else "growth",
                "message_strategy": message_strategy,
                "offer_recommendation": ctx.params.get("offer", "value-focused bundle"),
                "estimated_revenue": simulation.estimated_revenue,
                "confidence_range": [
                    simulation.confidence_low,
                    simulation.confidence_high,
                ],
                "source_opportunity_id": str(opportunity.id),
            },
        }

        self._require(PROPOSE_ACTION)
        action = create_action(
            db,
            merchant_id=merchant_id,
            action_type="send_campaign",
            input_payload=payload,
            requested_by=f"agent:{self.NAME}",
        )
        result.actions_proposed += 1
        result.output["proposed_action"] = {
            "action_id": str(action.id),
            "status": str(action.status),
            "target_segment": segment,
            "target_count": target_size,
        }

    @staticmethod
    def _pick_opportunity(
        db: Session, ctx: AgentContext
    ) -> GrowthOpportunity | None:
        opp_id = ctx.params.get("opportunity_id")
        stmt = (
            select(GrowthOpportunity)
            .where(GrowthOpportunity.merchant_id == ctx.merchant_id)
            .order_by(GrowthOpportunity.expected_revenue.desc())
            .limit(1)
        )
        if opp_id:
            stmt = stmt.where(GrowthOpportunity.id == uuid.UUID(str(opp_id)))
            return db.scalars(stmt).first()
        return db.scalars(stmt.where(GrowthOpportunity.type == "campaign")).first()

    @staticmethod
    def _resolve_segment(
        db: Session, ctx: AgentContext
    ) -> tuple[str, int, float]:
        """Real segment size + average LTV from persisted customer insights."""
        preferred = str(ctx.params.get("segment", "dormant"))
        insights = list(
            db.scalars(
                select(CustomerInsight).where(
                    CustomerInsight.merchant_id == ctx.merchant_id,
                    CustomerInsight.primary_segment == preferred,
                )
            ).all()
        )
        if not insights and preferred != "vip":
            insights = list(
                db.scalars(
                    select(CustomerInsight).where(
                        CustomerInsight.merchant_id == ctx.merchant_id,
                        CustomerInsight.primary_segment == "vip",
                    )
                ).all()
            )
            preferred = "vip"
        if not insights:
            return preferred, 0, 0.0
        avg_ltv = sum(float(i.lifetime_value) for i in insights) / len(insights)
        return preferred, len(insights), avg_ltv
