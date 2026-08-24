"""
GrowthOpportunityService.

Separates three concerns:
  1. ANALYSIS  — query DB to identify opportunities (deterministic rules)
  2. PERSISTENCE — upsert opportunities to growth_opportunities table
  3. RETRIEVAL — read stored opportunities for the API

The growth engine remains rule-based in Phase 2. LLM augmentation comes later.
Opportunities are never duplicated: each has a stable opportunity_key and
get-or-create logic prevents re-insertion on every API call.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.models.opportunity import GrowthOpportunity
from backend.app.models.enums import OpportunityStatus, OpportunityType
from backend.app.repositories.opportunity import GrowthOpportunityRepository
from backend.app.repositories.order import OrderRepository
from backend.app.repositories.payment import PaymentRepository
from backend.app.repositories.customer import CustomerRepository
from backend.app.repositories.product import ProductRepository
from backend.app.core.logging import get_logger

log = get_logger(__name__)


class GrowthOpportunityService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._opp_repo = GrowthOpportunityRepository(db)
        self._order_repo = OrderRepository(db)
        self._payment_repo = PaymentRepository(db)
        self._customer_repo = CustomerRepository(db)
        self._product_repo = ProductRepository(db)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def analyse_and_persist(self, merchant_id: uuid.UUID) -> list[GrowthOpportunity]:
        """
        Run all opportunity analyses for the merchant, persist new ones,
        and return the full current list.

        Idempotent: calling this multiple times does not create duplicates.
        """
        self._analyse_cross_sell_case(merchant_id)
        self._analyse_high_value_returning(merchant_id)
        self._analyse_failed_payment_recovery(merchant_id)
        return self.list_opportunities(merchant_id)

    def list_opportunities(
        self,
        merchant_id: uuid.UUID,
        *,
        status: OpportunityStatus | None = None,
    ) -> list[GrowthOpportunity]:
        return self._opp_repo.list_by_merchant(merchant_id, status=status)

    # ------------------------------------------------------------------ #
    # Analysis methods (private)
    # ------------------------------------------------------------------ #

    def _get_or_create_opportunity(
        self,
        *,
        merchant_id: uuid.UUID,
        key: str,
        type: OpportunityType,
        title: str,
        description: str,
        confidence: Decimal,
        expected_revenue: Decimal,
        target_customer_count: int,
        reasoning: list[str],
    ) -> GrowthOpportunity:
        """Upsert: return existing opportunity if key already exists."""
        existing = self._opp_repo.get_by_key(merchant_id, key)
        if existing:
            return existing
        return self._opp_repo.create(
            merchant_id=merchant_id,
            opportunity_key=key,
            type=type,
            title=title,
            description=description,
            confidence=confidence,
            expected_revenue=expected_revenue,
            target_customer_count=target_customer_count,
            reasoning=reasoning,
        )

    def _analyse_cross_sell_case(self, merchant_id: uuid.UUID) -> None:
        """
        Opportunity: cross-sell protective case to headphone buyers who
        have never purchased a case.
        """
        products = self._product_repo.list_by_merchant(merchant_id, active_only=False)
        headphone = next(
            (p for p in products if "headphone" in p.name.lower() and p.category == "audio"),
            None,
        )
        case = next(
            (p for p in products if "case" in p.name.lower()),
            None,
        )
        if not headphone or not case:
            log.debug("Cross-sell analysis skipped: headphone or case product not found.")
            return

        headphone_buyers = self._order_repo.get_customer_ids_for_product(
            merchant_id, headphone.id
        )
        case_buyers = self._order_repo.get_customer_ids_for_product(
            merchant_id, case.id
        )
        eligible = headphone_buyers - case_buyers

        if not eligible:
            return

        estimated_conversion = Decimal("0.12")
        expected_revenue = (
            Decimal(len(eligible)) * estimated_conversion * case.price
        ).quantize(Decimal("0.01"))

        self._get_or_create_opportunity(
            merchant_id=merchant_id,
            key="opp_headphone_case",
            type=OpportunityType.cross_sell,
            title="Cross-sell protective case to headphone buyers",
            description=(
                f"{len(eligible)} headphone buyers have not purchased a protective case."
            ),
            confidence=Decimal("0.87"),
            expected_revenue=expected_revenue,
            target_customer_count=len(eligible),
            reasoning=[
                "Headphone buyers are a high-intent segment.",
                "Accessory attachment is currently below the modelled target.",
                "The proposed action has a bounded price and requires merchant approval.",
            ],
        )
        log.info("Cross-sell opportunity analysed: %d eligible customers.", len(eligible))

    def _analyse_high_value_returning(self, merchant_id: uuid.UUID) -> None:
        """
        Opportunity: upsell premium audio product to high-value returning customers.
        """
        high_value = self._customer_repo.list_high_value_returning(
            merchant_id, min_orders=2, limit=100
        )
        if not high_value:
            return

        products = self._product_repo.list_by_merchant(merchant_id, active_only=False)
        premium = next(
            (p for p in products if p.price >= Decimal("2000") and p.category == "audio"),
            None,
        )
        if not premium:
            return

        estimated_conversion = Decimal("0.08")
        expected_revenue = (
            Decimal(len(high_value)) * estimated_conversion * premium.price
        ).quantize(Decimal("0.01"))

        self._get_or_create_opportunity(
            merchant_id=merchant_id,
            key="opp_high_value_upsell",
            type=OpportunityType.upsell,
            title="Upsell premium audio to high-value returning customers",
            description=(
                f"{len(high_value)} returning customers with 2+ orders "
                "are candidates for premium audio upsell."
            ),
            confidence=Decimal("0.72"),
            expected_revenue=expected_revenue,
            target_customer_count=len(high_value),
            reasoning=[
                "Returning customers with multiple purchases show strong brand affinity.",
                "Premium audio products have the highest margin in the catalogue.",
                "Targeted personal recommendation increases conversion vs. generic email.",
            ],
        )
        log.info("High-value upsell opportunity analysed: %d candidates.", len(high_value))

    def _analyse_failed_payment_recovery(self, merchant_id: uuid.UUID) -> None:
        """
        Opportunity: recover revenue from retryable failed payments.
        """
        failed = self._payment_repo.list_failed_by_merchant(merchant_id)
        if not failed:
            return

        total_at_risk = sum(p.amount for p in failed)
        estimated_recovery_rate = Decimal("0.35")
        expected_revenue = (
            total_at_risk * estimated_recovery_rate
        ).quantize(Decimal("0.01"))

        self._get_or_create_opportunity(
            merchant_id=merchant_id,
            key="opp_failed_payment_recovery",
            type=OpportunityType.failed_payment_recovery,
            title="Recover revenue from failed payments",
            description=(
                f"{len(failed)} failed payments totalling "
                f"₹{total_at_risk:.2f} are eligible for retry."
            ),
            confidence=Decimal("0.65"),
            expected_revenue=expected_revenue,
            target_customer_count=len(failed),
            reasoning=[
                f"{len(failed)} payments failed, likely due to transient issues.",
                "Automated retry with a payment link has a ~35% recovery rate.",
                "No discount required — customer intent already exists.",
            ],
        )
        log.info("Failed payment recovery opportunity: %d payments.", len(failed))
