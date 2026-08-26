"""
GrowthDiscoveryAgent — turns Growth Radar signals into scored,
deduplicated growth opportunities.

Permission profile: read-only over commerce data. It creates
opportunities (pending approval, never actions) and reinforces existing
ones instead of duplicating them.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.agents.base import AgentContext, AgentResult, BaseGrowthAgent
from backend.app.agents.permissions import AGENT_PERMISSIONS, READ_ORDERS
from backend.app.models.enums import OpportunityType
from backend.app.services.opportunity_upsert import (
    build_opportunity_key,
    upsert_opportunity,
)
from backend.app.services.radar import GrowthRadarService
from backend.app.services.scoring import OpportunityScoringEngine

log = logging.getLogger(__name__)

# signal type → opportunity type mapping (deterministic)
SIGNAL_TO_OPPORTUNITY = {
    "payment_failures": OpportunityType.failed_payment_recovery,
    "payment_recovery_opportunity": OpportunityType.failed_payment_recovery,
    "abandoned_customers": OpportunityType.campaign,
    "segment_opportunity": OpportunityType.campaign,
    "inactive_high_value": OpportunityType.campaign,
    "declining_repeat_purchases": OpportunityType.checkout_optimization,
    "revenue_drop": OpportunityType.campaign,
    "emerging_growth": OpportunityType.upsell,
    "unusual_order_behavior": OpportunityType.cross_sell,
}


class GrowthDiscoveryAgent(BaseGrowthAgent):
    NAME = "GrowthDiscoveryAgent"
    DESCRIPTION = (
        "Detects revenue, churn, and payment signals from real commerce "
        "data and converts them into deduplicated, scored opportunities."
    )
    PERMISSIONS = AGENT_PERMISSIONS[NAME]
    TOOLS = ("growth_radar", "opportunity_upsert", "opportunity_scoring")

    def _run(self, ctx: AgentContext, result: AgentResult) -> None:
        self._require(READ_ORDERS)  # sanity: read perms present
        db: Session = ctx.db
        merchant_id: uuid.UUID = ctx.merchant_id
        window_days = int(ctx.params.get("window_days", 30))

        radar = GrowthRadarService(db)
        signals, db_ms = self._timed(
            radar.detect, merchant_id, window_days=window_days, persist=True
        )
        result.signals_detected = len(signals)
        result.db_ms += db_ms
        result.output["signals"] = [
            {
                "signal_type": s["signal_type"],
                "title": s["title"],
                "current_value": s["current_value"],
                "change_percentage": s["change_percentage"],
            }
            for s in signals
        ]

        engine = OpportunityScoringEngine()
        created_keys: list[str] = []
        for signal in signals:
            opp_type = SIGNAL_TO_OPPORTUNITY.get(signal["signal_type"])
            if opp_type is None:
                continue
            segment = str(signal["evidence"].get("segment", "all"))
            key = build_opportunity_key(
                merchant_id, opp_type.value, f"{segment}:{signal['signal_type']}", window_days
            )
            change = abs(signal.get("change_percentage") or 0)
            urgency = min(1.0, 0.4 + change / 100.0) if change else 0.5
            expected_revenue = max(float(signal["current_value"]), 0.0)

            scoring = engine.score(
                expected_revenue=expected_revenue,
                confidence=signal["confidence"],
                evidence_items=1 + len(signal["evidence"]),
                urgency_score=urgency,
                risk_score=0.2,
                implementation_cost=0.2,
            )
            opp, created = upsert_opportunity(
                db,
                merchant_id=merchant_id,
                opportunity_key=key,
                type_=opp_type,
                title=signal["title"][:255],
                confidence=Decimal(str(min(max(signal["confidence"], 0.0), 1.0))),
                expected_revenue=Decimal(str(expected_revenue)),
                reasoning=[
                    {"source_signal": signal["signal_type"], "evidence": signal["evidence"]},
                    {"scoring": scoring.to_dict()},
                ],
            )
            created_keys.append(key)
            if created:
                result.opportunities_created += 1

        result.output["opportunity_keys"] = created_keys
