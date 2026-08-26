"""CustomerIntelligenceAgent — Phase 5 Feature 4 orchestration wrapper."""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.agents.base import AgentContext, AgentResult, BaseGrowthAgent
from backend.app.agents.permissions import AGENT_PERMISSIONS, READ_CUSTOMERS
from backend.app.models.enums import InsightType, OpportunityType
from backend.app.services.customer_intelligence import CustomerIntelligenceService
from backend.app.services.opportunity_upsert import (
    build_opportunity_key,
    upsert_opportunity,
)
from backend.app.services.scoring import OpportunityScoringEngine

log = logging.getLogger(__name__)

SEGMENT_OPPORTUNITY_MAP = {
    InsightType.dormant.value: "Win-back campaign for dormant customers",
    InsightType.churn_risk.value: "Retention outreach for churn-risk customers",
    InsightType.vip.value: "VIP nurture programme",
}


class CustomerIntelligenceAgent(BaseGrowthAgent):
    NAME = "CustomerIntelligenceAgent"
    DESCRIPTION = (
        "Computes deterministic customer metrics (LTV, recency, frequency, "
        "payment success), classifies segments, scores churn risk, and "
        "raises segment-level opportunities."
    )
    PERMISSIONS = AGENT_PERMISSIONS[NAME]
    TOOLS = ("customer_metrics", "segment_classification", "churn_engine")

    def _run(self, ctx: AgentContext, result: AgentResult) -> None:
        self._require(READ_CUSTOMERS)
        db: Session = ctx.db
        merchant_id: uuid.UUID = ctx.merchant_id

        intel = CustomerIntelligenceService(db)
        insights, db_ms = self._timed(intel.refresh, merchant_id)
        result.db_ms += db_ms
        result.insights_generated = len(insights)

        # Segment rollup (deterministic counts from persisted insights)
        by_segment: dict[str, int] = {}
        for insight in insights:
            by_segment[str(insight.primary_segment)] = by_segment.get(
                str(insight.primary_segment), 0
            ) + 1
        high_churn = sum(
            1 for i in insights if i.churn_risk_level in ("high", "critical")
        )
        by_segment["churn_risk_high_or_critical"] = high_churn
        result.output["segments"] = by_segment

        # LLM interpretation is OPTIONAL — deterministic path works without it
        strategy_note: str | None = None
        if ctx.llm is not None and ctx.mode == "deep":
            try:
                raw = ctx.llm.generate(
                    system_prompt=(
                        "You are a customer intelligence analyst. In two "
                        "sentences, interpret the following segments for a "
                        "merchant. Never invent numbers."
                    ),
                    user_prompt=str(by_segment),
                )
                strategy_note = str(raw)[:1000]
            except Exception as exc:  # LLM failure must not fail the agent
                result.errors.append(f"llm_interpretation_skipped: {exc}")
        if strategy_note:
            result.output["strategy_note"] = strategy_note

        # Segment opportunities (reinforcing, never duplicating)
        scoring = OpportunityScoringEngine()
        total_customers = len(insights) or 1
        for segment_value, description in SEGMENT_OPPORTUNITY_MAP.items():
            count = by_segment.get(segment_value, 0)
            if count < 3:
                continue
            avg_ltv = (
                sum(float(i.lifetime_value) for i in insights[:50]) / min(len(insights), 50)
            )
            opportunity_type = (
                OpportunityType.failed_payment_recovery
                if segment_value == InsightType.churn_risk.value
                else OpportunityType.campaign
            )
            key = build_opportunity_key(
                merchant_id, opportunity_type.value, segment_value, 30
            )
            seg_scoring = scoring.score(
                expected_revenue=avg_ltv * count * 0.10,   # explicit 10% response assumption
                confidence=0.6,
                target_customer_count=count,
                evidence_items=3,
                urgency_score=0.7 if segment_value == "dormant" else 0.5,
            )
            _, created = upsert_opportunity(
                db,
                merchant_id=merchant_id,
                opportunity_key=key,
                type_=opportunity_type,
                title=f"{description} ({count} customers)",
                confidence=Decimal("0.60"),
                expected_revenue=Decimal(str(round(avg_ltv * count * 0.10, 2))),
                target_customer_count=count,
                reasoning=[
                    {
                        "basis": "real customer insights",
                        "segment_count": count,
                        "assumed_response_rate": 0.10,
                        "scoring": seg_scoring.to_dict(),
                    }
                ],
            )
            if created:
                result.opportunities_created += 1

        result.output["high_churn_customers"] = high_churn
