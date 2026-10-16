"""Phase 5 — API contract tests for every new route."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backend.app.agents.registry import AGENT_INSTANCES
from fastapi.testclient import TestClient

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
from tests.security_utils import bearer, make_world, create_access_token


@pytest.fixture(scope="module")
def api(client: TestClient) -> TestClient:
    return client


@pytest.fixture()
def world(db_session):
    """A merchant with an owner membership."""
    return make_world(db_session, slug_hint="p5api")


def _auth(user) -> dict[str, str]:
    """Authorization headers carrying a valid token."""
    token, _ = create_access_token(user.id, user.email)
    return {"Authorization": f"Bearer {token}"}


# Keep the old merchant fixture for backward compatibility
@pytest.fixture()
def merchant(world) -> Merchant:
    return world[0]


def _seed_minimal_commerce(db_session, merchant: Merchant, *, failures: int = 2) -> None:
    """Enough real rows for radar signals + brief revenue (prior window)."""
    now = datetime.now(timezone.utc)
    c = Customer(merchant_id=merchant.id, name="A", email=f"a-{uuid.uuid4().hex[:6]}@x.com")
    db_session.add(c); db_session.flush()
    o = Order(
        merchant_id=merchant.id, customer_id=c.id,
        order_number="API-1", status=OrderStatus.paid,
        subtotal=Decimal("40000"), discount=Decimal("0"), tax=Decimal("0"),
        total=Decimal("40000"), currency=Currency.INR,
        created_at=now - timedelta(days=45),
    )
    db_session.add(o); db_session.flush()
    db_session.add(Payment(
        merchant_id=merchant.id, order_id=o.id, provider=PaymentProvider.razorpay,
        amount=Decimal("40000"), currency=Currency.INR, status=PaymentStatus.captured,
        created_at=now - timedelta(days=45),
    ))
    for i in range(failures):
        fo = Order(
            merchant_id=merchant.id, customer_id=c.id,
            order_number=f"API-F{i}", status=OrderStatus.pending,
            subtotal=Decimal("2000"), discount=Decimal("0"), tax=Decimal("0"),
            total=Decimal("2000"), currency=Currency.INR,
            created_at=now - timedelta(days=2),
        )
        db_session.add(fo); db_session.flush()
        db_session.add(Payment(
            merchant_id=merchant.id, order_id=fo.id, provider=PaymentProvider.razorpay,
            amount=Decimal("2000"), currency=Currency.INR, status=PaymentStatus.failed,
            # Real ingestion always records a provider failure code. Without
            # one the recovery agent treats the failure as UNKNOWN and
            # correctly refuses to auto-retry it, so a realistic code is
            # required for this fixture to represent a genuine merchant.
            failure_code="GATEWAY_ERROR",
            created_at=now - timedelta(days=2),
        ))
    db_session.commit()


class TestRoutePresence:
    def test_all_phase5_routes_in_openapi(self, api: TestClient):
        spec = api.get("/openapi.json").json()["paths"]
        expected = [
            "/api/agents", "/api/agents/runs", "/api/agents/runs/{run_id}",
            "/api/agents/run", "/api/radar", "/api/opportunities/ranked",
            "/api/customer-insights", "/api/customers/{customer_id}/insights",
            "/api/simulations", "/api/experiments", "/api/growth-memory",
            "/api/growth-brief",
        ]
        for path in expected:
            assert path in spec, f"missing {path}"

    def test_no_double_api_prefix_anywhere(self, api: TestClient):
        spec = api.get("/openapi.json").json()["paths"]
        assert not any("/api/api/" in p for p in spec)


class TestAgentsApi:
    def test_list_agents_reports_permissions(self, api: TestClient, world):
        merchant, user, _token = world
        res = api.get("/api/agents", headers=bearer(user))
        assert res.status_code == 200, res.text
        body = res.json()
        # 9 domain specialists + 5 main growth team. Kept in step with the
        # registry so a newly registered agent can never be silently omitted
        # from the merchant-visible catalog.
        assert len(body["agents"]) == len(AGENT_INSTANCES)
        for agent in body["agents"]:
            assert agent["can_approve"] is False and agent["can_execute"] is False

    def test_runs_endpoint_shape(self, api: TestClient, world, db_session):
        merchant, user, _token = world
        res = api.get("/api/agents/runs", headers=bearer(user))
        assert res.status_code == 200, res.text
        body = res.json()
        assert "runs" in body
        assert all(
            {"id", "agent_name", "status", "total_latency_ms"} <= set(r.keys())
            for r in body["runs"]
        )

    def test_unknown_run_404(self, api: TestClient, world):
        merchant, user, _token = world
        res = api.get(f"/api/agents/runs/{uuid.uuid4()}", headers=bearer(user))
        assert res.status_code == 404

    def test_invalid_run_id_400(self, api: TestClient, world):
        merchant, user, _token = world
        res = api.get("/api/agents/runs/not-a-uuid", headers=bearer(user))
        assert res.status_code == 400

    def test_post_run_fast_mode(self, api: TestClient, world, db_session):
        merchant, user, _token = world
        _seed_minimal_commerce(db_session, merchant)
        res = api.post(
            "/api/agents/run",
            json={"mode": "fast", "merchant_id": str(merchant.id)},
            headers=bearer(user),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] in ("completed", "running", "pending")
        # fast mode runs synchronously, so it should complete
        assert body["status"] == "completed"
        assert len(body["agents"]) == 4
        assert any(a["agent"] == "GrowthDiscoveryAgent" for a in body["agents"])

    def test_post_run_invalid_mode_422(self, api: TestClient, world, db_session):
        merchant, user, _token = world
        res = api.post(
            "/api/agents/run", 
            json={"mode": "chaos"},
            headers=bearer(user),
        )
        assert res.status_code == 422

    def test_post_run_unknown_merchant_403(self, api: TestClient, world):
        merchant, user, _token = world
        res = api.post(
            "/api/agents/run", 
            json={"mode": "fast", "merchant_id": str(uuid.uuid4())},
            headers=bearer(user),
        )
        # Authenticated user without membership -> 403 MERCHANT_ACCESS_DENIED
        assert res.status_code == 403, res.text
        assert res.json()["detail"] == "MERCHANT_ACCESS_DENIED"


class TestRadarAndRanked:
    def test_radar_empty_merchant_no_signals(self, api: TestClient, world):
        merchant, user, _token = world
        res = api.get(f"/api/radar?merchant_id={merchant.id}", headers=bearer(user))
        assert res.status_code == 200
        assert res.json()["signals"] == []

    def test_radar_refresh_produces_real_signals(self, api: TestClient, world, db_session):
        merchant, user, _token = world
        _seed_minimal_commerce(db_session, merchant)
        res = api.post(
            "/api/agents/run", json={"mode": "fast", "merchant_id": str(merchant.id)}, headers=bearer(user)
        )
        assert res.status_code == 200
        res = api.get(f"/api/radar?merchant_id={merchant.id}", headers=bearer(user))
        signals = res.json()["signals"]
        assert signals, "expected persisted signals"
        sig = signals[0]
        for key in ("signal_type", "metric", "current_value", "comparison_value",
                    "window_days", "confidence"):
            assert key in sig

    def test_ranked_opportunities_with_breakdown(self, api: TestClient, world, db_session):
        from backend.app.services.opportunity_upsert import upsert_opportunity
        from decimal import Decimal as D
        from backend.app.models.enums import OpportunityType
        from backend.app.services.opportunity_upsert import build_opportunity_key

        merchant, user, _token = world
        opp, _ = upsert_opportunity(
            db_session,
            merchant_id=merchant.id,
            opportunity_key=build_opportunity_key(merchant.id, "campaign", "vip", 30),
            type_=OpportunityType.campaign,
            title="VIP campaign",
            confidence=D("0.8"),
            expected_revenue=D("120000"),
            reasoning=["evidence one", {"basis": "real data"}],
        )
        db_session.commit()
        res = api.get(f"/api/opportunities/ranked?merchant_id={merchant.id}", headers=bearer(user))
        assert res.status_code == 200
        ranked = res.json()["opportunities"]
        assert len(ranked) == 1
        top = ranked[0]
        assert top["rank"] == 1
        assert "score_breakdown" in top and "formula" in top["score_breakdown"]

    def test_ranked_rejects_bad_status(self, api: TestClient, world):
        merchant, user, _token = world
        res = api.get(f"/api/opportunities/ranked?merchant_id={merchant.id}&status=bogus", headers=bearer(user))
        assert res.status_code == 400


class TestInsightsApi:
    def test_customer_insights_empty(self, api: TestClient, world):
        merchant, user, _token = world
        res = api.get(f"/api/customer-insights?merchant_id={merchant.id}", headers=bearer(user))
        assert res.status_code == 200
        body = res.json()
        assert body["count"] == 0 and body["insights"] == []

    def test_customer_insight_single_missing(self, api: TestClient, world):
        merchant, user, _token = world
        res = api.get(
            f"/api/customers/{uuid.uuid4()}/insights?merchant_id={merchant.id}",
            headers=bearer(user),
        )
        assert res.status_code == 404

    def test_customer_insight_invalid_uuid(self, api: TestClient, world):
        merchant, user, _token = world
        res = api.get(f"/api/customers/not-a-uuid/insights?merchant_id={merchant.id}", headers=bearer(user))
        assert res.status_code == 400


class TestSimulationsApi:
    def test_create_discount_simulation(self, api: TestClient, world, db_session):
        merchant, user, _token = world
        res = api.post(
            "/api/simulations",
            json={
                "scenario_type": "discount",
                "discount_percentage": 10,
                "target_customers": 200,
                "expected_conversion": 0.1,
                "avg_order_value": 500,
                "merchant_id": str(merchant.id),
            },
            headers=bearer(user),
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["estimated_revenue"] == pytest.approx(9000.0)
        assert body["is_estimate"] is True
        assert body["confidence_low"] < body["estimated_revenue"] < body["confidence_high"]

    def test_create_campaign_simulation(self, api: TestClient, world):
        merchant, user, _token = world
        res = api.post(
            "/api/simulations",
            json={
                "scenario_type": "campaign",
                "target_customers": 100,
                "expected_conversion": 0.25,
                "avg_order_value": 400,
                "cost_per_target": 2,
                "merchant_id": str(merchant.id),
            },
            headers=bearer(user),
        )
        assert res.status_code == 201, res.text
        assert res.json()["estimated_revenue"] == pytest.approx(10000.0)

    def test_simulation_validation_error_422(self, api: TestClient, world):
        merchant, user, _token = world
        res = api.post(
            "/api/simulations",
            json={
                "scenario_type": "discount",
                "discount_percentage": 500,   # > 100 — invalid
                "target_customers": 10,
                "expected_conversion": 0.1,
                "avg_order_value": 100,
                "merchant_id": str(merchant.id),
            },
            headers=bearer(user),
        )
        assert res.status_code == 422

    def test_list_simulations_scoped(self, api: TestClient, world, db_session):
        merchant, user, _token = world
        other = Merchant(name="OM", slug=f"om-{uuid.uuid4().hex[:8]}",
                         email="om@x.com", status=MerchantStatus.active,
                         currency=Currency.INR)
        db_session.add(other); db_session.commit()
        # User from `merchant` cannot access `other`'s data — expect 403
        res = api.get(f"/api/simulations?merchant_id={other.id}", headers=bearer(user))
        assert res.status_code == 403


class TestExperimentsApi:
    def test_create_and_list_experiment(self, api: TestClient, world):
        merchant, user, _token = world
        res = api.post(
            "/api/experiments",
            json={
                "name": "VIP discount A/B",
                "hypothesis": "Discount lifts conversion",
                "control_group": {"offer": "none"},
                "treatment_group": {"offer": "10% off"},
                "target_population_size": 300,
                "merchant_id": str(merchant.id),
            },
            headers=bearer(user),
        )
        assert res.status_code == 201, res.text
        created = res.json()
        assert created["status"] == "proposed"

        listed = api.get(f"/api/experiments?merchant_id={merchant.id}", headers=bearer(user)).json()
        assert any(e["id"] == created["id"] for e in listed["experiments"])

    def test_create_experiment_requires_name(self, api: TestClient, world):
        merchant, user, _token = world
        res = api.post(
            "/api/experiments",
            json={"name": "", "merchant_id": str(merchant.id)},
            headers=bearer(user),
        )
        assert res.status_code == 422


class TestMemoryAndBriefApi:
    def test_growth_memory_empty_then_recorded_via_run(self, api: TestClient, world, db_session):
        merchant, user, _token = world
        res = api.get(f"/api/growth-memory?merchant_id={merchant.id}", headers=bearer(user))
        assert res.status_code == 200
        assert res.json()["memories"] == []

        _seed_minimal_commerce(db_session, merchant)
        api.post("/api/agents/run", json={"mode": "deep", "merchant_id": str(merchant.id)}, headers=bearer(user))
        res = api.get(f"/api/growth-memory?merchant_id={merchant.id}", headers=bearer(user))
        assert res.json()["memories"], "deep run should persist memories"

    def test_growth_brief_structure(self, api: TestClient, world, db_session):
        merchant, user, _token = world
        _seed_minimal_commerce(db_session, merchant)
        res = api.get(f"/api/growth-brief?merchant_id={merchant.id}", headers=bearer(user))
        assert res.status_code == 200
        body = res.json()
        assert body["revenue"]["current_period"] == pytest.approx(0.0)  # no current-window captures yet
        assert body["revenue"]["previous_period"] == pytest.approx(40000.0)
        assert "top_risk" in body and "recommended_action" in body

    def test_brief_unknown_merchant_403(self, api: TestClient, world):
        merchant, user, _token = world
        res = api.get(f"/api/growth-brief?merchant_id={uuid.uuid4()}", headers=bearer(user))
        # Authenticated user without membership -> 403 MERCHANT_ACCESS_DENIED
        assert res.status_code == 403, res.text
        assert res.json()["detail"] == "MERCHANT_ACCESS_DENIED"


class TestCrossMerchantSafety:
    def test_other_merchant_data_not_leaked(self, api: TestClient, world, db_session):
        merchant, user, _token = world
        other = Merchant(name="Secret", slug=f"sec-{uuid.uuid4().hex[:8]}",
                         email="sec@x.com", status=MerchantStatus.active,
                         currency=Currency.INR)
        db_session.add(other); db_session.commit()
        _seed_minimal_commerce(db_session, other)

        # query everything AS `merchant` — none of `other`'s data may appear
        radar = api.get(f"/api/radar?merchant_id={merchant.id}", headers=bearer(user)).json()
        assert all(str(s["id"]) for s in radar["signals"])
        sims = api.get(f"/api/simulations?merchant_id={merchant.id}", headers=bearer(user)).json()
        assert sims["simulations"] == []
        exps = api.get(f"/api/experiments?merchant_id={merchant.id}", headers=bearer(user)).json()
        assert exps["experiments"] == []
        mems = api.get(f"/api/growth-memory?merchant_id={merchant.id}", headers=bearer(user)).json()
        assert mems["memories"] == []
