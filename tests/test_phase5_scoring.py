"""Phase 5 — opportunity scoring engine + deterministic deduplication."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from backend.app.models.merchant import Merchant
from backend.app.models.enums import Currency, MerchantStatus, OpportunityType
from backend.app.services.scoring import (
    OpportunityScoringEngine,
    ScoreBreakdown,
    default_risk_for_action_type,
)
from backend.app.services.opportunity_upsert import (
    build_opportunity_key,
    upsert_opportunity,
)


@pytest.fixture()
def merchant(db_session: Session) -> Merchant:
    m = Merchant(
        name="P5 Scoring Merchant",
        slug=f"p5-score-{uuid.uuid4().hex[:10]}",
        email="p5score@x.com",
        status=MerchantStatus.active,
        currency=Currency.INR,
    )
    db_session.add(m)
    db_session.commit()
    return m


# ────────────────────────────────────────────────────────────────────────────
# Scoring engine
# ────────────────────────────────────────────────────────────────────────────


class TestScoringEngine:
    def setup_method(self) -> None:
        self.engine = OpportunityScoringEngine()

    def test_score_is_deterministic(self):
        kwargs = dict(
            expected_revenue=120000,
            confidence=0.8,
            target_customer_count=200,
            evidence_items=4,
            urgency_score=0.7,
            implementation_cost=0.3,
        )
        a = self.engine.score(**kwargs)
        b = self.engine.score(**kwargs)
        assert a.opportunity_score == b.opportunity_score
        assert a.to_dict() == b.to_dict()

    def test_known_formula_exact_value(self):
        # revenue_potential = 100000/500000 = 0.2 ; confidence 0.5 ;
        # urgency 1.0 ; evidence 5/5=1.0 ; cost adj 1.0+0.0 = 1.0
        # score = 100 * 0.2*0.5*1.0*1.0/1.0 = 10.00
        result = self.engine.score(
            expected_revenue=100000,
            confidence=0.5,
            urgency_score=1.0,
            evidence_items=5,
            implementation_cost=0,
        )
        assert result.opportunity_score == pytest.approx(10.0)

    def test_score_within_predictable_range(self):
        low = self.engine.score(expected_revenue=0, confidence=0)
        high = self.engine.score(
            expected_revenue=99999999, confidence=1, urgency_score=1,
            evidence_items=50, implementation_cost=0,
        )
        assert 0 <= low.opportunity_score <= 100
        assert 0 <= high.opportunity_score <= 100

    def test_cost_adjustment_dampens_never_inflates(self):
        base = self.engine.score(expected_revenue=100000, confidence=0.8, implementation_cost=0)
        costly = self.engine.score(expected_revenue=100000, confidence=0.8, implementation_cost=1.0)
        assert costly.opportunity_score < base.opportunity_score
        assert costly.implementation_cost_adjustment == pytest.approx(2.0)

    def test_higher_evidence_strength_raises_score(self):
        weak = self.engine.score(expected_revenue=80000, confidence=0.7, evidence_items=0)
        strong = self.engine.score(expected_revenue=80000, confidence=0.7, evidence_items=6)
        assert strong.evidence_strength > weak.evidence_strength
        assert strong.opportunity_score > weak.opportunity_score

    def test_evidence_strength_floored_not_zero(self):
        result = self.engine.score(expected_revenue=80000, confidence=0.7, evidence_items=0)
        assert result.evidence_strength == pytest.approx(0.20)

    def test_revenue_potential_capped_and_note_added(self):
        result = self.engine.score(expected_revenue=10_000_000, confidence=0.9)
        assert result.revenue_potential == 1.0
        assert any("capped" in n for n in result.notes)

    def test_expected_roi_computed_only_with_positive_cost(self):
        with_cost = self.engine.score(expected_revenue=100000, confidence=0.5, estimated_cost=25000)
        no_cost = self.engine.score(expected_revenue=100000, confidence=0.5)
        assert with_cost.expected_roi == pytest.approx(4.0)
        assert no_cost.expected_roi is None

    def test_breakdown_exposes_all_required_factors(self):
        result = self.engine.score(
            expected_revenue=90000, confidence=0.75, target_customer_count=120,
            urgency_score=0.6, risk_score=0.4,
        )
        d = result.to_dict()
        for key in (
            "revenue_potential", "confidence_score", "urgency_score",
            "customer_impact", "implementation_cost", "risk_score",
            "evidence_strength", "expected_roi", "opportunity_score", "formula",
        ):
            assert key in d

    def test_urgency_defaults_to_neutral(self):
        r = self.engine.score(expected_revenue=50000, confidence=0.5)
        assert r.urgency_score == pytest.approx(0.5)

    def test_negative_inputs_clamped(self):
        r = self.engine.score(
            expected_revenue=-500, confidence=-2, urgency_score=99, implementation_cost=-5
        )
        assert 0 <= r.opportunity_score <= 100
        assert r.confidence_score == 0.0

    def test_risk_reported_but_not_folded_into_headline_score(self):
        safe = self.engine.score(expected_revenue=100000, confidence=0.8, risk_score=0.0)
        risky = self.engine.score(expected_revenue=100000, confidence=0.8, risk_score=1.0)
        assert risky.risk_score == pytest.approx(1.0)
        assert safe.opportunity_score == risky.opportunity_score

    def test_llm_output_cannot_set_final_score(self):
        """The public API has no parameter accepting a final score."""
        import inspect

        sig = inspect.signature(OpportunityScoringEngine.score)
        assert "opportunity_score" not in sig.parameters
        assert "llm_score" not in sig.parameters

    def test_default_risk_mapping_matches_phase4_high_risk_actions(self):
        assert default_risk_for_action_type("retry_payment") > 0.5
        assert default_risk_for_action_type("create_discount") > 0.5
        assert default_risk_for_action_type("send_campaign") < 0.8
        assert default_risk_for_action_type("generate_opportunity") < 0.5


# ────────────────────────────────────────────────────────────────────────────
# Deduplication / upsert
# ────────────────────────────────────────────────────────────────────────────


class TestOpportunityDedup:
    def test_key_is_deterministic(self):
        mid = uuid.uuid4()
        a = build_opportunity_key(mid, "campaign", "dormant", 30)
        b = build_opportunity_key(mid, "campaign", "dormant", 30)
        assert a == b and len(a) == 32

    def test_key_varies_by_inputs(self):
        mid = uuid.uuid4()
        variants = {
            build_opportunity_key(mid, "campaign", "dormant", 30),
            build_opportunity_key(mid, "discount", "dormant", 30),
            build_opportunity_key(mid, "campaign", "vip", 30),
            build_opportunity_key(mid, "campaign", "dormant", 60),
        }
        assert len(variants) == 4

    def test_same_key_across_merchants_differs(self):
        k1 = build_opportunity_key(uuid.uuid4(), "campaign", "vip", 30)
        k2 = build_opportunity_key(uuid.uuid4(), "campaign", "vip", 30)
        assert k1 != k2

    def test_first_upsert_creates(self, db_session: Session, merchant: Merchant):
        key = build_opportunity_key(merchant.id, "payment_recovery", "failed_payments", 30)
        opp, created = upsert_opportunity(
            db_session,
            merchant_id=merchant.id,
            opportunity_key=key,
            type_=OpportunityType.failed_payment_recovery,
            title="Recover failed payments",
            confidence=Decimal("0.70"),
            expected_revenue=Decimal("50000"),
            reasoning=["12 failed payments in window"],
        )
        db_session.flush()
        assert created is True
        assert opp.status.value == "pending_approval"

    def test_second_upsert_reinforces_not_duplicates(self, db_session: Session, merchant: Merchant):
        key = build_opportunity_key(merchant.id, "campaign", "dormant", 30)
        opp1, created1 = upsert_opportunity(
            db_session, merchant_id=merchant.id, opportunity_key=key,
            type_=OpportunityType.campaign, title="Win-back dormant",
            confidence=Decimal("0.60"), expected_revenue=Decimal("40000"),
            reasoning=["signal A"],
        )
        db_session.flush()
        opp2, created2 = upsert_opportunity(
            db_session, merchant_id=merchant.id, opportunity_key=key,
            type_=OpportunityType.campaign, title="Win-back dormant",
            confidence=Decimal("0.85"), expected_revenue=Decimal("60000"),
            reasoning=["signal A", "signal B"],
        )
        db_session.flush()
        assert created1 and not created2
        assert opp1.id == opp2.id
        assert Decimal(str(opp2.confidence)) == Decimal("0.85")  # raised
        assert Decimal(str(opp2.expected_revenue)) == Decimal("60000")
        titles = [r for r in (opp2.reasoning or []) if str(r).startswith("signal")]
        assert sorted(titles) == ["signal A", "signal B"]

    def test_reinforcement_never_lowers_confidence(self, db_session: Session, merchant: Merchant):
        key = build_opportunity_key(merchant.id, "upsell", "repeat_customers", 30)
        _, _ = upsert_opportunity(
            db_session, merchant_id=merchant.id, opportunity_key=key,
            type_=OpportunityType.upsell, title="Upsell",
            confidence=Decimal("0.90"), expected_revenue=Decimal("90000"),
        )
        db_session.flush()
        opp, created = upsert_opportunity(
            db_session, merchant_id=merchant.id, opportunity_key=key,
            type_=OpportunityType.upsell, title="Upsell",
            confidence=Decimal("0.40"), expected_revenue=Decimal("10000"),
        )
        assert not created
        assert Decimal(str(opp.confidence)) == Decimal("0.90")
        assert Decimal(str(opp.expected_revenue)) == Decimal("90000")

    def test_cross_merchant_same_logical_key_isolated(self, db_session: Session, merchant: Merchant):
        other = Merchant(
            name="Other", slug=f"other-{uuid.uuid4().hex[:8]}",
            email="other@x.com", status=MerchantStatus.active, currency=Currency.INR,
        )
        db_session.add(other)
        db_session.commit()

        seg, typ, win = "vip", "campaign", 30
        k1 = build_opportunity_key(merchant.id, typ, seg, win)
        k2 = build_opportunity_key(other.id, typ, seg, win)
        assert k1 != k2
        upsert_opportunity(
            db_session, merchant_id=merchant.id, opportunity_key=k1,
            type_=OpportunityType.campaign, title="M1 VIP campaign",
            confidence=Decimal("0.7"), expected_revenue=Decimal("70000"),
        )
        db_session.flush()
        opp2, created2 = upsert_opportunity(
            db_session, merchant_id=other.id, opportunity_key=k2,
            type_=OpportunityType.campaign, title="M2 VIP campaign",
            confidence=Decimal("0.7"), expected_revenue=Decimal("70000"),
        )
        assert created2  # merchant A's row did NOT absorb merchant B's detection

    def test_reinforcement_does_not_change_status(self, db_session: Session, merchant: Merchant):
        from backend.app.models.enums import OpportunityStatus

        key = build_opportunity_key(merchant.id, "checkout_optimization", "all", 30)
        opp, _ = upsert_opportunity(
            db_session, merchant_id=merchant.id, opportunity_key=key,
            type_=OpportunityType.checkout_optimization, title="Checkout",
            confidence=Decimal("0.5"), expected_revenue=Decimal("30000"),
        )
        opp.status = OpportunityStatus.completed
        db_session.flush()
        reinforced, created = upsert_opportunity(
            db_session, merchant_id=merchant.id, opportunity_key=key,
            type_=OpportunityType.checkout_optimization, title="Checkout",
            confidence=Decimal("0.9"), expected_revenue=Decimal("31000"),
        )
        assert not created
        assert reinforced.status == OpportunityStatus.completed

    def test_reasoning_list_capped(self, db_session: Session, merchant: Merchant):
        from backend.app.services.opportunity_upsert import MAX_REASONING_ITEMS

        key = build_opportunity_key(merchant.id, "cross_sell", "buyers", 30)
        big = [f"evidence {i}" for i in range(MAX_REASONING_ITEMS + 20)]
        opp, _ = upsert_opportunity(
            db_session, merchant_id=merchant.id, opportunity_key=key,
            type_=OpportunityType.cross_sell, title="Cross sell",
            confidence=Decimal("0.5"), expected_revenue=Decimal("20000"),
            reasoning=big,
        )
        assert len(opp.reasoning) <= MAX_REASONING_ITEMS


def test_scorebreakdown_is_dataclass_serializable():
    s = OpportunityScoringEngine().score(expected_revenue=1000, confidence=0.5)
    assert isinstance(s, ScoreBreakdown)
    assert isinstance(s.to_dict(), dict)
