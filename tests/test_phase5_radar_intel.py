"""Phase 5 — Growth Radar signals + customer intelligence + churn engine.

Data-integrity theme: every emitted number must equal the raw aggregate
computed independently from the same seeded rows; empty data must never
produce fabricated signals.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from backend.app.models.customer import Customer
from backend.app.models.enums import (
    Currency,
    MerchantStatus,
    OrderStatus,
    PaymentProvider,
    PaymentStatus,
)
from backend.app.models.merchant import Merchant
from backend.app.models.order import Order
from backend.app.models.payment import Payment
from backend.app.services.radar import GrowthRadarService, _pct_change
from backend.app.services.customer_intelligence import (
    ChurnRiskEngine,
    CustomerIntelligenceService,
)


def make_merchant(db_session: Session) -> Merchant:
    m = Merchant(
        name=f"P5 Radar {uuid.uuid4().hex[:6]}",
        slug=f"p5-radar-{uuid.uuid4().hex[:10]}",
        email="p5radar@x.com",
        status=MerchantStatus.active,
        currency=Currency.INR,
    )
    db_session.add(m)
    db_session.commit()
    return m


def add_order(
    db_session: Session,
    merchant: Merchant,
    customer: Customer,
    *,
    total: str = "1000.00",
    days_ago: int = 5,
    status: OrderStatus = OrderStatus.paid,
) -> Order:
    order = Order(
        merchant_id=merchant.id,
        customer_id=customer.id,
        order_number=f"ORD-{uuid.uuid4().hex[:10]}",
        status=status,
        subtotal=Decimal(total),
        discount=Decimal("0"),
        tax=Decimal("0"),
        total=Decimal(total),
        currency=Currency.INR,
        created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
    )
    db_session.add(order)
    db_session.flush()
    return order


def add_payment(
    db_session: Session,
    merchant: Merchant,
    order: Order,
    *,
    amount: str | None = None,
    status: PaymentStatus = PaymentStatus.captured,
    days_ago: int | None = None,
) -> Payment:
    created_at = order.created_at if days_ago is None else datetime.now(timezone.utc) - timedelta(days=days_ago)
    payment = Payment(
        merchant_id=merchant.id,
        order_id=order.id,
        provider=PaymentProvider.razorpay.value,
        amount=Decimal(amount or order.total),
        currency=Currency.INR.value if hasattr(Currency.INR, 'value') else Currency.INR,
        status=status.value if hasattr(status, 'value') else status,
        created_at=created_at,
    )
    db_session.add(payment)
    db_session.commit()
    return payment


def make_customer(db_session: Session, merchant: Merchant, *, orders: int = 1, spend: str = "1000") -> Customer:
    c = Customer(
        merchant_id=merchant.id,
        name=f"C-{uuid.uuid4().hex[:6]}",
        email=f"{uuid.uuid4().hex[:10]}@c.com",
        total_orders=orders,
        total_spend=Decimal(spend),
    )
    db_session.add(c)
    db_session.commit()
    return c


# ────────────────────────────────────────────────────────────────────────────
# Growth radar
# ────────────────────────────────────────────────────────────────────────────


class TestGrowthRadar:
    def test_empty_db_emits_no_signals(self, db_session: Session):
        m = make_merchant(db_session)
        svc = GrowthRadarService(db_session)
        signals = svc.detect(m.id, persist=False)
        assert signals == []

    def test_revenue_drop_signal_matches_raw_aggregate(self, db_session: Session):
        m = make_merchant(db_session)
        custs = [make_customer(db_session, m) for _ in range(4)]
        # previous window: ₹40k captured ; current: ₹20k (−50% ⇒ drop)
        for i in range(4):
            o = add_order(db_session, m, custs[i], total="10000", days_ago=45)
            add_payment(db_session, m, o)
        for i in range(2):
            o = add_order(db_session, m, custs[i], total="10000", days_ago=5)
            add_payment(db_session, m, o)

        signals = GrowthRadarService(db_session).detect(m.id, persist=False)
        drop = next(
            s for s in signals if s["signal_type"] == "revenue_drop"
        )
        assert float(drop["current_value"]) == 20000.00   # exactly the SQL sum
        assert float(drop["comparison_value"]) == 40000.00
        assert drop["change_percentage"] == pytest.approx(-50.0)
        assert drop["window_days"] == 30

    def test_no_revenue_drop_when_flat(self, db_session: Session):
        m = make_merchant(db_session)
        custs = [make_customer(db_session, m) for _ in range(4)]
        for i in range(4):
            o = add_order(db_session, m, custs[i], total="5000", days_ago=45)
            add_payment(db_session, m, o)
            o2 = add_order(db_session, m, custs[i], total="5000", days_ago=5)
            add_payment(db_session, m, o2)
        signals = GrowthRadarService(db_session).detect(m.id, persist=False)
        assert not any(s["signal_type"] == "revenue_drop" for s in signals)

    def test_emerging_growth_positive_trend(self, db_session: Session):
        m = make_merchant(db_session)
        custs = [make_customer(db_session, m) for _ in range(4)]
        for i in range(2):
            o = add_order(db_session, m, custs[i], total="10000", days_ago=45)
            add_payment(db_session, m, o)
        for i in range(4):
            o = add_order(db_session, m, custs[i], total="10000", days_ago=5)
            add_payment(db_session, m, o)
        signals = GrowthRadarService(db_session).detect(m.id, persist=False)
        growth = [s for s in signals if s["signal_type"] == "emerging_growth"]
        assert len(growth) == 1
        assert growth[0]["change_percentage"] == pytest.approx(100.0)

    def test_payment_failure_signals_reference_real_rows(self, db_session: Session):
        m = make_merchant(db_session)
        cust = make_customer(db_session, m)
        for amt in ("3000", "4000"):
            o = add_order(db_session, m, cust, total=amt, days_ago=3)
            add_payment(db_session, m, o, status=PaymentStatus.failed, amount=amt)
        signals = GrowthRadarService(db_session).detect(m.id, persist=False)
        fails = next(s for s in signals if s["signal_type"] == "payment_failures")
        recovery = next(
            s for s in signals if s["signal_type"] == "payment_recovery_opportunity"
        )
        assert float(fails["current_value"]) == 7000.00
        assert fails["evidence"]["failed_count"] == 2
        assert float(recovery["current_value"]) == 7000.00

    def test_dormant_customers_detected(self, db_session: Session):
        m = make_merchant(db_session)
        for _ in range(3):
            c = make_customer(db_session, m, orders=3, spend="9000")
            add_order(db_session, m, c, total="3000", days_ago=75)
        active = make_customer(db_session, m, orders=2, spend="4000")
        add_order(db_session, m, active, total="2000", days_ago=2)

        signals = GrowthRadarService(db_session).detect(m.id, persist=False)
        abandoned = [
            s for s in signals if s["signal_type"] == "abandoned_customers"
        ]
        assert len(abandoned) == 1
        assert float(abandoned[0]["current_value"]) == 3.0

    def test_persist_is_idempotent_within_bucket(self, db_session: Session):
        from sqlalchemy import func, select

        m = make_merchant(db_session)
        custs = [make_customer(db_session, m) for _ in range(4)]
        for i in range(4):
            o = add_order(db_session, m, custs[i], total="8000", days_ago=45)
            add_payment(db_session, m, o)
        for i in range(2):
            o = add_order(db_session, m, custs[i], total="8000", days_ago=5)
            add_payment(db_session, m, o)

        svc = GrowthRadarService(db_session)
        svc.detect(m.id)
        svc.detect(m.id)  # same day ⇒ same bucket
        count = db_session.scalar(
            select(func.count()).select_from(
                __import__("backend.app.models.growth_signal", fromlist=["GrowthSignal"]).GrowthSignal
            ).where(__import__("backend.app.models.growth_signal", fromlist=["GrowthSignal"]).GrowthSignal.merchant_id == m.id)
        )
        assert count == len({s["signal_type"] for s in svc.detect(m.id, persist=False)})

    def test_signals_are_merchant_scoped(self, db_session: Session):
        m1, m2 = make_merchant(db_session), make_merchant(db_session)
        c1 = make_customer(db_session, m1)
        for _ in range(4):
            o = add_order(db_session, m1, c1, total="10000", days_ago=45)
            add_payment(db_session, m1, o)
        GrowthRadarService(db_session).detect(m1.id)
        assert GrowthRadarService(db_session).list_signals(m2.id) == []

    def test_pct_change_helper(self):
        assert _pct_change(Decimal("80"), Decimal("100")) == Decimal("-20.00")
        assert _pct_change(Decimal("120"), Decimal("100")) == Decimal("20.00")
        assert _pct_change(Decimal("50"), Decimal("0")) is None


# ────────────────────────────────────────────────────────────────────────────
# Churn risk engine (pure heuristics)
# ────────────────────────────────────────────────────────────────────────────


class TestChurnRiskEngine:
    def setup_method(self) -> None:
        self.engine = ChurnRiskEngine()

    def _compute(self, **overrides):
        base = dict(
            recency_days=47,
            avg_interval_days=18.0,
            recent_order_count=0,
            baseline_order_count=3.3,
            recent_spend=Decimal("0"),
            baseline_spend=Decimal("3300"),
            payment_count=6,
            failed_payment_count=0,
        )
        base.update(overrides)
        return self.engine.compute(**base)

    def test_high_churn_example_from_spec(self):
        result = self._compute()
        assert result["churn_risk_score"] > 55
        assert result["risk_level"] in ("high", "critical")
        reasons = " ".join(result["reasons"])
        assert "47 days since last purchase" in reasons
        assert "previous average interval: 18 days" in reasons

    def test_engaged_recent_customer_scores_minimal(self):
        result = self._compute(
            recency_days=3,
            recent_order_count=4,
            baseline_order_count=3.0,
            recent_spend=Decimal("4000"),
            baseline_spend=Decimal("3600"),
        )
        assert result["churn_risk_score"] < 15
        assert result["risk_level"] == "minimal"

    def test_score_components_are_bounded(self):
        worst = self._compute(recency_days=365, failed_payment_count=6)
        assert 0 <= worst["churn_risk_score"] <= 100
        comp = worst["components"]
        assert all(
            0 <= v <= 1
            for k, v in comp.items()
            if not k.endswith("_pct")
        )
        assert worst["churn_risk_score"] <= 100

    def test_reasons_generated_for_each_decline(self):
        result = self._compute(failed_payment_count=3)
        joined = " ".join(result["reasons"])
        assert "purchase frequency decreased" in joined
        assert "spending decreased" in joined
        assert "payments failed" in joined

    def test_level_boundaries_deterministic(self):
        f = ChurnRiskEngine.level_for
        assert f(Decimal("80")) == ChurnRiskLevelLevel_CRITICAL if False else f(Decimal("80")) .value == "critical"
        assert f(Decimal("60")).value == "high"
        assert f(Decimal("40")).value == "medium"
        assert f(Decimal("20")).value == "low"
        assert f(Decimal("5")).value == "minimal"

    def test_weights_sum_to_one(self):
        assert sum(ChurnRiskEngine.WEIGHTS.values()) == Decimal("1")


# keep flake-free reference used above
ChurnRiskLevelLevel_CRITICAL = "critical"


# ────────────────────────────────────────────────────────────────────────────
# Customer intelligence service
# ────────────────────────────────────────────────────────────────────────────


class TestCustomerIntelligence:
    def test_metrics_match_seeded_rows(self, db_session: Session):
        m = make_merchant(db_session)
        c = make_customer(db_session, m, orders=2, spend="3000")
        add_order(db_session, m, c, total="1500", days_ago=40)
        add_order(db_session, m, c, total="1500", days_ago=10)

        insights = CustomerIntelligenceService(db_session).compute_metrics(m.id)
        row = next(i for i in insights if i["customer_id"] == c.id)
        assert row["order_count"] == 2
        assert float(row["lifetime_value"]) == 3000.00
        assert float(row["avg_order_value"]) == 1500.00
        assert row["recency_days"] == 10
        assert row["segments"].count("repeat_customer") == 1

    def test_vip_classification_by_median_ltv(self, db_session: Session):
        m = make_merchant(db_session)
        # five customers with ~₹1000 real order history each (median ≈ 1000)
        for _ in range(5):
            c = make_customer(db_session, m, orders=1, spend="1000")
            add_order(db_session, m, c, total="1000", days_ago=20)
        # VIP: five real orders totalling ₹25000
        vip = make_customer(db_session, m, orders=5, spend="25000")
        for i in range(5):
            add_order(db_session, m, vip, total="5000", days_ago=10 + i)

        insights = CustomerIntelligenceService(db_session).refresh(m.id)
        vip_row = next(i for i in insights if i.customer_id == vip.id)
        assert "vip" in vip_row.segments

    def test_dormant_segment_after_90_days(self, db_session: Session):
        m = make_merchant(db_session)
        c = make_customer(db_session, m, orders=3, spend="6000")
        add_order(db_session, m, c, total="3000", days_ago=120)

        insights = CustomerIntelligenceService(db_session).refresh(m.id)
        row = next(i for i in insights if i.customer_id == c.id)
        assert "dormant" in row.segments
        # churn_risk_level is a plain string column
        assert row.churn_risk_level in ("medium", "high", "critical")

    def test_refresh_is_idempotent(self, db_session: Session):
        from sqlalchemy import func, select

        from backend.app.models.customer_insight import CustomerInsight

        m = make_merchant(db_session)
        c = make_customer(db_session, m, orders=2, spend="2000")
        add_order(db_session, m, c, total="1000", days_ago=30)

        svc = CustomerIntelligenceService(db_session)
        svc.refresh(m.id)
        svc.refresh(m.id)
        count = db_session.scalar(
            select(func.count()).select_from(CustomerInsight).where(
                CustomerInsight.merchant_id == m.id
            )
        )
        assert count == 1

    def test_cross_merchant_isolation(self, db_session: Session):
        m1, m2 = make_merchant(db_session), make_merchant(db_session)
        c1 = make_customer(db_session, m1, orders=2, spend="5000")
        add_order(db_session, m1, c1, total="2500", days_ago=20)

        CustomerIntelligenceService(db_session).refresh(m1.id)
        assert CustomerIntelligenceService(db_session).list_insights(m2.id) == []
        assert (
            CustomerIntelligenceService(db_session).get_customer_insight(m2.id, c1.id)
            is None
        )

    def test_get_single_insight_scoped(self, db_session: Session):
        m = make_merchant(db_session)
        c = make_customer(db_session, m, orders=1, spend="500")
        add_order(db_session, m, c, total="500", days_ago=8)
        CustomerIntelligenceService(db_session).refresh(m.id)
        got = CustomerIntelligenceService(db_session).get_customer_insight(m.id, c.id)
        assert got is not None and got.customer_id == c.id

    def test_no_llm_required_for_numbers(self, db_session: Session):
        """Metrics compute with no LLM configured — deterministic data path."""
        m = make_merchant(db_session)
        c = make_customer(db_session, m, orders=2, spend="2000")
        add_order(db_session, m, c, total="1000", days_ago=15)
        svc = CustomerIntelligenceService(db_session)  # no llm param exists
        rows = svc.compute_metrics(m.id)
        assert rows and all(r["order_count"] >= 1 for r in rows)
