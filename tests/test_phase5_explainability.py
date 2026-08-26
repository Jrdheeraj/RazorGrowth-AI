"""Phase 5 — explainability, do-nothing baseline, growth brief."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.customer import Customer
from backend.app.models.customer_insight import CustomerInsight
from backend.app.models.enums import (
    ChurnRiskLevel,
    Currency,
    InsightType,
    MerchantStatus,
    OrderStatus,
    PaymentProvider,
    PaymentStatus,
)
from backend.app.models.merchant import Merchant
from backend.app.models.opportunity import GrowthOpportunity
from backend.app.models.order import Order
from backend.app.models.payment import Payment
from backend.app.services.explainability import ExplainabilityService
from backend.app.services.brief import GrowthBriefService


def make_merchant(db_session: Session) -> Merchant:
    m = Merchant(
        name=f"P5 Expl {uuid.uuid4().hex[:6]}",
        slug=f"p5-expl-{uuid.uuid4().hex[:10]}",
        email="p5expl@x.com",
        status=MerchantStatus.active,
        currency=Currency.INR,
    )
    db_session.add(m)
    db_session.commit()
    return m


def seed_revenue_trend(db_session: Session, merchant: Merchant) -> None:
    """₹40k prior window → ₹20k current window (−50% measured trend)."""
    now = datetime.now(timezone.utc)

    def order_with_payment(total: str, days_ago: int) -> None:
        c = Customer(
            merchant_id=merchant.id,
            name=f"C{uuid.uuid4().hex[:6]}",
            email=f"{uuid.uuid4().hex[:8]}@c.com",
            total_orders=1,
            total_spend=Decimal(total),
        )
        db_session.add(c)
        db_session.flush()
        o = Order(
            merchant_id=merchant.id,
            customer_id=c.id,
            order_number=f"O-{uuid.uuid4().hex[:8]}",
            status=OrderStatus.paid,
            subtotal=Decimal(total), discount=Decimal("0"), tax=Decimal("0"),
            total=Decimal(total), currency=Currency.INR,
            created_at=now - timedelta(days=days_ago),
        )
        db_session.add(o)
        db_session.flush()
        db_session.add(
            Payment(
                merchant_id=merchant.id, order_id=o.id,
                provider=PaymentProvider.synthetic,
                amount=Decimal(total), currency=Currency.INR,
                status=PaymentStatus.captured,
                created_at=now - timedelta(days=days_ago),
            )
        )

    for _ in range(4):
        order_with_payment("10000", 45)   # previous window
    for _ in range(2):
        order_with_payment("10000", 5)    # current window
    db_session.commit()


def make_opportunity(merchant: Merchant, **overrides) -> GrowthOpportunity:
    defaults = dict(
        merchant_id=merchant.id,
        opportunity_key=f"test-{uuid.uuid4().hex[:16]}",
        type="campaign",
        title="Win-back campaign for declining revenue",
        confidence=Decimal("0.70"),
        expected_revenue=Decimal("60000"),
        target_customer_count=40,
        reasoning=[
            {"source_signal": "revenue_drop", "basis": "real revenue trend", "evidence": {}},
            {"assumed_response_rate": 0.10},
        ],
    )
    defaults.update(overrides)
    return GrowthOpportunity(**defaults)


@pytest.fixture()
def merchant(db_session: Session) -> Merchant:
    m = make_merchant(db_session)
    seed_revenue_trend(db_session, m)
    return m


class TestDoNothingBaseline:
    def test_projection_uses_measured_trend(self, db_session: Session, merchant: Merchant):
        opp = make_opportunity(merchant)
        db_session.add(opp); db_session.commit()
        svc = ExplainabilityService(db_session)
        baseline = svc.do_nothing_baseline(merchant.id, opp)
        assert baseline["scenario"] == "do_nothing"
        assert baseline["is_projection"] is True
        assert baseline["measured_change_percentage"] == pytest.approx(-50.0)
        # ₹20k current × (1 − 50%) ⇒ ₹10k projected next window
        assert baseline["projected_next_window_revenue"] == pytest.approx(10000.0)
        assert "continuation of measured" in baseline["basis"]

    def test_no_trend_data_means_no_projection(self, db_session: Session):
        empty_merchant = make_merchant(db_session)
        opp = make_opportunity(empty_merchant)
        db_session.add(opp); db_session.commit()
        baseline = ExplainabilityService(db_session).do_nothing_baseline(
            empty_merchant.id, opp
        )
        assert baseline["is_projection"] is False
        assert baseline["projected_next_window_revenue"] is None


class TestExplainability:
    def test_full_explanation_structure(self, db_session: Session, merchant: Merchant):
        opp = make_opportunity(merchant)
        db_session.add(opp); db_session.commit()
        explanation = ExplainabilityService(db_session).explain_opportunity(
            merchant.id, opp
        )
        for key in (
            "why", "evidence", "expected_impact", "risk", "assumptions",
            "do_nothing", "take_action", "score_breakdown",
        ):
            assert key in explanation
        assert "was raised because" in explanation["why"]
        assert explanation["take_action"]["is_estimate"] is True
        assert any(a == "0.1" for a in map(str, explanation["assumptions"]))

    def test_take_action_prefers_persisted_simulation(self, db_session: Session, merchant: Merchant):
        from backend.app.services.simulation import SimulationEngine

        opp = make_opportunity(merchant)
        db_session.add(opp); db_session.commit()
        sim_engine = SimulationEngine(db_session)
        result = sim_engine.simulate_discount(
            discount_percentage=10, target_customers=100,
            expected_conversion=0.2, avg_order_value=500,
        )
        sim_engine.persist(result, merchant_id=merchant.id, opportunity_id=opp.id)

        outlook = ExplainabilityService(db_session).take_action_outlook(merchant.id, opp)
        assert outlook["estimated_revenue"] == pytest.approx(9000.0)  # simulation value
        assert outlook["confidence_range"][0] is not None


class TestGrowthBrief:
    def test_brief_from_real_data_only(self, db_session: Session, merchant: Merchant):
        brief = GrowthBriefService(db_session).build(merchant.id)
        assert brief["revenue"]["current_period"] == 20000.0
        assert brief["revenue"]["previous_period"] == 40000.0
        assert brief["revenue"]["change_percentage"] == pytest.approx(-50.0)
        assert brief["revenue"]["has_prior_baseline"] is True

    def test_brief_flags_top_risk_from_failed_payments(self, db_session: Session, merchant: Merchant):
        now = datetime.now(timezone.utc)
        c = Customer(merchant_id=merchant.id, name="X", email="x@x.com")
        db_session.add(c); db_session.flush()
        o = Order(
            merchant_id=merchant.id, customer_id=c.id,
            order_number="OF", status=OrderStatus.pending,
            subtotal=Decimal("9000"), discount=Decimal("0"), tax=Decimal("0"),
            total=Decimal("9000"), currency=Currency.INR,
        )
        db_session.add(o); db_session.flush()
        db_session.add(Payment(
            merchant_id=merchant.id, order_id=o.id,
            provider=PaymentProvider.synthetic, amount=Decimal("9000"),
            currency=Currency.INR, status=PaymentStatus.failed,
        ))
        db_session.commit()

        brief = GrowthBriefService(db_session).build(merchant.id)
        assert brief["top_risk"]["type"] == "payment_failures"
        assert "9000" in brief["top_risk"]["detail"]

    def test_empty_merchant_brief_has_no_fabricated_numbers(self, db_session: Session):
        empty = make_merchant(db_session)
        brief = GrowthBriefService(db_session).build(empty.id)
        assert brief["revenue"]["current_period"] == 0.0
        assert brief["revenue"]["change_percentage"] is None  # no baseline invented
        assert brief["top_opportunity"] is None
        assert brief["recommended_action"]["title"].startswith("No open opportunities")

    def test_brief_recommends_human_approval(self, db_session: Session, merchant: Merchant):
        opp = make_opportunity(merchant)
        db_session.add(opp); db_session.commit()
        brief = GrowthBriefService(db_session).build(merchant.id)
        assert brief["recommended_action"]["requires_human_approval"] is True

    def test_churn_risk_surfaces_as_risk(self, db_session: Session, merchant: Merchant):
        c = Customer(merchant_id=merchant.id, name="Y", email="y@y.com")
        db_session.add(c); db_session.commit()
        insight = CustomerInsight(
            merchant_id=merchant.id, customer_id=c.id,
            insight_key=f"k-{uuid.uuid4().hex[:12]}",
            primary_segment=InsightType.churn_risk.value,
            churn_risk_score=Decimal("82.00"),
            churn_risk_level=ChurnRiskLevel.critical.value,
        )
        db_session.add(insight); db_session.commit()
        brief = GrowthBriefService(db_session).build(merchant.id)
        assert brief["top_risk"]["type"] == "customer_churn"
