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

from sqlalchemy.orm import Session

from backend.app.agents.base import AgentContext, AgentResult, BaseGrowthAgent
from backend.app.agents.permissions import (
    AGENT_PERMISSIONS,
    READ_MERCHANT,
    READ_CAMPAIGNS,
    READ_CUSTOMERS,
)
from backend.app.models.agent_debate import AgentFinding, AgentMessage
from backend.app.models.enums import AgentSpecialty, FindingType
from backend.app.repositories.agent_debate import (
    AgentFindingRepository,
    AgentMessageRepository,
)

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

        debate_id = ctx.params.get("debate_id")
        if not debate_id:
            result.errors.append("No debate_id provided for DesignerAgent")
            result.status = "failed"
            return

        debate_id = uuid.UUID(str(debate_id))

        finding_repo = AgentFindingRepository(db)
        message_repo = AgentMessageRepository(db)

        # Get context from shared findings (if available)
        marketing_findings = ctx.shared.get("marketing_findings", [])
        product_findings = ctx.shared.get("product_findings", [])

        findings_created = 0

        # Finding 1: Creative concept for primary campaign
        campaign_concept = self._develop_campaign_concept(objective, marketing_findings, product_findings)
        finding = self._create_finding(
            finding_repo, debate_id, task_id, merchant_id,
            finding_type=FindingType.supporting,
            title=f"Creative concept: {campaign_concept['theme']}",
            description=campaign_concept["description"],
            evidence=[
                {"type": "creative_concept", "data": campaign_concept},
                {"type": "source", "value": "DesignerAgent analysis of objective + segment insights"},
            ],
            confidence=0.75,
            supports_recommendation=True,
        )
        findings_created += 1

        # Finding 2: Messaging strategy variants
        messaging_variants = self._develop_messaging_variants(objective, marketing_findings)
        finding = self._create_finding(
            finding_repo, debate_id, task_id, merchant_id,
            finding_type=FindingType.supporting,
            title="Messaging strategy variants for A/B testing",
            description=(
                f"Developed {len(messaging_variants)} messaging variants targeting "
                f"different psychological triggers: {', '.join(v['trigger'] for v in messaging_variants)}. "
                f"Each variant includes headline, body copy, and CTA."
            ),
            evidence=[
                {"type": "messaging_variants", "data": messaging_variants},
                {"type": "source", "value": "DesignerAgent copy strategy framework"},
            ],
            confidence=0.70,
            supports_recommendation=True,
        )
        findings_created += 1

        # Finding 3: Experiment creative variants
        experiment_variants = self._design_experiment_variants(product_findings)
        if experiment_variants:
            finding = self._create_finding(
                finding_repo, debate_id, task_id, merchant_id,
                finding_type=FindingType.supporting,
                title="Experiment creative variants for product tests",
                description=(
                    f"Designed {len(experiment_variants)} creative variants for product "
                    f"experimentation: {', '.join(v['name'] for v in experiment_variants)}. "
                    f"Each includes visual concept, copy framework, and UX flow."
                ),
                evidence=[
                    {"type": "experiment_variants", "data": experiment_variants},
                    {"type": "source", "value": "DesignerAgent experiment design framework"},
                ],
                confidence=0.65,
                supports_recommendation=True,
            )
            findings_created += 1

        # Finding 4: UX funnel recommendations
        ux_recommendations = self._recommend_ux_improvements(objective)
        finding = self._create_finding(
            finding_repo, debate_id, task_id, merchant_id,
            finding_type=FindingType.supporting,
            title="UX funnel optimization recommendations",
            description=(
                f"Identified {len(ux_recommendations)} UX improvements for the growth funnel: "
                f"{', '.join(r['area'] for r in ux_recommendations)}. "
                f"Each includes current state, proposed change, and expected impact."
            ),
            evidence=[
                {"type": "ux_recommendations", "data": ux_recommendations},
                {"type": "source", "value": "DesignerAgent UX audit framework"},
            ],
            confidence=0.68,
            supports_recommendation=True,
        )
        findings_created += 1

        # Finding 5: Creative constraints & brand guidelines
        finding = self._create_finding(
            finding_repo, debate_id, task_id, merchant_id,
            finding_type=FindingType.uncertainty,
            title="Brand guidelines and creative constraints need clarification",
            description=(
                "Creative recommendations assume standard brand flexibility. "
                "Actual brand guidelines, color palettes, tone of voice, and "
                "regulatory constraints (if any) must be validated with merchant "
                "before production. No brand asset library was provided."
            ),
            evidence=[
                {"type": "constraint", "key": "brand_guidelines", "value": "not_provided"},
                {"type": "constraint", "key": "tone_of_voice", "value": "not_defined"},
                {"type": "constraint", "key": "regulatory_review", "value": "unknown"},
            ],
            confidence=0.40,
            uncertainty_notes="Merchant brand guidelines not available; creatives are conceptual only",
            supports_recommendation=None,
        )
        findings_created += 1

        # Finding 6: Opposing - creative fatigue risk
        finding = self._create_finding(
            finding_repo, debate_id, task_id, merchant_id,
            finding_type=FindingType.opposing,
            title="Creative fatigue risk with repeated campaign exposure",
            description=(
                "High-frequency campaigns to the same segments risk creative fatigue, "
                "reducing conversion over time. Recommend rotation schedule and "
                "fresh creative production every 2-3 weeks for sustained campaigns."
            ),
            evidence=[
                {"type": "risk", "key": "creative_fatigue", "description": "Conversion decay with repeated exposure"},
                {"type": "mitigation", "value": "Creative rotation every 14-21 days; minimum 3 variants per campaign"},
            ],
            confidence=0.75,
            supports_recommendation=False,
        )
        findings_created += 1

        # Send summary message
        message_repo.create(
            debate_id=debate_id,
            merchant_id=merchant_id,
            from_agent=AgentSpecialty.designer,
            to_agent=None,
            message_type="findings_summary",
            content=(
                f"Creative analysis complete. Developed campaign concept '{campaign_concept['theme']}', "
                f"{len(messaging_variants)} messaging variants, {len(experiment_variants)} "
                f"experiment variants, and {len(ux_recommendations)} UX recommendations. "
                f"Created {findings_created} findings. Brand guidelines validation required."
            ),
        )

        result.output["campaign_concept"] = campaign_concept
        result.output["messaging_variants"] = messaging_variants
        result.output["experiment_variants"] = experiment_variants
        result.output["ux_recommendations"] = ux_recommendations
        result.output["findings_created"] = findings_created

    def _develop_campaign_concept(
        self,
        objective: str,
        marketing_findings: list[dict[str, Any]],
        product_findings: list[dict[str, Any]],
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
        marketing_findings: list[dict[str, Any]],
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

    def _recommend_ux_improvements(self, objective: str) -> list[dict[str, Any]]:
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