"""
Product Agent — AI Growth Team Product Specialist.

The Product Agent focuses on product growth opportunities, upsell, cross-sell,
product affinity, customer/product behavior analysis, experimentation, and
product strategy recommendations.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from backend.app.agents.base import AgentContext, AgentResult, BaseGrowthAgent
from backend.app.agents.permissions import (
    AGENT_PERMISSIONS,
    READ_MERCHANT,
    READ_PRODUCTS,
    READ_ORDERS,
    READ_CUSTOMERS,
    READ_OPPORTUNITIES,
    SIMULATE,
    PROPOSE_ACTION,
)
from backend.app.models.agent_debate import AgentFinding, AgentMessage
from backend.app.models.enums import AgentSpecialty, FindingType
from backend.app.models.opportunity import GrowthOpportunity
from backend.app.models.order import Order, OrderItem
from backend.app.models.product import Product
from backend.app.repositories.agent_debate import (
    AgentFindingRepository,
    AgentMessageRepository,
)
from backend.app.agents.revenue_optimization import RevenueOptimizationAgent
from backend.app.services.experiment_service import ExperimentService
from backend.app.services.simulation import SimulationEngine

log = logging.getLogger(__name__)


class ProductAgent(BaseGrowthAgent):
    """
    Product Agent — AI Growth Team Product Specialist.

    Responsibilities:
    - Product growth opportunity identification (upsell, cross-sell)
    - Product affinity analysis
    - Customer/product behavior analysis
    - Experimentation design
    - Product strategy recommendations

    Reuses existing domain capabilities:
    - RevenueOptimizationAgent (opportunity ranking)
    - ExperimentAgent (A/B test design)
    - SimulationEngine (what-if scenarios)
    """

    NAME = "ProductAgent"
    DESCRIPTION = (
        "Product specialist for the AI Growth Team. Identifies upsell and "
        "cross-sell opportunities, analyzes product affinity, designs "
        "experiments, and proposes product growth strategies with evidence."
    )
    PERMISSIONS = frozenset({
        READ_MERCHANT,
        READ_PRODUCTS,
        READ_ORDERS,
        READ_CUSTOMERS,
        READ_OPPORTUNITIES,
        SIMULATE,
        PROPOSE_ACTION,
    })
    TOOLS = ("product_affinity_analysis", "upsell_cross_sell_detection", "experiment_design", "simulation", "finding_creation")

    def _run(self, ctx: AgentContext, result: AgentResult) -> None:
        db: Session = ctx.db
        merchant_id: uuid.UUID = ctx.merchant_id
        task_id = ctx.params.get("task_id")
        objective = ctx.params.get("objective", "Improve product revenue")

        debate_id = ctx.params.get("debate_id")
        if not debate_id:
            result.errors.append("No debate_id provided for ProductAgent")
            result.status = "failed"
            return

        debate_id = uuid.UUID(str(debate_id))

        finding_repo = AgentFindingRepository(db)
        message_repo = AgentMessageRepository(db)

        # Phase 1: Product affinity analysis from order data
        affinity_results = self._analyze_product_affinity(db, merchant_id)
        result.output["product_affinity"] = affinity_results

        # Phase 2: Identify upsell/cross-sell opportunities
        upsell_opps = self._identify_upsell_opportunities(db, merchant_id, affinity_results)
        cross_sell_opps = self._identify_cross_sell_opportunities(db, merchant_id, affinity_results)

        # Phase 3: Analyze existing opportunities
        opportunities = list(db.scalars(
            select(GrowthOpportunity).where(
                GrowthOpportunity.merchant_id == merchant_id,
                GrowthOpportunity.status.in_(["pending_approval", "approved"]),
            ).limit(20)
        ).all())

        product_opps = [o for o in opportunities if o.type.value in {
            "upsell", "cross_sell", "product_affinity", "checkout_optimization"
        }]

        findings_created = 0

        # Finding 1: Product affinity insights
        if affinity_results.get("strong_affinities"):
            top_affinity = affinity_results["strong_affinities"][0]
            finding = self._create_finding(
                finding_repo, debate_id, task_id, merchant_id,
                finding_type=FindingType.supporting,
                title=f"Strong product affinity: {top_affinity['product_a']} + {top_affinity['product_b']}",
                description=(
                    f"Customers who bought '{top_affinity['product_a']}' are "
                    f"{top_affinity['lift']:.1f}x more likely to buy "
                    f"'{top_affinity['product_b']}' (confidence: {top_affinity['confidence']:.0%}). "
                    f"Cross-sell opportunity identified."
                ),
                evidence=[
                    {"type": "affinity_analysis", "data": top_affinity},
                    {"type": "source", "value": "OrderItem co-occurrence analysis"},
                ],
                confidence=min(top_affinity["confidence"], 0.9),
                supports_recommendation=True,
            )
            findings_created += 1

        # Finding 2: Upsell opportunity
        if upsell_opps:
            top_upsell = upsell_opps[0]
            sim_engine = SimulationEngine(db)
            simulation = sim_engine.simulate_discount(
                discount_percentage=10.0,
                target_customers=top_upsell["target_count"],
                expected_conversion=0.12,
                avg_order_value=top_upsell["avg_order_value"],
            )
            sim_engine.persist(
                simulation,
                merchant_id=merchant_id,
                opportunity_id=None,
                created_by_agent=self.NAME,
                inputs={"upsell_product": top_upsell["product_name"]},
            )

            finding = self._create_finding(
                finding_repo, debate_id, task_id, merchant_id,
                finding_type=FindingType.supporting,
                title=f"Upsell opportunity: {top_upsell['product_name']}",
                description=(
                    f"Identified {top_upsell['target_count']} customers eligible for "
                    f"upsell to '{top_upsell['product_name']}'. "
                    f"Simulated 10% discount campaign estimates "
                    f"₹{simulation.estimated_revenue:,.2f} additional revenue "
                    f"(ROI: {simulation.expected_roi:.1f}%)."
                ),
                evidence=[
                    {"type": "upsell_analysis", "data": top_upsell},
                    {"type": "simulation", "data": simulation.to_dict()},
                ],
                confidence=0.78,
                supports_recommendation=True,
            )
            findings_created += 1

        # Finding 3: Cross-sell opportunity
        if cross_sell_opps:
            top_cross = cross_sell_opps[0]
            finding = self._create_finding(
                finding_repo, debate_id, task_id, merchant_id,
                finding_type=FindingType.supporting,
                title=f"Cross-sell opportunity: {top_cross['product_a']} → {top_cross['product_b']}",
                description=(
                    f"{top_cross['target_count']} customers bought '{top_cross['product_a']}' "
                    f"but not '{top_cross['product_b']}'. "
                    f"Estimated cross-sell revenue: ₹{top_cross['estimated_revenue']:,.2f}"
                ),
                evidence=[
                    {"type": "cross_sell_analysis", "data": top_cross},
                    {"type": "source", "value": "Product affinity + purchase history"},
                ],
                confidence=0.75,
                supports_recommendation=True,
            )
            findings_created += 1

        # Finding 4: Experiment proposal for top opportunity
        if product_opps:
            top_opp = max(product_opps, key=lambda o: float(o.expected_revenue))
            exp_service = ExperimentService(db)
            experiment = exp_service.create_experiment(
                merchant_id=merchant_id,
                name=f"Product A/B: {top_opp.title[:60]}",
                hypothesis=(
                    f"Offering targeted product recommendation for {top_opp.type.value} "
                    f"increases conversion vs. no recommendation."
                ),
                opportunity_id=top_opp.id,
                control_group={"recommendation": "none"},
                treatment_group={"recommendation": f"personalized_{top_opp.type.value}"},
                target_population_size=int(top_opp.target_customer_count or 50),
                estimated_metric={
                    "estimated_additional_revenue": float(top_opp.expected_revenue),
                    "is_estimate": True,
                },
            )
            result.experiments_proposed += 1

            finding = self._create_finding(
                finding_repo, debate_id, task_id, merchant_id,
                finding_type=FindingType.supporting,
                title=f"Experiment proposed for: {top_opp.title}",
                description=(
                    f"Designed A/B experiment (control vs. personalized {top_opp.type.value} recommendation) "
                    f"for {int(top_opp.target_customer_count or 0)} customers. "
                    f"Experiment ID: {experiment.id}. Measurement pending real data."
                ),
                evidence=[
                    {"type": "experiment_design", "experiment_id": str(experiment.id)},
                    {"type": "source_opportunity", "value": str(top_opp.id)},
                ],
                confidence=0.70,
                uncertainty_notes="Experiment results require real traffic; estimated impact is theoretical",
                supports_recommendation=True,
            )
            findings_created += 1

        # Finding 5: Opposing - inventory/stock constraints
        low_stock_products = list(db.scalars(
            select(Product).where(
                Product.merchant_id == merchant_id,
                Product.active == True,
                Product.stock_quantity < 10,
            ).limit(5)
        ).all())
        if low_stock_products:
            finding = self._create_finding(
                finding_repo, debate_id, task_id, merchant_id,
                finding_type=FindingType.opposing,
                title="Low stock may constrain product recommendations",
                description=(
                    f"{len(low_stock_products)} active products have <10 units in stock. "
                    f"Aggressive cross-sell/upsell campaigns may face fulfillment issues."
                ),
                evidence=[
                    {"type": "inventory_check", "products": [{"id": str(p.id), "name": p.name, "stock": p.stock_quantity} for p in low_stock_products]},
                ],
                confidence=0.85,
                supports_recommendation=False,
            )
            findings_created += 1

        # Finding 6: Assumption - price elasticity
        finding = self._create_finding(
            finding_repo, debate_id, task_id, merchant_id,
            finding_type=FindingType.uncertainty,
            title="Price elasticity assumptions for upsell/discount simulations",
            description=(
                "Simulations assume 10-12% conversion uplift from discounts. "
                "Actual price elasticity varies by product category and customer segment. "
                "Requires real experiment data to validate."
            ),
            evidence=[
                {"type": "assumption", "key": "discount_conversion_uplift", "value": 0.12, "source": "benchmark"},
                {"type": "assumption", "key": "price_elasticity", "value": "unknown", "source": "no_historical_data"},
            ],
            confidence=0.45,
            uncertainty_notes="No historical A/B test data for price elasticity in this merchant",
            supports_recommendation=None,
        )
        findings_created += 1

        # Send summary message
        message_repo.create(
            debate_id=debate_id,
            merchant_id=merchant_id,
            from_agent=AgentSpecialty.product,
            to_agent=None,
            message_type="findings_summary",
            content=(
                f"Product analysis complete. Found {len(affinity_results.get('strong_affinities', []))} "
                f"strong affinities, {len(upsell_opps)} upsell and {len(cross_sell_opps)} "
                f"cross-sell opportunities. Created {findings_created} findings."
            ),
        )

        result.output["product_affinity_count"] = len(affinity_results.get("strong_affinities", []))
        result.output["upsell_opportunities"] = len(upsell_opps)
        result.output["cross_sell_opportunities"] = len(cross_sell_opps)
        result.output["product_opportunities"] = len(product_opps)
        result.output["findings_created"] = findings_created

    def _analyze_product_affinity(self, db: Session, merchant_id: uuid.UUID) -> dict[str, Any]:
        """Analyze product co-occurrence in orders to find affinities."""
        # Get all order items for this merchant
        order_items = db.execute(
            select(OrderItem, Product.name)
            .join(Order, OrderItem.order_id == Order.id)
            .join(Product, OrderItem.product_id == Product.id)
            .where(Order.merchant_id == merchant_id)
            .where(Order.status == "paid")
        ).all()

        if not order_items:
            return {"strong_affinities": [], "message": "No order data available"}

        # Build product co-occurrence matrix
        product_orders: dict[uuid.UUID, set[uuid.UUID]] = {}  # order_id -> set of product_ids
        product_names: dict[uuid.UUID, str] = {}

        for item, name in order_items:
            product_names[item.product_id] = name
            if item.order_id not in product_orders:
                product_orders[item.order_id] = set()
            product_orders[item.order_id].add(item.product_id)

        # Calculate co-occurrence
        co_occurrence: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
        product_counts: dict[uuid.UUID, int] = {}

        for order_id, products in product_orders.items():
            for p1 in products:
                product_counts[p1] = product_counts.get(p1, 0) + 1
                for p2 in products:
                    if p1 != p2:
                        pair = tuple(sorted([p1, p2]))
                        co_occurrence[pair] = co_occurrence.get(pair, 0) + 1

        # Calculate lift for each pair
        affinities = []
        total_orders = len(product_orders)
        for (p1, p2), co_count in co_occurrence.items():
            p1_count = product_counts.get(p1, 1)
            p2_count = product_counts.get(p2, 1)
            expected = (p1_count * p2_count) / total_orders if total_orders > 0 else 0
            lift = (co_count / expected) if expected > 0 else 0
            confidence = min(co_count / 10.0, 1.0)  # simple confidence based on sample size

            if lift > 1.5 and co_count >= 3:  # meaningful affinity
                affinities.append({
                    "product_a": product_names.get(p1, "Unknown"),
                    "product_b": product_names.get(p2, "Unknown"),
                    "product_a_id": str(p1),
                    "product_b_id": str(p2),
                    "co_occurrence_count": co_count,
                    "lift": round(lift, 2),
                    "confidence": round(confidence, 2),
                })

        # Sort by lift
        affinities.sort(key=lambda x: x["lift"], reverse=True)

        return {"strong_affinities": affinities[:10]}

    def _identify_upsell_opportunities(
        self, db: Session, merchant_id: uuid.UUID, affinity_results: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Identify upsell opportunities (higher-value products for existing customers)."""
        # Find premium products
        premium_products = db.execute(
            select(Product).where(
                Product.merchant_id == merchant_id,
                Product.active == True,
                Product.price >= 1000,  # arbitrary threshold
            ).order_by(Product.price.desc()).limit(10)
        ).scalars().all()

        upsell_opps = []
        for product in premium_products:
            # Count customers who haven't bought this premium product but bought cheaper ones
            cheaper_products = db.execute(
                select(Product.id).where(
                    Product.merchant_id == merchant_id,
                    Product.price < product.price,
                    Product.active == True,
                )
            ).scalars().all()

            if not cheaper_products:
                continue

            cheaper_buyers = db.execute(
                select(func.count(func.distinct(Order.customer_id)))
                .join(OrderItem, Order.id == OrderItem.order_id)
                .where(Order.merchant_id == merchant_id)
                .where(Order.status == "paid")
                .where(OrderItem.product_id.in_(cheaper_products))
            ).scalar_one()

            premium_buyers = db.execute(
                select(func.count(func.distinct(Order.customer_id)))
                .join(OrderItem, Order.id == OrderItem.order_id)
                .where(Order.merchant_id == merchant_id)
                .where(Order.status == "paid")
                .where(OrderItem.product_id == product.id)
            ).scalar_one()

            eligible = cheaper_buyers - premium_buyers
            if eligible > 5:
                upsell_opps.append({
                    "product_name": product.name,
                    "product_id": str(product.id),
                    "target_count": eligible,
                    "avg_order_value": float(product.price),
                    "estimated_revenue": eligible * float(product.price) * 0.12,
                })

        upsell_opps.sort(key=lambda x: x["estimated_revenue"], reverse=True)
        return upsell_opps[:5]

    def _identify_cross_sell_opportunities(
        self, db: Session, merchant_id: uuid.UUID, affinity_results: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Identify cross-sell opportunities from affinity analysis."""
        cross_sell_opps = []
        for affinity in affinity_results.get("strong_affinities", []):
            # Find customers who have product_a but not product_b
            buyers_a = db.execute(
                select(func.count(func.distinct(Order.customer_id)))
                .join(OrderItem, Order.id == OrderItem.order_id)
                .where(Order.merchant_id == merchant_id)
                .where(Order.status == "paid")
                .where(OrderItem.product_id == affinity["product_a_id"])
            ).scalar_one()

            buyers_both = db.execute(
                select(func.count(func.distinct(Order.customer_id)))
                .join(OrderItem, Order.id == OrderItem.order_id)
                .where(Order.merchant_id == merchant_id)
                .where(Order.status == "paid")
                .where(OrderItem.product_id.in_([affinity["product_a_id"], affinity["product_b_id"]]))
                .group_by(Order.customer_id)
                .having(func.count(func.distinct(OrderItem.product_id)) == 2)
            ).scalar_one() or 0

            target_count = buyers_a - buyers_both
            if target_count > 5:
                cross_sell_opps.append({
                    "product_a": affinity["product_a"],
                    "product_b": affinity["product_b"],
                    "product_a_id": affinity["product_a_id"],
                    "product_b_id": affinity["product_b_id"],
                    "target_count": target_count,
                    "lift": affinity["lift"],
                    "estimated_revenue": target_count * affinity["lift"] * 100,  # rough estimate
                })

        cross_sell_opps.sort(key=lambda x: x["estimated_revenue"], reverse=True)
        return cross_sell_opps[:5]

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
            agent_specialty=AgentSpecialty.product,
            finding_type=finding_type,
            title=title,
            description=description,
            evidence=evidence,
            confidence=confidence,
            uncertainty_notes=uncertainty_notes,
            supports_recommendation=supports_recommendation,
        )
        return finding