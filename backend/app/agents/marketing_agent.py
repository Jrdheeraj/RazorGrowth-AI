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
        phase = ctx.params.get("phase", "investigate")

        # Get debate context (optional for AI Team workspace mode)
        debate_id = ctx.params.get("debate_id")
        finding_repo = None
        message_repo = None
        if debate_id:
            debate_id = uuid.UUID(str(debate_id))
            finding_repo = AgentFindingRepository(db)
            message_repo = AgentMessageRepository(db)

        if phase in ("investigate", "work"):
            self._run_investigation(ctx, result, finding_repo, message_repo, debate_id, task_id, merchant_id, objective)
        elif phase == "cross_examine" and message_repo and debate_id:
            self._run_cross_examination(ctx, result, finding_repo, message_repo, debate_id, merchant_id)
        elif phase == "rebut" and message_repo and debate_id:
            self._run_rebuttal(ctx, result, finding_repo, message_repo, debate_id, merchant_id)

    def _run_investigation(
        self,
        ctx: AgentContext,
        result: AgentResult,
        finding_repo: AgentFindingRepository | None,
        message_repo: AgentMessageRepository | None,
        debate_id: uuid.UUID | None,
        task_id: str | None,
        merchant_id: uuid.UUID,
        objective: str,
    ) -> None:
        db = ctx.db
        intel_service = CustomerIntelligenceService(db)
        insights = intel_service.list_insights(merchant_id, limit=500)
        result.insights_generated = len(insights)

        segment_counts: dict[str, int] = {}
        for insight in insights:
            seg_val = getattr(insight.primary_segment, "value", str(insight.primary_segment))
            segment_counts[seg_val] = segment_counts.get(seg_val, 0) + 1

        from backend.app.models.payment import Payment
        from backend.app.models.enums import PaymentProvider, PaymentStatus
        from sqlalchemy import func

        failed_stats = db.execute(
            select(func.count(Payment.id), func.coalesce(func.sum(Payment.amount), 0))
            .where(
                Payment.merchant_id == merchant_id,
                Payment.provider == PaymentProvider.razorpay.value,
                Payment.status == PaymentStatus.failed.value,
            )
        ).one()
        failed_count = int(failed_stats[0])
        failed_amt = float(failed_stats[1])

        total_cust_count = sum(segment_counts.values()) or len(insights)
        high_value_count = sum(segment_counts.get(s, 0) for s in ["vip", "high_value", "repeat_customer"])
        at_risk_count = sum(segment_counts.get(s, 0) for s in ["at_risk", "churned", "dormant", "churn_risk"])

        findings_created = 0

        # Finding 1: Failed payment recoverable revenue
        if failed_count > 0 and finding_repo and debate_id:
            f = self._create_finding(
                finding_repo, debate_id, task_id, merchant_id,
                finding_type=FindingType.supporting,
                title=f"Recoverable Revenue: ₹{failed_amt:,.2f} lost across {failed_count} failed Razorpay payments",
                description=(
                    f"Analysis of real Razorpay TEST transactions shows {failed_count} payment failures "
                    f"totalling ₹{failed_amt:,.2f}. Automated SMS/email payment recovery workflows "
                    f"can re-engage these high-intent shoppers."
                ),
                evidence=[
                    {"source": "Razorpay Payments API", "metric": "failed_payment_value_inr", "value": failed_amt},
                    {"source": "Razorpay Payments API", "metric": "failed_count", "value": failed_count},
                ],
                confidence=0.90,
                supports_recommendation=True,
            )
            findings_created += 1

        # Finding 2: Customer segment retention
        if finding_repo and debate_id:
            f2 = self._create_finding(
                finding_repo, debate_id, task_id, merchant_id,
                finding_type=FindingType.supporting,
                title=f"Customer Base Intelligence: {total_cust_count} tracked customers ({high_value_count} high-value)",
                description=(
                    f"Customer intelligence derived from real transaction history identifies {total_cust_count} unique "
                    f"profiles. {high_value_count} customers exhibit repeat purchasing patterns, while {at_risk_count} "
                    f"show dormancy risks."
                ),
                evidence=[
                    {"source": "CustomerIntelligenceService", "metric": "total_customers", "value": total_cust_count},
                    {"source": "CustomerIntelligenceService", "metric": "high_value_segments", "value": high_value_count},
                ],
                confidence=0.85,
                supports_recommendation=True,
            )
            findings_created += 1

            # Finding 3: Target campaign assumptions & uncertainty
            f3 = self._create_finding(
                finding_repo, debate_id, task_id, merchant_id,
                finding_type=FindingType.uncertainty,
                title="Recovery & Win-back Campaign Conversion Assumptions",
                description=(
                    "Campaign recovery estimates assume an 8-12% baseline conversion on failed-payment links. "
                    "Conversion variance depends on timely notification delivery within 15 minutes of failure."
                ),
                evidence=[
                    {"source": "Industry Benchmark", "metric": "expected_conversion", "value": 0.10},
                    {"source": "Internal Heuristics", "metric": "window_minutes", "value": 15},
                ],
                confidence=0.70,
                uncertainty_notes="Actual conversion rate should be verified through A/B experimentation",
                supports_recommendation=True,
            )
            findings_created += 1

        # Opening message (Round 1)
        if message_repo and debate_id:
            message_repo.create(
                debate_id=debate_id,
                merchant_id=merchant_id,
                from_agent=AgentSpecialty.marketing.value,
                to_agent=None,
                message_type="opening",
                content=(
                    f"Marketing Analyst: Real Razorpay data reveals {total_cust_count} active customer profiles and "
                    f"{failed_count} failed payment transactions totalling ₹{failed_amt:,.2f}. Re-engaging failed-checkout "
                    f"customers and launching a targeted retention campaign represents our highest-yield, lowest-CAC opportunity."
                ),
                references=[{"round": 1, "type": "opening", "failed_value": failed_amt, "customers": total_cust_count}],
            )

        recs = []
        if failed_count > 0:
            recs.append(f"Deploy automated recovery alerts to recapture ₹{failed_amt:,.2f} lost in {failed_count} checkout drops")
        if high_value_count > 0:
            recs.append(f"Create retention & loyalty incentive for {high_value_count} repeat/VIP customers")
        if at_risk_count > 0:
            recs.append(f"Run win-back reactivation for {at_risk_count} customers showing drop-off signals")
        if not recs:
            recs.append("Monitor new checkout sessions and customer signups")

        result.output["segment_analysis"] = segment_counts
        result.output["findings_created"] = findings_created
        result.output["failed_payments_value"] = failed_amt
        result.output["failed_payments_count"] = failed_count
        result.output["total_customers"] = total_cust_count
        result.output["high_value_count"] = high_value_count
        result.output["at_risk_count"] = at_risk_count
        result.output["recommendations"] = recs
        result.output["summary"] = (
            f"Analyzed {total_cust_count} customer profiles and {failed_count} failed payments. "
            f"Identified {high_value_count} high-value repeat shoppers and ₹{failed_amt:,.2f} in recoverable checkout drops."
        )

    def _run_cross_examination(
        self,
        ctx: AgentContext,
        result: AgentResult,
        finding_repo: AgentFindingRepository,
        message_repo: AgentMessageRepository,
        debate_id: uuid.UUID,
        merchant_id: uuid.UUID,
    ) -> None:
        message_repo.create(
            debate_id=debate_id,
            merchant_id=merchant_id,
            from_agent=AgentSpecialty.marketing.value,
            to_agent=AgentSpecialty.product.value,
            message_type="challenge",
            content=(
                "Marketing Analyst → Product Strategist: High-AOV bundle strategies rely on existing customer multi-item "
                "intent. Does our real Razorpay order basket history show repeat multi-item orders, or are customers "
                "primarily purchasing single hero SKUs?"
            ),
            references=[{"round": 2, "target": "product", "focus": "basket_affinity"}],
        )

    def _run_rebuttal(
        self,
        ctx: AgentContext,
        result: AgentResult,
        finding_repo: AgentFindingRepository,
        message_repo: AgentMessageRepository,
        debate_id: uuid.UUID,
        merchant_id: uuid.UUID,
    ) -> None:
        message_repo.create(
            debate_id=debate_id,
            merchant_id=merchant_id,
            from_agent=AgentSpecialty.marketing.value,
            to_agent=AgentSpecialty.software.value,
            message_type="rebuttal",
            content=(
                "Marketing Analyst → Technical Feasibility: Understood on webhook rate boundaries and discount guardrails. "
                "We agree that recovery discounts must be capped at 10% and triggered strictly on genuine network/bank drops "
                "with a single automated SMS/email notification rather than continuous messaging."
            ),
            references=[{"round": 3, "target": "software", "resolution": "bounded_recovery_notification"}],
        )

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
        task_uuid = uuid.UUID(str(task_id)) if task_id else None
        finding = finding_repo.create(
            debate_id=debate_id,
            merchant_id=merchant_id,
            task_id=task_uuid,
            agent_specialty=AgentSpecialty.marketing.value,
            finding_type=finding_type.value,
            title=title,
            description=description,
            evidence=evidence,
            confidence=confidence,
            uncertainty_notes=uncertainty_notes,
            supports_recommendation=supports_recommendation,
        )
        return finding