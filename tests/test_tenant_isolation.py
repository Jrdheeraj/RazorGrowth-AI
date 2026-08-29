"""
Phase 6 security tests — cross-merchant tenant isolation (Slice 10, scenarios 9–14).

For every merchant-scoped resource family, user A (merchant A) must NEVER
reach user B's data (merchant B):

 9.  customers
 10. opportunities
 11. actions
 12. agent runs
 13. simulations
 14. experiments
"""
from __future__ import annotations

import uuid

import pytest

from backend.app.core.config import get_settings
from backend.app.core.security import create_access_token
from tests.security_utils import bearer, make_world


@pytest.fixture
def secure(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "required")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture
def two_merchants(db_session):
    """Merchant A with an owner token; Merchant B with seeded resources."""
    from backend.app.models.agent_action import AgentAction
    from backend.app.models.enums import (
        AgentActionStatus,
        AgentActionType,
        OpportunityStatus,
        OpportunityType,
    )
    from backend.app.models.customer import Customer
    from backend.app.models.experiment import Experiment, Simulation
    from backend.app.models.opportunity import GrowthOpportunity
    from decimal import Decimal

    m_a, u_a, _ = make_world(db_session, slug_hint="tena")
    m_b, u_b, _ = make_world(db_session, slug_hint="tenb")

    # Customer under each merchant.
    c_a = Customer(
        merchant_id=m_a.id,
        email="a@tenant.test", name="Customer A",
    )
    c_b = Customer(
        merchant_id=m_b.id,
        email="b@tenant.test", name="Customer B",
    )
    db_session.add_all([c_a, c_b])

    opp_b = GrowthOpportunity(
        merchant_id=m_b.id,
        opportunity_key=f"opp-b-{uuid.uuid4().hex[:8]}",
        type=OpportunityType.upsell,
        title="Tenant B opportunity",
        confidence=Decimal("0.80"),
        expected_revenue=Decimal("1000"),
        target_customer_count=5,
        reasoning=["evidence"],
        status=OpportunityStatus.pending_approval,
    )
    db_session.add(opp_b)

    action_b = AgentAction(
        id=uuid.uuid4(),
        merchant_id=m_b.id,
        action_type=AgentActionType.send_campaign,
        status=AgentActionStatus.requested,
        input_payload={"campaign_type": "email", "target": {"segment": "all"},
                       "target_count": 3},
        requested_by="seed",
    )
    db_session.add(action_b)

    sim_b = Simulation(
        merchant_id=m_b.id,
        scenario_type="discount",
        estimated_revenue=Decimal("500"),
        estimated_cost=Decimal("50"),
        estimated_profit=Decimal("450"),
        expected_conversion=Decimal("0.1"),
        assumptions={},
        is_estimate=True,
        created_by_agent="security_seed",
    )
    db_session.add(sim_b)

    exp_b = Experiment(
        merchant_id=m_b.id,
        name=f"exp-b-{uuid.uuid4().hex[:6]}",
        hypothesis="H",
        control_group="control",
        treatment_group="treatment",
        target_population_size=10,
    )
    db_session.add_all([c_a, c_b])
    db_session.commit()

    return {
        "m_a": m_a, "u_a": u_a,
        "m_b": m_b, "u_b": u_b,
        "customer_b": c_b,
        "opportunity_b": opp_b,
        "action_b": action_b,
        "simulation_b": sim_b,
        "experiment_b": exp_b,
    }


def _headers(user) -> dict[str, str]:
    return bearer(user)


class TestCrossMerchantIsolation:
    def test_customers_list_scoped(self, client, secure, db_session, two_merchants):
        w = two_merchants
        r = client.get("/api/customers", headers=_headers(w["u_a"]))
        assert r.status_code == 200
        emails = [c["email"] for c in r.json()["customers"]]
        assert "b@tenant.test" not in emails

    def test_customers_cross_tenant_query_param_rejected(
        self, client, secure, db_session, two_merchants
    ):
        w = two_merchants
        r = client.get(
            f"/api/customers?merchant_id={w['m_b'].id}", headers=_headers(w["u_a"])
        )
        assert r.status_code == 403
        assert r.json()["detail"] == "MERCHANT_ACCESS_DENIED"

    def test_opportunities_ranked_scoped(
        self, client, secure, db_session, two_merchants
    ):
        w = two_merchants
        r = client.get("/api/opportunities/ranked", headers=_headers(w["u_a"]))
        assert r.status_code == 200
        ids = [o["opportunity_id"] for o in r.json()["opportunities"]]
        assert str(w["opportunity_b"].id) not in ids

    def test_actions_single_resource_denied(
        self, client, secure, db_session, two_merchants
    ):
        w = two_merchants
        r = client.get(
            f"/api/actions/{w['action_b'].id}", headers=_headers(w["u_a"])
        )
        assert r.status_code == 403
        assert r.json()["detail"] == "MERCHANT_ACCESS_DENIED"

    def test_actions_approve_denied_across_tenants(
        self, client, secure, db_session, two_merchants
    ):
        w = two_merchants
        r = client.post(
            f"/api/actions/{w['action_b'].id}/approve", headers=_headers(w["u_a"])
        )
        assert r.status_code == 403

    def test_actions_execute_denied_across_tenants(
        self, client, secure, db_session, two_merchants
    ):
        w = two_merchants
        r = client.post(
            f"/api/actions/{w['action_b'].id}/execute", headers=_headers(w["u_a"])
        )
        assert r.status_code == 403

    def test_agent_runs_never_leak_across_tenants(
        self, client, secure, db_session, two_merchants
    ):
        from backend.app.models.enums import AgentName, AgentRunStatus
        from backend.app.models.agent_run import AgentRun
        from datetime import datetime, timezone

        w = two_merchants
        run_b = AgentRun(
            merchant_id=w["m_b"].id,
            agent_name=AgentName.growth_discovery.value,
            status=AgentRunStatus.completed,
            mode="fast",
            started_at=datetime.now(timezone.utc),
            total_latency_ms=1, llm_latency_ms=0, db_latency_ms=0,
            tool_latency_ms=0, opportunities_created=0, actions_proposed=0,
        )
        db_session.add(run_b)
        db_session.commit()

        # Listing as A never includes B's runs…
        r = client.get("/api/agents/runs", headers=_headers(w["u_a"]))
        assert r.status_code == 200
        ids = [x["id"] for x in r.json()["runs"]]
        assert str(run_b.id) not in ids
        # …and fetching B's run directly is indistinguishable from missing.
        r = client.get(f"/api/agents/runs/{run_b.id}", headers=_headers(w["u_a"]))
        assert r.status_code == 404
        assert r.json()["detail"] == "RUN_NOT_FOUND"
        # Owner of B can see it fine.
        r = client.get(f"/api/agents/runs/{run_b.id}", headers=_headers(w["u_b"]))
        assert r.status_code == 200

    def test_simulations_scoped(self, client, secure, db_session, two_merchants):
        w = two_merchants
        r = client.get("/api/simulations", headers=_headers(w["u_a"]))
        assert r.status_code == 200
        ids = [s["id"] for s in r.json()["simulations"]]
        assert str(w["simulation_b"].id) not in ids

    def test_experiments_scoped(self, client, secure, db_session, two_merchants):
        w = two_merchants
        r = client.get("/api/experiments", headers=_headers(w["u_a"]))
        assert r.status_code == 200
        names = [e["name"] for e in r.json()["experiments"]]
        assert w["experiment_b"].name not in names

    def test_customer_insight_cross_tenant_404(
        self, client, secure, db_session, two_merchants
    ):
        w = two_merchants
        r = client.get(
            f"/api/customers/{w['customer_b'].id}/insights",
            headers=_headers(w["u_a"]),
        )
        assert r.status_code in (403, 404)
        if r.status_code == 404:
            assert r.json()["detail"] == "INSIGHT_NOT_FOUND"

    def test_growth_memory_scoped(self, client, secure, db_session, two_merchants):
        from backend.app.models.agent_memory import AgentMemory

        w = two_merchants
        mem = AgentMemory(
            merchant_id=w["m_b"].id,
            memory_type="recommendation",
            content="TENANT-B-SECRET-MEMORY-MARKER",
            importance=0.9,
        )
        db_session.add(mem)
        db_session.commit()
        r = client.get("/api/growth-memory", headers=_headers(w["u_a"]))
        assert r.status_code == 200
        contents = str(r.json()["memories"])
        assert "TENANT-B-SECRET-MEMORY-MARKER" not in contents

    def test_growth_brief_scoped(self, client, secure, db_session, two_merchants):
        w = two_merchants
        r = client.get("/api/growth-brief", headers=_headers(w["u_a"]))
        assert r.status_code == 200
        assert r.json().get("merchant_id") == str(w["m_a"].id)

    def test_radar_cross_tenant_query_param_rejected(
        self, client, secure, db_session, two_merchants
    ):
        w = two_merchants
        r = client.get(
            f"/api/radar?merchant_id={w['m_b'].id}", headers=_headers(w["u_a"])
        )
        assert r.status_code == 403

    def test_ai_ingest_cross_tenant_body_param_rejected(
        self, client, secure, db_session, two_merchants
    ):
        w = two_merchants
        r = client.post(
            "/api/ai/ingest",
            json={"merchant_id": str(w["m_b"].id)},
            headers=_headers(w["u_a"]),
        )
        assert r.status_code == 403

    def test_user_without_membership_cannot_resolve_tenant(
        self, client, secure, db_session
    ):
        from tests.security_utils import make_user

        loner = make_user(db_session)
        r = client.get("/api/customers", headers=_headers(loner))
        assert r.status_code == 403
        assert r.json()["detail"] == "NO_MERCHANT_MEMBERSHIP"

    def test_multi_merchant_user_without_explicit_choice_gets_400(
        self, client, secure, db_session
    ):
        from backend.app.models.enums import UserRole
        from tests.security_utils import make_membership

        m1, u, _ = make_world(db_session, slug_hint="mul1")
        m2, _, _ = make_world(db_session, slug_hint="mul2")
        make_membership(db_session, u, m2, UserRole.operator)

        r = client.get("/api/customers", headers=_headers(u))
        assert r.status_code == 400
        assert r.json()["detail"] == "AMBIGUOUS_MERCHANT"

        # Explicit selection works for a member.
        r = client.get(
            f"/api/customers?merchant_id={m2.id}", headers=_headers(u)
        )
        assert r.status_code == 200
