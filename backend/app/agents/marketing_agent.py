"""
Marketing Agent — AI Growth Team Marketing Specialist.

The Marketing Agent focuses on audience analysis, segmentation, retention
strategy, acquisition strategy, win-back campaigns, campaign strategy,
messaging, and campaign recommendations.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.agents.base import AgentContext, AgentResult, BaseGrowthAgent
from backend.app.agents.permissions import (
    AGENT_PERMISSIONS,
    READ_MERCHANT,
    READ_CUSTOMERS,
    READ_ORDERS,
    READ_CAMPAIGNS,
    READ_OPPORTUNITIES,
    SIMULATE,
    PROPOSE_ACTION,
)
from backend.app.models.agent_debate import AgentFinding, AgentMessage
from backend.app.models.customer_insight import CustomerInsight
from backend.app.models.enums import AgentSpecialty, FindingType, InsightType
from backend.app.models.opportunity import GrowthOpportunity
from backend.app.repositories.agent_debate import (
    AgentFindingRepository,
    AgentMessageRepository,
)
from backend.app.agents.campaign_strategist import CampaignStrategistAgent
from backend.app.services.customer_intelligence import CustomerIntelligenceService
from backend.app.services.simulation import SimulationEngine

log = logging.getLogger(__name__)


class MarketingAgent(BaseGrowthAgent):
    """
    Marketing Agent — AI Growth Team Marketing Specialist.

    Responsibilities:
    - Audience analysis and segmentation
    - Retention strategy and churn prevention
    - Win-back campaign design
    - Acquisition strategy
    - Campaign strategy and messaging
    - Campaign recommendations as structured findings

    Reuses existing domain capabilities:
    - CampaignStrategistAgent (campaign design)
    - CustomerIntelligenceService (segment analysis)
    - SimulationEngine (what-if scenarios)
    """

    NAME = "MarketingAgent"
    DESCRIPTION = (
        "Marketing specialist for the AI Growth Team. Analyzes customer "
        "segments, designs retention/win-back campaigns, creates messaging "
        "strategies, and proposes campaign recommendations with evidence."
    )
    PERMISSIONS = frozenset({
        READ_MERCHANT,
        READ_CUSTOMERS,
        READ_ORDERS,
        READ_CAMPAIGNS,
        READ_OPPORTUNITIES,
        SIMULATE,
        PROPOSE_ACTION,
    })
    TOOLS = ("segment_analysis", "campaign_design", "messaging_strategy", "simulation", "finding_creation")

    def _run(self, ctx: AgentContext, result: AgentResult) -> None:
        db: Session = ctx.db
        merchant_id: uuid.UUID = ctx.merchant_id
        task_id = ctx.params.get("task_id")
        objective = ctx.params.get("objective", "Improve marketing effectiveness")

        # Get debate context
        debate_id = ctx.params.get("debate_id")
        if not debate_id:
            result.errors.append("No debate_id provided for MarketingAgent")
            result.status = "failed"
            return

        debate_id = uuid.UUID(str(debate_id))

        # Initialize repositories
        finding_repo = AgentFindingRepository(db)
        message_repo = AgentMessageRepository(db)

        # Phase 1: Analyze customer segments from Customer Intelligence
        intel_service = CustomerIntelligenceService(db)
        insights = intel_service.list_insights(merchant_id, limit=500)
        result.insights_generated = len(insights)

        # Segment breakdown
        segment_counts: dict[str, int] = {}
        for insight in insights:
            segment_counts[insight.primary_segment.value] = segment_counts.get(insight.primary_segment.value, 0) + 1

        # Identify high-value segments
        high_value_segments = [
            s for s, count in segment_counts.items()
            if s in {"vip", "high_value", "repeat_customer"} and count >= 3
        ]
        at_risk_segments = [
            s for s, count in segment_counts.items()
            if s in {"at_risk", "churned", "dormant", "churn_risk"} and count >= 3
        ]

        # Phase 2: Analyze relevant opportunities
        opportunities = list(db.scalars(
            select(GrowthOpportunity).where(
                GrowthOpportunity.merchant_id == merchant_id,
                GrowthOpportunity.status.in_(["pending_approval", "approved"]),
            ).limit(20)
        ).all())

        marketing_opps = [o for o in opportunities if o.type.value in {
            "campaign", "win_back", "retention", "discount", "segment_expansion"
        }]

        # Phase 3: Generate findings based on analysis
        findings_created = 0

        # Finding 1: Segment opportunity
        if high_value_segments:
            finding = self._create_finding(
                finding_repo, debate_id, task_id, merchant_id,
                finding_type=FindingType.supporting,
                title=f"High-value segments identified: {', '.join(high_value_segments)}",
                description=(
                    f"Found {sum(segment_counts.get(s, 0) for s in high_value_segments)} "
                    f"customers in high-value segments ({', '.join(high_value_segments)}). "
                    f"These segments are prime targets for upsell and retention campaigns."
                ),
                evidence=[
                    {"type": "segment_counts", "data": {s: segment_counts.get(s, 0) for s in high_value_segments}},
                    {"type": "source", "value": "CustomerIntelligenceService"},
                ],
                confidence=0.85,
                supports_recommendation=True,
            )
            findings_created += 1

        # Finding 2: At-risk / churn segment
        if at_risk_segments:
            finding = self._create_finding(
                finding_repo, debate_id, task_id, merchant_id,
                finding_type=FindingType.supporting,
                title=f"At-risk segments require intervention: {', '.join(at_risk_segments)}",
                description=(
                    f"Found {sum(segment_counts.get(s, 0) for s in at_risk_segments)} "
                    f"customers in at-risk segments. Win-back campaigns recommended."
                ),
                evidence=[
                    {"type": "segment_counts", "data": {s: segment_counts.get(s, 0) for s in at_risk_segments}},
                    {"type": "source", "value": "CustomerIntelligenceService"},
                ],
                confidence=0.80,
                supports_recommendation=True,
            )
            findings_created += 1

        # Finding 3: Campaign opportunity simulation
        if marketing_opps:
            top_opp = max(marketing_opps, key=lambda o: float(o.expected_revenue))
            sim_engine = SimulationEngine(db)
            simulation = sim_engine.simulate_campaign(
                target_customers=int(top_opp.target_customer_count or 100),
                expected_conversion=0.08,
                avg_order_value=float(top_opp.expected_revenue) / max(int(top_opp.target_customer_count or 1), 1) if top_opp.target_customer_count else 500.0,
                cost_per_target=0.50,
            )
            sim_engine.persist(
                simulation,
                merchant_id=merchant_id,
                opportunity_id=top_opp.id,
                created_by_agent=self.NAME,
                inputs={"segment": "targeted", "conversion_assumption": 0.08},
            )

            finding = self._create_finding(
                finding_repo, debate_id, task_id, merchant_id,
                finding_type=FindingType.supporting,
                title=f"Campaign simulation for: {top_opp.title}",
                description=(
                    f"Simulated campaign for {int(top_opp.target_customer_count or 0)} target customers. "
                    f"Estimated revenue: ₹{simulation.estimated_revenue:,.2f}, "
                    f"ROI: {simulation.expected_roi:.1f}%, "
                    f"Confidence range: ₹{simulation.confidence_low:,.2f} - ₹{simulation.confidence_high:,.2f}"
                ),
                evidence=[
                    {"type": "simulation", "data": simulation.to_dict()},
                    {"type": "source_opportunity", "value": str(top_opp.id)},
                ],
                confidence=0.75,
                supports_recommendation=True,
            )
            findings_created += 1

        # Finding 4: Check for conflicting evidence (e.g., low engagement segments)
        low_engagement = [s for s, count in segment_counts.items() if s in {"new_customer"} and count > 50]
        if low_engagement:
            finding = self._create_finding(
                finding_repo, debate_id, task_id, merchant_id,
                finding_type=FindingType.opposing,
                title="Large new-customer segment with unknown retention",
                description=(
                    f"{segment_counts.get('new_customer', 0)} new customers with no purchase history. "
                    f"Campaign effectiveness on this segment is uncertain."
                ),
                evidence=[
                    {"type": "segment_counts", "data": {"new_customer": segment_counts.get("new_customer", 0)}},
                    {"type": "assumption", "value": "New customers may not respond to retention campaigns"},
                ],
                confidence=0.60,
                uncertainty_notes="No historical engagement data for new customers",
                supports_recommendation=False,
            )
            findings_created += 1

        # Finding 5: Assumption documentation
        finding = self._create_finding(
            finding_repo, debate_id, task_id, merchant_id,
            finding_type=FindingType.uncertainty,
            title="Campaign conversion assumptions documented",
            description=(
                "Campaign simulations assume 8% conversion rate based on industry benchmarks. "
                "Actual conversion may vary significantly by segment, offer, and channel."
            ),
            evidence=[
                {"type": "assumption", "key": "campaign_conversion_rate", "value": 0.08, "source": "industry_benchmark"},
                {"type": "assumption", "key": "cost_per_target", "value": 0.50, "source": "internal_estimate"},
            ],
            confidence=0.50,
            uncertainty_notes="Conversion rate is an estimate; actual performance requires A/B testing",
            supports_recommendation=None,
        )
        findings_created += 1

        # Phase 4: Send summary message to debate
        message_repo.create(
            debate_id=debate_id,
            merchant_id=merchant_id,
            from_agent=AgentSpecialty.marketing,
            to_agent=None,  # broadcast
            message_type="findings_summary",
            content=(
                f"Marketing analysis complete. Identified {len(high_value_segments)} high-value "
                f"and {len(at_risk_segments)} at-risk segments. Created {findings_created} findings. "
                f"Campaign simulation shows estimated ₹{simulation.estimated_revenue:,.0f} revenue "
                f"for top opportunity." if marketing_opps else "No campaign-type opportunities found."
            ),
            references=[str(f.id) for f in finding_repo.list_by_debate(debate_id)[-findings_created:]],
        )

        result.output["segment_analysis"] = segment_counts
        result.output["high_value_segments"] = high_value_segments
        result.output["at_risk_segments"] = at_risk_segments
        result.output["marketing_opportunities"] = len(marketing_opps)
        result.output["findings_created"] = findings_created

    def _create_finding(
        self,
        finding_repo: AgentFindingRepository,
        debate_id: uuid.UUID,
        task_id: str | None,
        merchant_id: uuid.UUID,
        finding_type: FindingType,
        title: str,
        description: str,
        evidence: list[dict[str, Any]],
        confidence: float,
        uncertainty_notes: str | None = None,
        supports_recommendation: bool | None = None,
    ) -> AgentFinding:
        """Create and persist an AgentFinding."""
        task_uuid = uuid.UUID(str(task_id)) if task_id else None
        finding = finding_repo.create(
            debate_id=debate_id,
            merchant_id=merchant_id,
            task_id=task_uuid,
            agent_specialty=AgentSpecialty.marketing,
            finding_type=finding_type,
            title=title,
            description=description,
            evidence=evidence,
            confidence=confidence,
            uncertainty_notes=uncertainty_notes,
            supports_recommendation=supports_recommendation,
        )
        return finding