"""Phase 5 — What-If simulation engine + experiment engine."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from backend.app.models.enums import Currency, ExperimentStatus, MerchantStatus
from backend.app.models.experiment import Simulation
from backend.app.models.merchant import Merchant
from backend.app.services.simulation import (
    SimulationEngine,
    SimulationValidationError,
)
from backend.app.services.experiment_service import (
    MIN_DETECTABLE_SAMPLE,
    ExperimentService,
    ExperimentValidationError,
)


@pytest.fixture()
def merchant(db_session: Session) -> Merchant:
    m = Merchant(
        name=f"P5 Sim {uuid.uuid4().hex[:6]}",
        slug=f"p5-sim-{uuid.uuid4().hex[:10]}",
        email="p5sim@x.com",
        status=MerchantStatus.active,
        currency=Currency.INR,
    )
    db_session.add(m)
    db_session.commit()
    return m


# ────────────────────────────────────────────────────────────────────────────
# Simulation engine
# ────────────────────────────────────────────────────────────────────────────


class TestSimulationEngine:
    def setup_method(self) -> None:
        self.engine = SimulationEngine()

    def test_discount_math_exact(self):
        # 200 customers × 0.10 conversion = 20 buyers × ₹500 = ₹10k gross
        # 10% discount ⇒ cost 1000, net revenue 9000, profit 9000−1000 = 8000
        r = self.engine.simulate_discount(
            discount_percentage=10,
            target_customers=200,
            expected_conversion=0.10,
            avg_order_value=500,
        )
        assert r.estimated_revenue == pytest.approx(9000.0)
        assert r.estimated_cost == pytest.approx(1000.0)
        assert r.estimated_profit == pytest.approx(8000.0)
        assert r.expected_roi == pytest.approx(8.0)

    def test_campaign_math_exact(self):
        # 100 × 0.25 = 25 buyers × ₹400 = ₹10k ; cost 100×₹2 = ₹200
        r = self.engine.simulate_campaign(
            target_customers=100,
            expected_conversion=0.25,
            avg_order_value=400,
            cost_per_target=2,
        )
        assert r.estimated_revenue == pytest.approx(10000.0)
        assert r.estimated_cost == pytest.approx(200.0)
        assert r.expected_roi == pytest.approx(49.0)

    def test_payment_recovery_math_exact(self):
        r = self.engine.simulate_payment_recovery(
            failed_payment_value=50000, recovery_rate=0.3, cost_per_contact=1, contacts=50
        )
        assert r.estimated_revenue == pytest.approx(15000.0)
        assert r.estimated_cost == pytest.approx(50.0)

    def test_confidence_range_is_pm_20_percent(self):
        r = self.engine.simulate_campaign(
            target_customers=100, expected_conversion=0.5, avg_order_value=100
        )
        assert r.confidence_low == pytest.approx(r.estimated_revenue * 0.8)
        assert r.confidence_high == pytest.approx(r.estimated_revenue * 1.2)

    def test_everything_labelled_estimate(self):
        r = self.engine.simulate_discount(
            discount_percentage=15, target_customers=50,
            expected_conversion=0.2, avg_order_value=800,
        )
        d = r.to_dict()
        assert r.is_estimate is True and d["is_estimate"] is True
        for key in ("estimated_revenue", "estimated_cost", "estimated_profit"):
            assert key in d
        assert "assumptions" in d and len(d["assumptions"]) > 0

    def test_deterministic(self):
        kwargs = dict(
            discount_percentage=12, target_customers=300,
            expected_conversion=0.08, avg_order_value=1200,
        )
        assert self.engine.simulate_discount(**kwargs).to_dict() == (
            self.engine.simulate_discount(**kwargs).to_dict()
        )

    def test_conversion_bounds_enforced(self):
        with pytest.raises(SimulationValidationError):
            self.engine.simulate_campaign(
                target_customers=10, expected_conversion=1.5, avg_order_value=100
            )
        with pytest.raises(SimulationValidationError):
            self.engine.simulate_campaign(
                target_customers=10, expected_conversion=-0.1, avg_order_value=100
            )

    def test_discount_percentage_bounds_enforced(self):
        with pytest.raises(SimulationValidationError):
            self.engine.simulate_discount(
                discount_percentage=150, target_customers=10,
                expected_conversion=0.1, avg_order_value=100,
            )

    def test_negative_inputs_rejected(self):
        with pytest.raises(SimulationValidationError):
            self.engine.simulate_campaign(
                target_customers=-5, expected_conversion=0.1, avg_order_value=100
            )
        with pytest.raises(SimulationValidationError):
            self.engine.simulate_payment_recovery(
                failed_payment_value=-1, recovery_rate=0.2
            )

    def test_unknown_scenario_type_rejected(self):
        with pytest.raises(SimulationValidationError):
            self.engine.simulate("moonshot", target_customers=1)

    def test_zero_cost_gives_null_roi_not_infinity(self):
        r = self.engine.simulate_campaign(
            target_customers=10, expected_conversion=0.5, avg_order_value=100,
            cost_per_target=0,
        )
        assert r.expected_roi is None

    def test_persist_marks_estimate_and_scopes_merchant(
        self, db_session: Session, merchant: Merchant
    ):
        other = Merchant(name="O", slug=f"o-{uuid.uuid4().hex[:8]}", email="o@x.com",
                         status=MerchantStatus.active, currency=Currency.INR)
        db_session.add(other); db_session.commit()

        engine = SimulationEngine(db_session)
        result = engine.simulate_discount(
            discount_percentage=10, target_customers=100,
            expected_conversion=0.2, avg_order_value=500,
        )
        row = engine.persist(result, merchant_id=merchant.id, created_by_agent="test")
        db_session.flush()
        assert isinstance(row, Simulation)
        assert row.is_estimate is True
        assert row.merchant_id == merchant.id
        mine = db_session.query(Simulation).filter(
            Simulation.merchant_id.in_([merchant.id, other.id])
        ).all()
        ids = {s.merchant_id for s in mine}
        assert ids == {merchant.id}  # other merchant sees nothing


# ────────────────────────────────────────────────────────────────────────────
# Experiment engine
# ────────────────────────────────────────────────────────────────────────────


class TestExperimentService:
    def setup_method(self) -> None:
        self.svc: dict[str, ExperimentService] = {}

    def service(self, db_session: Session) -> ExperimentService:
        return ExperimentService(db_session)

    def test_create_experiment_idempotent_by_name(self, db_session: Session, merchant: Merchant):
        svc = self.service(db_session)
        kwargs = dict(
            merchant_id=merchant.id, name="VIP 10% discount test",
            hypothesis="Discount lifts repeat purchases",
            control_group={"offer": "none"}, treatment_group={"offer": "10% off"},
            target_population_size=500,
        )
        a = svc.create_experiment(**kwargs)
        b = svc.create_experiment(**kwargs)
        assert a.id == b.id
        assert a.status == ExperimentStatus.proposed

    def test_pending_until_min_sample(self, db_session: Session, merchant: Merchant):
        svc = self.service(db_session)
        exp = svc.create_experiment(merchant_id=merchant.id, name="Small test")
        result = svc.record_result(
            experiment=exp, control_size=10, control_conversions=2,
            treatment_size=10, treatment_conversions=4,
        )
        assert result.statistical_status == "measurement_pending"
        assert result.uplift_percentage is None
        assert exp.status == ExperimentStatus.measurement_pending

    def test_uplift_reported_only_with_real_counts(self, db_session: Session, merchant: Merchant):
        svc = self.service(db_session)
        exp = svc.create_experiment(merchant_id=merchant.id, name="Big test")
        n = MIN_DETECTABLE_SAMPLE
        result = svc.record_result(
            experiment=exp,
            control_size=n * 10, control_conversions=n,
            treatment_size=n * 10, treatment_conversions=n * 2,  # CR 10% → 20%
        )
        assert result.uplift_percentage == pytest.approx(Decimal("100.00"))
        assert result.statistical_status == "directional_uplift"

    def test_never_claims_statistical_significance(self, db_session: Session, merchant: Merchant):
        svc = self.service(db_session)
        exp = svc.create_experiment(merchant_id=merchant.id, name="Wording test")
        n = MIN_DETECTABLE_SAMPLE
        result = svc.record_result(
            experiment=exp,
            control_size=n * 10, control_conversions=n,
            treatment_size=n * 10, treatment_conversions=n * 3,
        )
        blob = str(result.statistical_status).lower()
        assert "significant" not in blob

    def test_zero_baseline_handled_honestly(self, db_session: Session, merchant: Merchant):
        svc = self.service(db_session)
        exp = svc.create_experiment(merchant_id=merchant.id, name="Zero baseline")
        n = MIN_DETECTABLE_SAMPLE
        result = svc.record_result(
            experiment=exp,
            control_size=n * 10, control_conversions=0,
            treatment_size=n * 10, treatment_conversions=n,
        )
        assert result.uplift_percentage is None
        assert result.statistical_status == "insufficient_baseline"

    def test_invalid_counts_rejected(self, db_session: Session, merchant: Merchant):
        svc = self.service(db_session)
        exp = svc.create_experiment(merchant_id=merchant.id, name="Bad counts")
        with pytest.raises(ExperimentValidationError):
            svc.record_result(
                experiment=exp, control_size=5, control_conversions=9,
                treatment_size=5, treatment_conversions=1,
            )

    def test_cross_merchant_experiment_invisible(self, db_session: Session, merchant: Merchant):
        other = Merchant(name="O2", slug=f"o2-{uuid.uuid4().hex[:8]}", email="o2@x.com",
                         status=MerchantStatus.active, currency=Currency.INR)
        db_session.add(other); db_session.commit()
        svc = self.service(db_session)
        exp = svc.create_experiment(merchant_id=merchant.id, name="Secret test")
        assert svc.get_experiment(other.id, exp.id) is None
        assert svc.list_experiments(other.id) == []
