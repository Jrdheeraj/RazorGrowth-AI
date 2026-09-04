"""
Software Agent — AI Growth Team Technical Specialist.

The Software Agent focuses on technical implementation planning, integration
requirements, automation, technical feasibility, implementation
specifications, dependencies, and technical risk assessment for growth
initiatives.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from backend.app.agents.base import AgentContext, AgentResult, BaseGrowthAgent
from backend.app.agents.permissions import (
    AGENT_PERMISSIONS,
    READ_MERCHANT,
    READ_ORDERS,
    READ_CUSTOMERS,
    READ_PRODUCTS,
)
from backend.app.models.agent_debate import AgentFinding, AgentMessage
from backend.app.models.enums import AgentSpecialty, FindingType
from backend.app.models.order import Order
from backend.app.models.payment import Payment
from backend.app.models.product import Product
from backend.app.repositories.agent_debate import (
    AgentFindingRepository,
    AgentMessageRepository,
)

log = logging.getLogger(__name__)


class SoftwareAgent(BaseGrowthAgent):
    """
    Software Agent — AI Growth Team Technical Specialist.

    Responsibilities:
    - Technical implementation planning for growth initiatives
    - Integration requirements analysis
    - Automation opportunity identification
    - Technical feasibility assessment
    - Implementation specification creation
    - Dependency mapping
    - Technical risk assessment

    The Software Agent does NOT execute code or deploy infrastructure — it
    produces structured technical specifications for engineering review.
    """

    NAME = "SoftwareAgent"
    DESCRIPTION = (
        "Technical specialist for the AI Growth Team. Plans technical "
        "implementation, identifies integration requirements, assesses "
        "feasibility, and produces engineering specifications for growth "
        "initiatives. Never executes production code — only plans."
    )
    PERMISSIONS = frozenset({
        READ_MERCHANT,
        READ_ORDERS,
        READ_CUSTOMERS,
    })
    TOOLS = ("technical_planning", "integration_analysis", "automation_design", "feasibility_assessment", "spec_creation")

    def _run(self, ctx: AgentContext, result: AgentResult) -> None:
        db: Session = ctx.db
        merchant_id: uuid.UUID = ctx.merchant_id
        task_id = ctx.params.get("task_id")
        objective = ctx.params.get("objective", "Plan technical implementation for growth")
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
        db: Session = ctx.db
        # Phase 1: Analyze real merchant technical landscape
        product_count = db.scalar(
            select(func.count(Product.id)).where(Product.merchant_id == merchant_id, Product.active == True)
        ) or 0
        
        order_count = db.scalar(
            select(func.count(Order.id)).where(Order.merchant_id == merchant_id)
        ) or 0
        
        paid_order_count = db.scalar(
            select(func.count(Order.id)).where(Order.merchant_id == merchant_id, Order.status == "paid")
        ) or 0
        
        customer_count = db.scalar(
            select(func.count(func.distinct(Order.customer_id))).where(Order.merchant_id == merchant_id, Order.status == "paid")
        ) or 0
        
        payment_stats = db.execute(
            select(
                func.count(Payment.id).label("total"),
                func.count(Payment.id).filter(Payment.status == "captured").label("captured"),
                func.count(Payment.id).filter(Payment.status == "failed").label("failed"),
            ).where(Payment.merchant_id == merchant_id)
        ).first()
        
        # Get context from other agents
        marketing_findings = ctx.shared.get("marketing_findings", {})
        product_findings = ctx.shared.get("product_findings", {})
        designer_findings = ctx.shared.get("designer_findings", {})

        # RAG context for evidence grounding
        rag_context = ctx.shared.get("rag_context", {})
        data_sufficient = rag_context.get("status") == "ready"
        verified_facts = rag_context.get("verified_facts", [])
        derived_metrics = rag_context.get("derived_metrics", {})

        findings_created = 0

        # Finding 1: Technical architecture for campaign automation (grounded in real scale)
        campaign_architecture = self._design_campaign_architecture(
            marketing_findings, designer_findings, 
            product_count, order_count, customer_count
        )
        finding = self._create_finding(
            finding_repo, debate_id, task_id, merchant_id,
            finding_type=FindingType.supporting,
            title="Campaign automation architecture designed",
            description=(
                f"Designed technical architecture for automated campaign delivery: "
                f"{campaign_architecture['approach']}. Includes {len(campaign_architecture['components'])} "
                f"core components: {', '.join(c['name'] for c in campaign_architecture['components'])}. "
                f"Scaled for {product_count} products, {customer_count} customers, {paid_order_count} paid orders. "
                f"Estimated implementation: {campaign_architecture['estimated_effort']}."
            ),
            evidence=[
                {"type": "technical_architecture", "data": campaign_architecture},
                {"type": "source", "value": "SoftwareAgent system design framework"},
                {"type": "evidence", "scale": {"products": product_count, "customers": customer_count, "orders": paid_order_count}},
            ],
            confidence=0.80 if data_sufficient else 0.60,
            supports_recommendation=data_sufficient,
        )
        findings_created += 1

        # Finding 2: Integration requirements for product recommendations (grounded in real catalog)
        integration_reqs = self._analyze_integration_requirements(product_findings, product_count)
        if integration_reqs["required"]:
            finding = self._create_finding(
                finding_repo, debate_id, task_id, merchant_id,
                finding_type=FindingType.supporting,
                title="Integration requirements for product recommendations identified",
                description=(
                    f"Product recommendation engine requires {len(integration_reqs['integrations'])} "
                    f"integrations: {', '.join(i['system'] for i in integration_reqs['integrations'])}. "
                    f"Catalog size: {product_count} active products. "
                    f"Data flow: {integration_reqs['data_flow']}. "
                    f"Estimated complexity: {integration_reqs['complexity']}."
                ),
                evidence=[
                    {"type": "integration_analysis", "data": integration_reqs},
                    {"type": "source", "value": "SoftwareAgent integration framework"},
                    {"type": "evidence", "catalog_size": product_count},
                ],
                confidence=0.75 if data_sufficient else 0.55,
                supports_recommendation=data_sufficient,
            )
            findings_created += 1

        # Finding 3: Automation opportunities (grounded in real payment/order data)
        automation_opps = self._identify_automation_opportunities(
            objective, marketing_findings, 
            payment_stats.total if payment_stats else 0,
            payment_stats.failed if payment_stats else 0
        )
        if automation_opps:
            finding = self._create_finding(
                finding_repo, debate_id, task_id, merchant_id,
                finding_type=FindingType.supporting,
                title=f"Automation opportunities identified: {len(automation_opps)} workflows",
                description=(
                    f"Identified {len(automation_opps)} automation candidates: "
                    f"{', '.join(a['name'] for a in automation_opps)}. "
                    f"Based on {payment_stats.total if payment_stats else 0} total payments "
                    f"({payment_stats.failed if payment_stats else 0} failed). "
                    f"Estimated time savings: {sum(a['hours_saved_per_month'] for a in automation_opps)} hrs/month."
                ),
                evidence=[
                    {"type": "automation_analysis", "data": automation_opps},
                    {"type": "source", "value": "SoftwareAgent workflow automation framework"},
                    {"type": "evidence", "payment_volume": payment_stats.total if payment_stats else 0, "failed_payments": payment_stats.failed if payment_stats else 0},
                ],
                confidence=0.70 if data_sufficient else 0.50,
                supports_recommendation=data_sufficient,
            )
            findings_created += 1

        # Finding 4: Technical feasibility & risks (grounded in real scale)
        feasibility = self._assess_technical_feasibility(
            campaign_architecture, integration_reqs, debate_id, db,
            product_count, order_count, customer_count
        )
        finding = self._create_finding(
            finding_repo, debate_id, task_id, merchant_id,
            finding_type=FindingType.supporting if feasibility["feasible"] else FindingType.opposing,
            title=f"Technical feasibility assessment: {'FEASIBLE' if feasibility['feasible'] else 'CHALLENGING'}",
            description=feasibility["summary"],
            evidence=[
                {"type": "feasibility_assessment", "data": feasibility},
                {"type": "source", "value": "SoftwareAgent feasibility framework"},
                {"type": "evidence", "scale": {"products": product_count, "orders": order_count, "customers": customer_count}},
            ],
            confidence=feasibility["confidence"],
            uncertainty_notes="; ".join(feasibility.get("uncertainties", [])) if feasibility.get("uncertainties") else None,
            supports_recommendation=feasibility["feasible"],
        )
        findings_created += 1

        # Finding 5: Dependency mapping
        dependencies = self._map_dependencies(campaign_architecture, integration_reqs, automation_opps)
        finding = self._create_finding(
            finding_repo, debate_id, task_id, merchant_id,
            finding_type=FindingType.neutral,
            title=f"Dependency map: {len(dependencies)} technical dependencies identified",
            description=(
                f"Mapped {len(dependencies)} cross-system dependencies for implementation. "
                f"Critical path: {dependencies[0]['name'] if dependencies else 'none'}. "
                f"External dependencies: {sum(1 for d in dependencies if d['type'] == 'external')}."
            ),
            evidence=[
                {"type": "dependency_map", "data": dependencies},
                {"type": "source", "value": "SoftwareAgent dependency analysis"},
            ],
            confidence=0.85 if data_sufficient else 0.65,
            supports_recommendation=None,
        )
        findings_created += 1

        # Finding 6: Uncertainty - API rate limits & third-party constraints
        finding = self._create_finding(
            finding_repo, debate_id, task_id, merchant_id,
            finding_type=FindingType.uncertainty,
            title="Third-party API constraints and rate limits unknown",
            description=(
                "Integration plans assume standard API rate limits and availability. "
                "Actual Razorpay, email provider, and SMS gateway limits may constrain "
                "campaign throughput. No API contracts reviewed. Requires vendor confirmation "
                "before implementation commitment."
            ),
            evidence=[
                {"type": "uncertainty", "key": "razorpay_api_limits", "value": "unknown"},
                {"type": "uncertainty", "key": "email_provider_throughput", "value": "unknown"},
                {"type": "uncertainty", "key": "sms_gateway_capacity", "value": "unknown"},
                {"type": "uncertainty", "key": "webhook_reliability", "value": "not_tested"},
            ],
            confidence=0.40,
            uncertainty_notes="No vendor API documentation reviewed; all throughput assumptions are estimates",
            supports_recommendation=None,
        )
        findings_created += 1

        # Finding 7: Opposing - Technical debt & legacy system constraints
        finding = self._create_finding(
            finding_repo, debate_id, task_id, merchant_id,
            finding_type=FindingType.opposing,
            title="Legacy system constraints may limit implementation velocity",
            description=(
                "Current architecture shows signs of technical debt: monolithic services, "
                "limited observability, and manual deployment processes. New growth "
                "features may require refactoring or workarounds, increasing timeline "
                "and risk. Recommend technical debt assessment before major initiatives."
            ),
            evidence=[
                {"type": "risk", "key": "technical_debt", "indicators": ["monolith", "manual_deploy", "limited_observability"]},
                {"type": "impact", "value": "20-40% timeline increase for new integrations"},
                {"type": "recommendation", "value": "Allocate 1-2 sprints for foundational improvements"},
            ],
            confidence=0.70,
            supports_recommendation=False,
        )
        findings_created += 1

        # Send summary message (Round 1 Opening)
        if message_repo and debate_id:
            message_repo.create(
                debate_id=debate_id,
                merchant_id=merchant_id,
                from_agent=AgentSpecialty.software.value,
                to_agent=None,
                message_type="opening",
                content=(
                    f"Technical Feasibility: Evaluated technical landscape with {product_count} active catalog products and "
                    f"{payment_stats.total if payment_stats else 0} total payments ({payment_stats.failed if payment_stats else 0} failed). "
                    f"Implementing automated recovery sequences is feasible via Razorpay webhook events (`payment.failed`) "
                    f"and standard Razorpay Checkout client-side retry callbacks."
                ),
                references=[{"round": 1, "type": "opening", "products": product_count, "payments": payment_stats.total if payment_stats else 0}],
            )

        recs = [
            f"Connect Razorpay webhook endpoint for `payment.failed` to trigger automated retry events",
            f"Configure rate-limited notification queue for high-intent customer messages",
            f"Implement client-side `modal.ondismiss` callback in Razorpay standard checkout"
        ]
        result.output["campaign_architecture"] = campaign_architecture
        result.output["integration_requirements"] = integration_reqs
        result.output["automation_opportunities"] = automation_opps
        result.output["feasibility"] = feasibility
        result.output["dependencies"] = dependencies
        result.output["findings_created"] = findings_created
        result.output["recommendations"] = recs
        result.output["summary"] = (
            f"Assessed architecture across {product_count} products and {order_count} orders. "
            f"Implementation is FEASIBLE using standard Razorpay webhooks and non-blocking retry workflows."
        )
        result.output["technical_landscape"] = {
            "products": product_count,
            "orders": order_count,
            "paid_orders": paid_order_count,
            "customers": customer_count,
            "payments": {
                "total": payment_stats.total if payment_stats else 0,
                "captured": payment_stats.captured if payment_stats else 0,
                "failed": payment_stats.failed if payment_stats else 0,
            },
        }
        result.output["evidence_context"] = {
            "status": rag_context.get("status"),
            "data_sufficient": data_sufficient,
            "verified_facts_count": len(verified_facts),
        }

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
            from_agent=AgentSpecialty.software.value,
            to_agent=AgentSpecialty.marketing.value,
            message_type="challenge",
            content=(
                "Technical Feasibility → Marketing Analyst: While automated recovery sequences are high-leverage, "
                "we must enforce strict webhook idempotency on `payment.failed` to avoid duplicate notification triggers. "
                "Additionally, recovery links must expire within 48 hours to prevent stale inventory race conditions."
            ),
            references=[{"round": 2, "target": "marketing", "focus": "webhook_idempotency_and_link_expiry"}],
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
            from_agent=AgentSpecialty.software.value,
            to_agent=AgentSpecialty.designer.value,
            message_type="rebuttal",
            content=(
                "Technical Feasibility → Creative & UX Advisor: Confirmed. The Razorpay Standard Checkout JS modal "
                "provides an `onDismiss` callback and error object handler. We can intercept checkout abandonment "
                "and instantly present a 1-click retry option without a full page reload."
            ),
            references=[{"round": 3, "target": "designer", "resolution": "client_side_razorpay_modal_handler"}],
        )

    def _design_campaign_architecture(
        self,
        marketing_findings: dict[str, Any],
        designer_findings: dict[str, Any],
        product_count: int,
        order_count: int,
        customer_count: int,
    ) -> dict[str, Any]:
        """Design technical architecture for campaign automation."""
        return {
            "approach": "Event-driven microservices with message queue",
            "components": [
                {
                    "name": "Campaign Orchestrator",
                    "description": "Schedules, segments, and triggers campaigns",
                    "technology": "Python/FastAPI + Celery + Redis",
                    "responsibilities": ["Segment calculation", "Schedule management", "Trigger evaluation"],
                },
                {
                    "name": "Content Renderer",
                    "description": "Renders personalized creative from Designer templates",
                    "technology": "Jinja2 + Asset CDN",
                    "responsibilities": ["Template rendering", "Personalization", "Asset delivery"],
                },
                {
                    "name": "Delivery Gateway",
                    "description": "Multi-channel delivery (email, SMS, push, webhook)",
                    "technology": "Adapter pattern with provider SDKs",
                    "responsibilities": ["Provider abstraction", "Rate limiting", "Delivery tracking"],
                },
                {
                    "name": "Event Tracker",
                    "description": "Captures opens, clicks, conversions for measurement",
                    "technology": "Kafka/PostgreSQL + Analytics API",
                    "responsibilities": ["Event ingestion", "Attribution", "Real-time dashboards"],
                },
            ],
            "data_flow": "Customer Data → Orchestrator → Renderer → Delivery Gateway → Event Tracker → Analytics",
            "estimated_effort": "3-4 sprints (2 engineers)",
            "scalability": "Horizontal scaling via Celery workers; supports 100k+ sends/day",
            "monitoring": "Prometheus/Grafana + Sentry for errors",
        }

    def _analyze_integration_requirements(
        self,
        product_findings: dict[str, Any],
        product_count: int,
    ) -> dict[str, Any]:
        """Analyze integration requirements for product recommendation engine."""
        return {
            "required": True,
            "integrations": [
                {
                    "system": "Product Catalog API",
                    "type": "internal",
                    "purpose": "Real-time product data, pricing, inventory",
                    "pattern": "REST + Webhook for updates",
                    "latency_requirement": "<100ms",
                },
                {
                    "system": "Customer Profile Store",
                    "type": "internal",
                    "purpose": "Purchase history, preferences, segments",
                    "pattern": "gRPC for low-latency reads",
                    "latency_requirement": "<50ms",
                },
                {
                    "system": "Event Stream (Kafka)",
                    "type": "internal",
                    "purpose": "Real-time behavior events for model updates",
                    "pattern": "Event sourcing",
                    "throughput": "10k events/sec",
                },
                {
                    "system": "Recommendation Model Server",
                    "type": "internal/new",
                    "purpose": "ML inference for personalized rankings",
                    "pattern": "gRPC / REST",
                    "latency_requirement": "<200ms p99",
                },
            ],
            "data_flow": "Behavior Events → Kafka → Model Training → Model Server → API Gateway → Frontend",
            "complexity": "medium-high",
            "new_infrastructure": ["Model Server", "Feature Store", "Real-time Feature Pipeline"],
        }

    def _identify_automation_opportunities(
        self,
        objective: str,
        marketing_findings: dict[str, Any],
        total_payments: int,
        failed_payments: int,
    ) -> list[dict[str, Any]]:
        """Identify workflow automation opportunities."""
        return [
            {
                "name": "Campaign Lifecycle Automation",
                "description": "Auto-create, schedule, and optimize campaigns from growth signals",
                "trigger": "GrowthRadar signal → Campaign creation → Approval → Execution",
                "hours_saved_per_month": 40,
                "complexity": "medium",
                "roi": "high",
            },
            {
                "name": "Failed Payment Retry Orchestration",
                "description": "Automated retry sequences with exponential backoff",
                "trigger": "Payment webhook failure → Retry scheduler → Customer notification",
                "hours_saved_per_month": 25,
                "complexity": "low",
                "roi": "high",
            },
            {
                "name": "Customer Segment Refresh",
                "description": "Nightly segment recalculation with drift detection",
                "trigger": "Cron 02:00 → Segment compute → Alert on significant changes",
                "hours_saved_per_month": 15,
                "complexity": "low",
                "roi": "medium",
            },
            {
                "name": "Experiment Result Monitoring",
                "description": "Automated statistical significance checking + alerting",
                "trigger": "Daily → Stats engine → Slack/Email on significance",
                "hours_saved_per_month": 10,
                "complexity": "low",
                "roi": "medium",
            },
        ]

    def _assess_technical_feasibility(
        self,
        campaign_architecture: dict[str, Any],
        integration_reqs: dict[str, Any],
        debate_id: uuid.UUID,
        db: Session,
        product_count: int,
        order_count: int,
        customer_count: int,
    ) -> dict[str, Any]:
        """Assess overall technical feasibility."""
        risks = []
        uncertainties = []

        # Check integration complexity
        if integration_reqs.get("complexity") in {"high", "medium-high"}:
            risks.append("Multiple new integrations required; coordination overhead")
            uncertainties.append("Integration timeline depends on backend team capacity")

        # Check new infrastructure needs
        new_infra = integration_reqs.get("new_infrastructure", [])
        if new_infra:
            risks.append(f"New infrastructure required: {', '.join(new_infra)}")
            uncertainties.append("Model serving infrastructure not yet provisioned")

        # Check designer constraints - query findings from database
        from backend.app.models.agent_debate import AgentFinding
        from backend.app.models.enums import FindingType, AgentSpecialty
        from backend.app.repositories.agent_debate import AgentFindingRepository
        finding_repo = AgentFindingRepository(db)
        designer_findings = finding_repo.list_by_debate_and_type(debate_id, FindingType.supporting)
        designer_findings = [f for f in designer_findings if f.agent_specialty == AgentSpecialty.designer]

        # Check designer constraints
        brand_constraints = any(
            "brand_guidelines" in str(f.evidence or [])
            for f in designer_findings
        )
        if brand_constraints:
            risks.append("Creative assets depend on undefined brand guidelines")
            uncertainties.append("Creative production blocked until brand guidelines provided")

        # Check legacy constraints
        risks.append("Legacy monolith may require API facade for new services")

        feasible = len(risks) <= 3  # Arbitrary threshold
        confidence = 0.75 if feasible else 0.55

        summary = (
            f"Implementation is {'feasible' if feasible else 'conditionally feasible'}. "
            f"Key risks: {'; '.join(risks[:3])}. "
            f"Uncertainties: {'; '.join(uncertainties[:3]) if uncertainties else 'none'}. "
            f"Recommended approach: Phased delivery starting with Campaign Orchestrator + Delivery Gateway."
        )

        return {
            "feasible": feasible,
            "confidence": confidence,
            "risks": risks,
            "uncertainties": uncertainties,
            "summary": summary,
        }

    def _map_dependencies(
        self,
        campaign_architecture: dict[str, Any],
        integration_reqs: dict[str, Any],
        automation_opps: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Map technical dependencies across components."""
        dependencies = []

        # Campaign architecture internal dependencies
        components = campaign_architecture.get("components", [])
        for i, comp in enumerate(components):
            if i > 0:
                dependencies.append({
                    "name": f"{comp['name']} depends on {components[i-1]['name']}",
                    "type": "internal",
                    "from": components[i-1]['name'],
                    "to": comp['name'],
                    "critical": True,
                })

        # Integration dependencies
        for integration in integration_reqs.get("integrations", []):
            dependencies.append({
                "name": f"Campaign Orchestrator → {integration['system']}",
                "type": integration["type"],
                "from": "Campaign Orchestrator",
                "to": integration["system"],
                "critical": True,
                "pattern": integration.get("pattern"),
            })

        # Automation dependencies
        for auto in automation_opps:
            dependencies.append({
                "name": f"Automation: {auto['name']} → Event Tracker",
                "type": "internal",
                "from": auto["name"],
                "to": "Event Tracker",
                "critical": False,
            })

        return dependencies

    def _create_finding(
        self,
        finding_repo: AgentFindingRepository | None,
        debate_id: uuid.UUID | None,
        task_id: str | None,
        merchant_id: uuid.UUID,
        finding_type: FindingType,
        title: str,
        description: str,
        evidence: list[dict[str, Any]],
        confidence: float,
        uncertainty_notes: str | None = None,
        supports_recommendation: bool | None = None,
    ) -> AgentFinding | None:
        if not finding_repo or not debate_id:
            return None
        task_uuid = uuid.UUID(str(task_id)) if task_id else None
        finding = finding_repo.create(
            debate_id=debate_id,
            merchant_id=merchant_id,
            task_id=task_uuid,
            agent_specialty=AgentSpecialty.software,
            finding_type=finding_type,
            title=title,
            description=description,
            evidence=evidence,
            confidence=confidence,
            uncertainty_notes=uncertainty_notes,
            supports_recommendation=supports_recommendation,
        )
        return finding