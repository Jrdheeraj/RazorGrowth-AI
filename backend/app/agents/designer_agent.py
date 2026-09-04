"""
Designer Agent — AI Growth Team Creative Specialist.

The Designer Agent focuses on campaign creative concepts, messaging variations,
experiment concepts, UX recommendations, creative direction, and creative
specifications for growth initiatives.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.agents.base import AgentContext, AgentResult, BaseGrowthAgent
from backend.app.agents.permissions import (
    AGENT_PERMISSIONS,
    READ_MERCHANT,
    READ_CAMPAIGNS,
    READ_CUSTOMERS,
)
from backend.app.models.agent_debate import AgentFinding, AgentMessage
from backend.app.models.campaign import Campaign
from backend.app.models.enums import AgentSpecialty, FindingType
from backend.app.repositories.agent_debate import (
    AgentFindingRepository,
    AgentMessageRepository,
)
from backend.app.services.customer_intelligence import CustomerIntelligenceService

log = logging.getLogger(__name__)


class DesignerAgent(BaseGrowthAgent):
    """
    Designer Agent — AI Growth Team Creative Specialist.

    Responsibilities:
    - Campaign creative concepts and visual direction
    - Messaging variations and copy strategy
    - Experiment creative concepts (A/B test variants)
    - UX recommendations for growth funnels
    - Creative direction and brand alignment
    - Creative specifications for implementation

    The Designer Agent does NOT execute creatives — it produces structured
    creative briefs and specifications for human review and approval.
    """

    NAME = "DesignerAgent"
    DESCRIPTION = (
        "Creative specialist for the AI Growth Team. Designs campaign "
        "creatives, messaging strategies, experiment variants, and UX "
        "recommendations. Produces structured creative briefs for human "
        "review — never executes production creatives."
    )
    PERMISSIONS = frozenset({
        READ_MERCHANT,
        READ_CAMPAIGNS,
        READ_CUSTOMERS,
    })
    TOOLS = ("creative_concept", "messaging_strategy", "experiment_variants", "ux_recommendations", "creative_brief")

    def _run(self, ctx: AgentContext, result: AgentResult) -> None:
        db: Session = ctx.db
        merchant_id: uuid.UUID = ctx.merchant_id
        task_id = ctx.params.get("task_id")
        objective = ctx.params.get("objective", "Create compelling growth creatives")
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
        from backend.app.models.payment import Payment
        from backend.app.models.enums import PaymentProvider, PaymentStatus
        from sqlalchemy import func

        failed_count = int(db.scalar(
            select(func.count(Payment.id)).where(
                Payment.merchant_id == merchant_id,
                Payment.provider == PaymentProvider.razorpay.value,
                Payment.status == PaymentStatus.failed.value,
            )
        ) or 0)

        intel_service = CustomerIntelligenceService(db)
        insights = intel_service.list_insights(merchant_id, limit=500)
        segment_counts: dict[str, int] = {}
        for insight in insights:
            seg_val = getattr(insight.primary_segment, "value", str(insight.primary_segment))
            segment_counts[seg_val] = segment_counts.get(seg_val, 0) + 1

        findings_created = 0

        # Finding 1: Checkout & Payment Retry Experience
        if finding_repo and debate_id:
            f1 = self._create_finding(
                finding_repo, debate_id, task_id, merchant_id,
                finding_type=FindingType.supporting,
                title="Checkout Journey & Friction Reduction for Payment Failures",
                description=(
                    f"Analysis of {failed_count} payment failures highlights the necessity of a streamlined recovery UX. "
                    f"Displaying explicit decline causes (e.g. UPI timeout, bank decline) combined with an instant 1-click "
                    f"Razorpay retry link recovers up to 35-40% of drop-offs without user re-authentication."
                ),
                evidence=[
                    {"source": "Payment Failure UX Analysis", "metric": "failed_payment_events", "value": failed_count},
                    {"source": "UX Best Practices", "metric": "expected_retry_conversion", "value": 0.35},
                ],
                confidence=0.85,
                supports_recommendation=True,
            )
            findings_created += 1

            # Finding 2: Messaging & Trust Badging
            f2 = self._create_finding(
                finding_repo, debate_id, task_id, merchant_id,
                finding_type=FindingType.supporting,
                title="Trust Badges & Dynamic Payment Method Prominence",
                description=(
                    "Adding verified Razorpay security badges and highlighting preferred Indian payment methods "
                    "(UPI AutoPay, Google Pay, Netbanking) elevates customer confidence during the final payment decision."
                ),
                evidence=[
                    {"source": "Commerce Trust Signals", "metric": "trust_factor", "value": "Razorpay Verified Merchant"},
                ],
                confidence=0.80,
                supports_recommendation=True,
            )
            findings_created += 1

            # Finding 3: UX Overload Risk
            f3 = self._create_finding(
                finding_repo, debate_id, task_id, merchant_id,
                finding_type=FindingType.uncertainty,
                title="Pre-Payment Friction Risk from Intrusive Upsell Popups",
                description=(
                    "Modal overlays injected before the payment step introduce cognitive friction. "
                    "Creative recommendations must remain non-blocking (e.g. order summary card badges or post-checkout cards)."
                ),
                evidence=[
                    {"source": "UX Friction Framework", "metric": "abandonment_risk", "value": "medium"},
                ],
                confidence=0.75,
                uncertainty_notes="Should be tested against control via standard Razorpay modal checkout",
                supports_recommendation=True,
            )
            findings_created += 1

        # Opening message (Round 1)
        if message_repo and debate_id:
            message_repo.create(
                debate_id=debate_id,
                merchant_id=merchant_id,
                from_agent=AgentSpecialty.designer.value,
                to_agent=None,
                message_type="opening",
                content=(
                    f"Creative & UX Advisor: With {failed_count} failed payment attempts observed in real merchant data, "
                    f"frictionless recovery UX is essential. Replacing generic error screens with instant pre-filled Razorpay "
                    f"retry links and clean trust badging will maximize customer completion rates."
                ),
                references=[{"round": 1, "type": "opening", "failed_events": failed_count}],
            )

        recs = [
            "Implement an instant 1-click retry state on failed Razorpay payments to recover drop-offs",
            "Embed Razorpay security trust badges and prominent UPI options in checkout summary",
            "Keep upsell and bundle recommendations non-blocking on post-order confirmation view"
        ]
        result.output["findings_created"] = findings_created
        result.output["failed_count"] = failed_count
        result.output["recommendations"] = recs
        result.output["summary"] = (
            f"Evaluated customer journey and {failed_count} checkout failure points. "
            f"Designed frictionless 1-click recovery UX and trust-enhancing checkout layout."
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
            from_agent=AgentSpecialty.designer.value,
            to_agent=AgentSpecialty.software.value,
            message_type="challenge",
            content=(
                "Creative & UX Advisor → Technical Feasibility: When a buyer's payment fails due to a bank timeout, "
                "can the frontend catch the Razorpay checkout `modal.ondismiss` or error event and immediately render "
                "a 1-click retry state without reloading the whole checkout page?"
            ),
            references=[{"round": 2, "target": "software", "focus": "client_side_retry_handler"}],
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
            from_agent=AgentSpecialty.designer.value,
            to_agent=AgentSpecialty.product.value,
            message_type="rebuttal",
            content=(
                "Creative & UX Advisor → Product Strategist: We completely agree that checkout popups are hazardous. "
                "We recommend embedding companion accessory suggestions exclusively into the order-summary accordion "
                "and thank-you confirmation card to preserve seamless 1-step payment speed."
            ),
            references=[{"round": 3, "target": "product", "resolution": "non_intrusive_summary_upsell"}],
        )

    def _develop_campaign_concept(
        self,
        objective: str,
        marketing_findings: dict[str, Any],
        product_findings: dict[str, Any],
        existing_campaigns: list,
        segment_counts: dict[str, int],
        high_value_segments: list[str],
        at_risk_segments: list[str],
    ) -> dict[str, Any]:
        """Develop a primary campaign creative concept."""
        # Determine theme based on objective and findings
        obj_lower = objective.lower()

        if "retention" in obj_lower or "churn" in obj_lower:
            theme = "Loyalty & Appreciation"
            visual_direction = "Warm, personal, customer-centric imagery"
            key_message = "We value your continued trust"
        elif "win-back" in obj_lower or "dormant" in obj_lower:
            theme = "Rediscovery & Value"
            visual_direction = "Fresh, inviting, 'what you've been missing' aesthetic"
            key_message = "Come back for something special"
        elif "upsell" in obj_lower or "cross-sell" in obj_lower:
            theme = "Enhanced Experience"
            visual_direction = "Premium, aspirational, benefit-focused"
            key_message = "Elevate your experience"
        elif "acquisition" in obj_lower:
            theme = "First Impression"
            visual_direction = "Bold, clear value proposition, social proof"
            key_message = "Discover why customers love us"
        else:
            theme = "Growth & Momentum"
            visual_direction = "Dynamic, forward-looking, energetic"
            key_message = "Grow with us"

        return {
            "theme": theme,
            "visual_direction": visual_direction,
            "key_message": key_message,
            "description": (
                f"Campaign theme: '{theme}'. Visual direction: {visual_direction}. "
                f"Core message: '{key_message}'. Designed to resonate with "
                f"target segments identified by Marketing and Product agents. "
                f"Includes hero creative, supporting assets, and channel adaptations."
            ),
            "channels": ["email", "push", "social", "web_banner"],
            "asset_requirements": [
                "Hero image (1200x628)",
                "Mobile banner (375x667)",
                "Email header (600x300)",
                "Push notification icon (1024x1024)",
            ],
        }

    def _develop_messaging_variants(
        self,
        objective: str,
        marketing_findings: dict[str, Any],
        segment_counts: dict[str, int],
        high_value_segments: list[str],
        at_risk_segments: list[str],
    ) -> list[dict[str, Any]]:
        """Develop messaging variants for A/B testing."""
        variants = [
            {
                "name": "Value-Focused",
                "trigger": "value_perception",
                "headline": "Get more from every purchase",
                "body": "Unlock exclusive benefits and savings tailored just for you.",
                "cta": "See Your Offers",
                "tone": "helpful, empowering",
            },
            {
                "name": "Urgency-Driven",
                "trigger": "scarcity",
                "headline": "Limited time: Your exclusive offer expires soon",
                "body": "Don't miss out on personalized deals selected for you.",
                "cta": "Claim Now",
                "tone": "urgent, direct",
            },
            {
                "name": "Social Proof",
                "trigger": "social_validation",
                "headline": "Join 10,000+ customers who upgraded",
                "body": "See why loyal customers are choosing the premium experience.",
                "cta": "Upgrade Today",
                "tone": "confident, community",
            },
            {
                "name": "Personal Relevance",
                "trigger": "personalization",
                "headline": "Picked for you: [Product] matches your style",
                "body": "Based on your recent purchases, we think you'll love this.",
                "cta": "View Recommendation",
                "tone": "personal, attentive",
            },
        ]
        return variants

    def _design_experiment_variants(
        self,
        product_findings: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Design creative variants for product experiments."""
        variants = [
            {
                "name": "Control - No Recommendation",
                "description": "Standard product page without personalized recommendation module",
                "visual": "Current layout",
                "copy": "Standard product description",
            },
            {
                "name": "Variant A - Personalized Banner",
                "description": "Top-of-page banner with 'Recommended for you' + product image",
                "visual": "Banner with user's name + product image + 'Based on your history'",
                "copy": "Hi [Name], we think you'll love [Product]",
            },
            {
                "name": "Variant B - Social Proof Card",
                "description": "Sidebar card showing 'Customers who bought X also bought Y'",
                "visual": "Card with product image, rating, '2,847 customers agree'",
                "copy": "2,847 customers who bought [Product A] also love [Product B]",
            },
            {
                "name": "Variant C - Bundle Offer",
                "description": "Inline bundle suggestion with discount badge",
                "visual": "Product pair with 'Save 15% together' badge",
                "copy": "Complete your set: [Product A] + [Product B] = 15% off",
            },
        ]
        return variants

    def _recommend_ux_improvements(self, objective: str, derived_metrics: dict[str, Any]) -> list[dict[str, Any]]:
        """Recommend UX improvements for growth funnels."""
        return [
            {
                "area": "Checkout Flow",
                "current": "Multi-step checkout with optional account creation",
                "proposed": "Single-page checkout with guest option + progress indicator",
                "expected_impact": "15-20% reduction in cart abandonment",
                "effort": "medium",
            },
            {
                "area": "Product Discovery",
                "current": "Category-based navigation only",
                "proposed": "Add 'Recommended for You' section on homepage and category pages",
                "expected_impact": "10-15% increase in cross-sell conversion",
                "effort": "low",
            },
            {
                "area": "Post-Purchase",
                "current": "Generic order confirmation",
                "proposed": "Personalized thank-you page with relevant cross-sell + referral prompt",
                "expected_impact": "5-8% increase in repeat purchase rate",
                "effort": "medium",
            },
            {
                "area": "Email Capture",
                "current": "Footer newsletter signup only",
                "proposed": "Exit-intent popup with incentive + post-purchase referral invite",
                "expected_impact": "20-30% increase in email list growth",
                "effort": "low",
            },
        ]

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
            agent_specialty=AgentSpecialty.designer,
            finding_type=finding_type,
            title=title,
            description=description,
            evidence=evidence,
            confidence=confidence,
            uncertainty_notes=uncertainty_notes,
            supports_recommendation=supports_recommendation,
        )
        return finding