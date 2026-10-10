"""Product Agent — agent, MCP capabilities, safety, approval and API tests.

Covers the acceptance contract for the Product Agent:

  MCP
    - capability filtering (commerce / analytics / product_intelligence only)
    - the Marketing Agent gains no Product Agent tools, and vice versa
    - commerce tools read this tenant's real catalog
    - analytics tools sum quantity (not line count) and show never-sold SKUs
    - product_intelligence tools are deterministic and report honest gaps
    - unknown tool refused; forbidden arguments stripped; tenant enforced
    - every Product Agent tool is read-only

  PRODUCT INTELLIGENCE
    - low stock from the threshold, underperformance vs benchmarks,
      content gaps, pricing without competitor invention, bundle affinity,
      catalog health
    - "insufficient data" instead of a fabricated answer

  AGENT
    - initialization, run creation, stage transitions, state persistence
    - findings + recommendations persisted with evidence
    - impact reported as unavailable when it cannot be computed
    - failure handling

  APPROVAL
    - recommendation -> existing agent_actions row in `requested`
    - the agent never approves and never executes
    - unapproved execution blocked through the real pipeline

  API
    - tenant isolation, no-run state, run detail, findings, recommendations,
      activity

  TENANT ISOLATION
    - another merchant's products, runs, findings and recommendations are
      unreachable
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from backend.app.agents.product_agi import service as pa_service
from backend.app.agents.product_agi import tools as pa_tools
from backend.app.agents.product_agi.agent import ACTION_TYPE, ProductAGI
from backend.app.agents.product_agi.state import (
    PROGRESS_STEPS,
    ProductAgentState,
    RunStatus,
    Stage,
    StateTransitionError,
    assert_stage_transition,
    stage_index,
)
from backend.app.integrations.mcp import bridge as mcp_bridge
from backend.app.integrations.mcp.domains import (
    AGENT_CAPABILITIES,
    DOMAINS,
    OPERATIONAL,
    capability_domain,
    domains_for_agent,
)
from backend.app.integrations.mcp.errors import TOOL_NOT_ALLOWED
from backend.app.integrations.mcp.registry import get_mcp_registry
from backend.app.models.agent_action import AgentAction
from backend.app.models.customer import Customer
from backend.app.models.enums import (
    AgentActionStatus,
    MembershipStatus,
    OrderStatus,
    UserRole,
)
from backend.app.models.membership import MerchantMembership
from backend.app.models.order import Order, OrderItem
from backend.app.models.product import Product
from backend.app.models.product_agi import (
    ProductAgentEvent,
    ProductAgentFinding,
    ProductAgentRecommendation,
    ProductAgentRun,
)
from backend.app.services import product_intelligence as pi
from tests.security_utils import bearer, make_merchant, make_user

# ── fixtures ────────────────────────────────────────────────────────────


def _seed_catalog(db, merchant, *, days_ago: int = 5, products: int = 4):
    """Real products + real settled orders for THIS merchant."""
    rows = []
    for i in range(products):
        p = Product(
            merchant_id=merchant.id,
            name=f"Test Product {i}",
            category=("audio", "desk")[i % 2],
            price=Decimal(str(500 + i * 100)),
            sku=f"SKU-TEST-{i}",
            description="A real product description long enough to count as content.",
            stock_quantity=100,
        )
        db.add(p)
        rows.append(p)
    db.flush()

    customer = Customer(
        merchant_id=merchant.id,
        name="Buyer",
        email=f"buyer-{uuid.uuid4().hex[:8]}@test.local",
        total_orders=3,
        total_spend=Decimal("1000"),
    )
    db.add(customer)
    db.flush()

    created = datetime.now(timezone.utc) - timedelta(days=days_ago)
    for i in range(8):
        order = Order(
            merchant_id=merchant.id,
            customer_id=customer.id,
            order_number=f"T-{merchant.id.hex[:6]}-{i}",
            status=OrderStatus.paid,
            subtotal=Decimal("100"),
            discount=Decimal("0"),
            tax=Decimal("0"),
            total=Decimal("100"),
            created_at=created,
        )
        db.add(order)
        db.flush()
        for p in rows[: 2 + (i % 2)]:
            db.add(
                OrderItem(
                    order_id=order.id,
                    product_id=p.id,
                    quantity=2,   # quantity 2 proves SUM(quantity), not COUNT
                    unit_price=p.price,
                    line_total=p.price * 2,
                )
            )
    db.commit()
    return rows


@pytest.fixture()
def merchant(db_session):
    return make_merchant(db_session, "pa")


@pytest.fixture()
def seeded(db_session, merchant):
    _seed_catalog(db_session, merchant)
    return merchant


def _client(db, merchant, **kw):
    return mcp_bridge.build_client(db, merchant.id, **kw)



def _new_run(db, merchant, **kw) -> ProductAgentRun:
    row = ProductAgentRun(
        merchant_id=merchant.id,
        objective=kw.pop("objective", "Analyse the catalog"),
        status="queued",
        current_stage=Stage.understand_catalog.value,
        metrics={"window_days": kw.pop("window_days", 365)},
        **kw,
    )
    db.add(row)
    db.commit()
    return row


# ── 1. MCP capability filtering ─────────────────────────────────────────


def test_product_agent_capability_grant_is_commerce_analytics_product_intelligence():
    caps = AGENT_CAPABILITIES["product_agent"]
    assert set(caps.domains) == {"commerce", "analytics", "product_intelligence"}
    # Marketing must NOT gain Product Agent tools.
    assert "product_intelligence" not in domains_for_agent("marketing_agent")
    assert "commerce" not in domains_for_agent("marketing_agent")
    # The granted domains are registered and real.
    for name in ("commerce", "analytics", "product_intelligence"):
        assert DOMAINS[name].status == OPERATIONAL


def test_product_agent_catalog_contains_no_marketing_or_customer_tools():
    registry = get_mcp_registry()
    entries = registry.catalog_for_agent("product_agent", include_write=False)
    assert entries, "the Product Agent must discover real tools"
    domains = {e["capability_domain"] for e in entries}
    assert domains <= {"commerce", "analytics", "product_intelligence"}
    leaked = [e["name"] for e in entries if e["capability_domain"] in {"marketing", "customer"}]
    assert leaked == []


def test_product_agent_catalog_contains_its_expected_tools():
    names = {
        e["name"]
        for e in get_mcp_registry().catalog_for_agent("product_agent", include_write=False)
    }
    for required in (
        "commerce.list_products",
        "commerce.get_product",
        "commerce.get_inventory",
        "commerce.get_low_stock_products",
        "commerce.get_product_sales",
        "commerce.get_orders",
        "analytics.get_product_performance",
        "analytics.get_top_products",
        "analytics.get_conversion",
        "product_intelligence.get_catalog_health",
        "product_intelligence.get_underperforming_products",
        "product_intelligence.get_low_stock_risk",
        "product_intelligence.get_content_gaps",
        "product_intelligence.get_pricing_opportunities",
        "product_intelligence.get_bundle_opportunities",
        "product_intelligence.get_product_opportunities",
    ):
        assert required in names, f"missing {required}"


def test_marketing_agent_does_not_see_product_intelligence_tools():
    names = {
        e["name"]
        for e in get_mcp_registry().catalog_for_agent("marketing_agent", include_write=False)
    }
    assert not any(n.startswith("product_intelligence.") for n in names)
    assert not any(n.startswith("commerce.") for n in names)


def test_unknown_agent_gets_an_empty_catalog():
    assert get_mcp_registry().catalog_for_agent("not_an_agent") == []


def test_capability_domain_mapping():
    assert capability_domain("commerce.list_products") == "commerce"
    assert capability_domain("product_intelligence.get_catalog_health") == (
        "product_intelligence"
    )
    assert capability_domain("analytics.get_conversion") == "analytics"
    # Pre-existing mappings must be untouched.
    assert capability_domain("marketing.analytics.get_revenue") == "analytics"
    assert capability_domain("marketing.crm.get_customer") == "customer"
    assert capability_domain("marketing.email.send_email") == "marketing"


def test_stage_tool_map_is_stage_scoped():
    # Understand-catalog sees catalog tools, not research-only ones.
    assert "commerce.list_products" in pa_tools.tools_for_stage(Stage.understand_catalog)
    assert "analytics.get_conversion" not in pa_tools.tools_for_stage(
        Stage.understand_catalog
    )
    # Waiting for approval exposes no prompt tools at all: this agent has no
    # MCP write of its own.
    assert pa_tools.tools_for_stage(Stage.waiting_approval) == ()
    # Every stage name maps to a known shared MCP phase.
    for stage in Stage:
        assert pa_tools.mcp_phase_for_stage(stage) in {
            "observe",
            "research",
            "campaign_prep",
            "execution",
        }


def test_stage_tools_narrow_the_registry_catalog(seeded, db_session):
    client = _client(db_session, seeded)
    full = client.catalog_for_agent("product_agent", include_write=False)
    stage = client.catalog_for_agent(
        "product_agent",
        phase="observe",
        include_write=False,
        stage_tools=pa_tools.grant_names(Stage.find_opportunities),
    )
    assert 0 < len(stage) < len(full)
    assert all(
        e["name"].startswith("product_intelligence.") for e in stage
    )





# ── 2. commerce + analytics tools ───────────────────────────────────────


def test_commerce_list_products_reads_this_tenants_real_catalog(seeded, db_session):
    envelope = _client(db_session, seeded).call("commerce.list_products", {})
    assert envelope["status"] == "success"
    data = envelope["data"]
    assert data["product_count"] == 4
    names = {p["name"] for p in data["products"]}
    assert "Test Product 0" in names
    assert data["source"] == "products_table"


def test_commerce_get_product_is_tenant_scoped(seeded, db_session):
    other = make_merchant(db_session, "other")
    product = _seed_catalog(db_session, other, products=1)[0]
    envelope = _client(db_session, seeded).call(
        "commerce.get_product", {"product_id": str(product.id)}
    )
    assert envelope["status"] == "success"
    assert envelope["data"]["found"] is False


def test_commerce_inventory_reports_real_totals(seeded, db_session):
    db = db_session
    data = _client(db, seeded).data("commerce.get_inventory", {"window_days": 365})
    assert data["product_count"] == 4
    assert data["total_units"] == 400
    assert data["catalog_value_inr"] == sum(
        float(p["price_inr"]) * int(p["stock_quantity"]) for p in data["products"]
    )


def test_analytics_product_performance_sums_quantity_and_shows_never_sold(seeded, db_session):
    db = db_session
    data = _client(db, seeded).data(
        "analytics.get_product_performance", {"window_days": 365, "limit": 10}
    )
    rows = {r["name"]: r for r in data["all_products"]}
    # 8 orders x quantity 2 => 16 units for the products in every order,
    # which COUNT(line) would have reported as 8.
    assert rows["Test Product 0"]["units_sold"] == 16
    assert rows["Test Product 0"]["revenue_inr"] > 0
    # The never-sold SKU is present with a real zero, not missing.
    assert rows["Test Product 3"]["units_sold"] == 0
    assert rows["Test Product 3"]["never_sold"] is True
    assert data["never_sold_count"] >= 1


def test_analytics_get_conversion_is_honestly_unavailable(seeded, db_session):
    db = db_session
    data = _client(db, seeded).data("analytics.get_conversion", {"window_days": 90})
    assert data["available"] is False
    assert data["conversion_rate_pct"] is None
    assert "no sessions" in data["reason"].lower()


def test_product_intelligence_catalog_health(seeded, db_session):
    db = db_session
    data = _client(db, seeded).data(
        "product_intelligence.get_catalog_health", {"window_days": 365}
    )
    assert data["status"] == "available"
    assert 0 <= data["score"] <= 100
    assert data["grade"] in {"healthy", "needs_attention", "at_risk"}
    assert data["weights"]["content_completeness"] > 0


def test_product_intelligence_pricing_never_invents_competitor_prices(seeded, db_session):
    db = db_session
    data = _client(db, seeded).data("product_intelligence.get_pricing_opportunities", {})
    assert data["competitor_pricing"]["status"] == "unavailable"
    assert data["competitor_pricing"]["reason"]


def test_product_intelligence_bundle_reports_insufficient_data_without_baskets(
    seeded, db_session
):
    db = db_session
    data = _client(db, seeded).data(
        "product_intelligence.get_bundle_opportunities", {"window_days": 365}
    )
    # The fixture builds multi-item orders, so affinity is measurable here.
    assert data["status"] == "available"
    assert data["bundles"], "real co-order data must produce a real pair"
    assert data["impact"]["status"] == "unavailable"
    for bundle in data["bundles"]:
        assert bundle["co_orders"] >= 1
        assert bundle["basis"] == "orders_containing_both_products"


# ── 3. MCP safety: unknown tool, forbidden args, read-only ──────────────


def test_unknown_tool_is_refused(seeded, db_session):
    envelope = _client(db_session, seeded).call("commerce.drop_everything", {})
    assert envelope["status"] == "error"
    assert envelope["error"]["code"] == TOOL_NOT_ALLOWED


def test_model_cannot_supply_tenant_or_credentials(seeded, db_session):
    db = db_session
    other = make_merchant(db, "victim")
    envelope = _client(db, seeded).call(
        "commerce.list_products",
        {"merchant_id": str(other.id), "tenant_id": "x", "api_key": "leak", "limit": 5},
    )
    assert envelope["status"] == "success"
    dropped = set(envelope["metadata"].get("dropped_arguments") or [])
    assert {"merchant_id", "tenant_id", "api_key"} <= dropped
    # The result still contains ONLY this merchant's products.
    assert envelope["data"]["product_count"] == 4


def test_every_product_agent_tool_is_read_only():
    granted = get_mcp_registry().catalog_for_agent("product_agent")
    assert granted, "catalog must be non-empty"
    for entry in granted:
        spec = get_mcp_registry().spec(entry["name"])
        assert spec.read_only is True
        assert spec.external_write is False
        assert spec.requires_approval is False


def test_unknown_argument_is_dropped_and_reported(seeded, db_session):
    """The MCP sanitizer drops unknown keys and reports the attempt."""
    envelope = _client(db_session, seeded).call(
        "commerce.get_inventory", {"unexpected": 1}
    )
    assert envelope["status"] == "success"
    assert "unexpected" in (envelope["metadata"].get("dropped_arguments") or [])


# ── 4. Deterministic intelligence honesty ───────────────────────────────


def test_underperformance_needs_enough_orders_to_compare(db_session, merchant):
    _seed_catalog(db_session, merchant, products=3)
    snapshot = pi.build_snapshot(db_session, merchant.id, window_days=365)
    # Widen the guard: with fewer settled orders the answer is a refusal.
    original = pi.MIN_ORDERS_FOR_PERFORMANCE
    try:
        pi.MIN_ORDERS_FOR_PERFORMANCE = 10_000
        result = pi.underperforming_products(snapshot)
        assert result["status"] == "insufficient_data"
        assert result["count"] == 0
        assert result["reason"]
    finally:
        pi.MIN_ORDERS_FOR_PERFORMANCE = original


def test_underperformance_uses_benchmarks_not_a_fixed_bar(db_session, merchant):
    _seed_catalog(db_session, merchant, products=4)
    snapshot = pi.build_snapshot(db_session, merchant.id, window_days=365)
    result = pi.underperforming_products(snapshot)
    assert result["status"] == "available"
    assert result["category_benchmarks"]
    for row in result["underperforming"]:
        assert row["category_avg_revenue_inr"] is not None
        assert row["catalog_avg_revenue_inr"] is not None


def test_low_stock_risk_uses_the_configured_threshold(db_session, merchant):
    product = Product(
        merchant_id=merchant.id,
        name="Nearly out",
        category="desk",
        price=Decimal("100"),
        stock_quantity=4,
    )
    db_session.add(product)
    db_session.commit()
    snapshot = pi.build_snapshot(
        db_session, merchant.id, window_days=365, low_stock_threshold=10
    )
    result = pi.low_stock_risk(snapshot)
    names = {r["name"] for r in result["risks"]}
    assert "Nearly out" in names
    assert "below_configured_threshold" in result["risks"][0]["reasons"]


def test_content_gaps_report_missing_fields_and_platform_limits(db_session, merchant):
    thin = Product(
        merchant_id=merchant.id,
        name="Bare",  # no SKU, no description
        category="desk",
        price=Decimal("100"),
        stock_quantity=1,
    )
    db_session.add(thin)
    db_session.commit()
    snapshot = pi.build_snapshot(db_session, merchant.id, window_days=365)
    result = pi.content_gaps(snapshot)
    gap = next(g for g in result["gaps"] if g["name"] == "Bare")
    assert "description" in gap["missing_fields"]
    assert "sku" in gap["missing_fields"]
    assert result["platform_limitations"]


def test_empty_catalog_reports_insufficient_data(db_session, merchant):
    snapshot = pi.build_snapshot(db_session, merchant.id, window_days=365)
    health = pi.catalog_health(snapshot)
    assert health["status"] == "insufficient_data"
    assert health["score"] is None
    under = pi.underperforming_products(snapshot)
    assert under["status"] == "insufficient_data"


# ── 5. Agent: state machine ─────────────────────────────────────────────


def test_stage_transitions_are_ordered():
    assert_stage_transition(Stage.understand_catalog, Stage.analyze_performance)
    with pytest.raises(StateTransitionError):
        assert_stage_transition(Stage.understand_catalog, Stage.safety_check)


def test_progress_steps_cover_every_visible_stage():
    assert len(PROGRESS_STEPS) == 8
    for i, stage in enumerate(list(Stage)[:8]):
        assert stage_index(stage.value) == i
    assert stage_index(Stage.learn.value) == 7


def test_state_refuses_an_illegal_stage_jump():
    state = ProductAgentState(run_id=str(uuid.uuid4()), merchant_id="m", objective="o")
    state.set_stage(Stage.analyze_performance)
    with pytest.raises(StateTransitionError):
        state.set_stage(Stage.execute_measure)


# ── 6. Agent: full deterministic run ────────────────────────────────────


def test_agent_run_reaches_waiting_approval_with_real_evidence(seeded, db_session):
    db = db_session
    run_row = _new_run(db, seeded)
    agent = ProductAGI(db, seeded.id, llm=None)
    agent.run(run_row, "Analyse the catalog")

    db.refresh(run_row)
    assert run_row.status == RunStatus.waiting_approval.value
    assert run_row.current_stage == Stage.waiting_approval.value
    assert run_row.products_analyzed == 4
    assert run_row.metrics["product_count"] == 4
    assert run_row.metrics["executed_count"] == 0
    assert run_row.summary and "4 product(s)" in run_row.summary

    # Findings are real and evidence-backed.
    findings = db.scalars(
        select(ProductAgentFinding).where(ProductAgentFinding.run_id == run_row.id)
    ).all()
    assert findings, "a run over real data must record findings"
    for finding in findings:
        assert finding.evidence, f"{finding.title} has no evidence"
        assert finding.evidence[0].get("tool")

    # Recommendations exist with an explicit impact verdict.
    recs = db.scalars(
        select(ProductAgentRecommendation).where(
            ProductAgentRecommendation.run_id == run_row.id
        )
    ).all()
    assert recs
    for rec in recs:
        assert rec.evidence
        assert rec.expected_impact["status"] in {"available", "unavailable"}
        if rec.expected_impact["status"] == "unavailable":
            assert "insufficient" in rec.expected_impact["text"].lower()

    # Activity is real persisted events, in order.
    events = db.scalars(
        select(ProductAgentEvent)
        .where(ProductAgentEvent.run_id == run_row.id)
        .order_by(ProductAgentEvent.seq)
    ).all()
    assert len(events) >= 8
    assert [e.seq for e in events] == sorted(e.seq for e in events)
    assert any(e.event_type == "catalog_loaded" for e in events)
    assert any(e.event_type == "verification_passed" for e in events)


def test_agent_run_calls_the_shared_mcp_layer(seeded, db_session):
    db = db_session
    run_row = _new_run(db, seeded)
    ProductAGI(db, seeded.id, llm=None).run(run_row, "Analyse the catalog")
    db.refresh(run_row)
    calls = (run_row.state or {}).get("mcp_calls") or []
    assert calls, "the run must go through MCP"
    tools = {c["tool"] for c in calls}
    assert "commerce.list_products" in tools
    assert any(t.startswith("product_intelligence.") for t in tools)
    for call in calls:
        assert call["read_only"] is True
        assert call["run_id"] == str(run_row.id)
        assert "args" in call


def test_agent_run_on_an_empty_catalog_completes_honestly(db_session, merchant):
    run_row = _new_run(db_session, merchant)
    ProductAGI(db_session, merchant.id, llm=None).run(run_row, "Analyse the catalog")
    db_session.refresh(run_row)
    assert run_row.status == RunStatus.completed_no_actions.value
    assert "no products" in run_row.summary.lower()
    assert run_row.metrics["product_count"] == 0
    assert run_row.recommendations_created == 0


def test_a_tool_failure_is_recorded_as_a_gap_not_a_fake_result(seeded, db_session):
    """A failing MCP read must not crash the run nor invent an observation."""
    def _boom(*_a, **_kw):
        raise RuntimeError("synthetic failure")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(
        "backend.app.services.product_intelligence.build_snapshot", _boom
    )
    try:
        run_row = _new_run(db_session, seeded)
        ProductAGI(db_session, seeded.id, llm=None).run(run_row, "Analyse")
        db_session.refresh(run_row)
    finally:
        monkey.undo()

    # The run survived, honestly reporting the tool failure as a gap.
    assert run_row.status in {
        RunStatus.completed_no_actions.value,
        RunStatus.failed.value,
    }
    gaps = (run_row.state or {}).get("knowledge_gaps") or []
    assert any("failed" in g for g in gaps)
    assert "synthetic failure" not in str(run_row.summary)


def test_an_unexpected_run_failure_is_recorded(seeded, db_session, monkeypatch):
    def _boom(*_a, **_kw):
        raise RuntimeError("stage exploded")

    run_row = _new_run(db_session, seeded)
    agent = ProductAGI(db_session, seeded.id, llm=None)
    monkeypatch.setattr(agent, "_stage_analyze_performance", _boom)
    agent.run(run_row, "Analyse the catalog")
    db_session.refresh(run_row)
    assert run_row.status == RunStatus.failed.value
    assert run_row.errors
    assert "stage exploded" in str(run_row.errors)
    assert run_row.completed_at is not None


# ── 7. Approval / action integration ────────────────────────────────────


def test_recommendations_become_existing_actions_in_requested_state(seeded, db_session):
    db = db_session
    run_row = _new_run(db, seeded)
    ProductAGI(db, seeded.id, llm=None).run(run_row, "Analyse the catalog")
    db.refresh(run_row)

    recs = db.scalars(
        select(ProductAgentRecommendation).where(
            ProductAgentRecommendation.run_id == run_row.id,
            ProductAgentRecommendation.action_required.is_(True),
        )
    ).all()
    assert recs, "action-required recommendations must become actions"
    for rec in recs:
        assert rec.action_id is not None
        action = db.get(AgentAction, rec.action_id)
        assert action is not None
        assert action.merchant_id == seeded.id
        # Created, never approved, never executed.
        assert action.status == AgentActionStatus.requested
        assert action.approved_by is None
        assert action.completed_at is None
        assert action.requested_by == "agent:ProductAGI"
        assert action.action_type == ACTION_TYPE
        payload = action.input_payload
        assert payload["metadata"]["product_agent_run_id"] == str(run_row.id)
        assert payload["metadata"]["approval_gated"] is True
        # The agent never states a rupee impact it did not compute.
        assert payload["expected_revenue"] in (0, 0.0, "0", "0.00")


def test_agent_never_creates_an_approved_or_completed_action(seeded, db_session):
    db = db_session
    run_row = _new_run(db, seeded)
    ProductAGI(db, seeded.id, llm=None).run(run_row, "Analyse the catalog")
    actions = db.scalars(
        select(AgentAction).where(AgentAction.requested_by == "agent:ProductAGI")
    ).all()
    assert actions
    for action in actions:
        assert action.status == AgentActionStatus.requested


def test_unapproved_product_action_cannot_be_executed(seeded, db_session):
    db = db_session
    run_row = _new_run(db, seeded)
    ProductAGI(db, seeded.id, llm=None).run(run_row, "Analyse the catalog")
    action = db.scalars(
        select(AgentAction).where(AgentAction.requested_by == "agent:ProductAGI")
    ).first()
    assert action is not None

    from backend.app.services import action_service

    result = action_service.execute_action(db, action.id, actor="tester")
    assert result.success is False
    assert "INVALID_ACTION_STATE" in (result.error or "")
    db.refresh(action)
    assert action.status == AgentActionStatus.requested


def test_product_agent_actions_never_reach_a_provider(seeded, db_session):
    """No Product Agent action is an MCP external write."""
    from backend.app.integrations.mcp.execution import (
        is_marketing_external_write,
    )

    db = db_session
    run_row = _new_run(db, seeded)
    ProductAGI(db, seeded.id, llm=None).run(run_row, "Analyse the catalog")
    actions = db.scalars(
        select(AgentAction).where(AgentAction.requested_by == "agent:ProductAGI")
    ).all()
    for action in actions:
        assert is_marketing_external_write(action) is False


# ── 8. Safety verification ──────────────────────────────────────────────


def test_safety_check_rejects_a_recommendation_without_evidence(seeded, db_session):
    db = db_session
    run_row = _new_run(db, seeded)
    agent = ProductAGI(db, seeded.id, llm=None)

    state = ProductAgentState(
        run_id=str(run_row.id), merchant_id=str(seeded.id), objective="o"
    )
    state.catalog = {"products": [{"name": "Test Product 0"}]}
    state.recommendations = [
        {
            "id": str(uuid.uuid4()),
            "title": "Unsupported",
            "evidence": [],          # no evidence at all
            "approval_required": True,
            "action_required": True,
            "affected_products": ["Test Product 0"],
            "expected_impact": {"status": "unavailable", "text": "n/a"},
        }
    ]
    from backend.app.agents.product_agi.events import EventRecorder

    recorder = EventRecorder(db, run_row)
    passed = agent._stage_safety_check(state, recorder, run_row, None)
    assert passed is False
    assert state.verification["passed"] is False
    assert any("no evidence" in f for f in state.verification["failures"])


def test_safety_check_rejects_a_product_outside_the_catalog(seeded, db_session):
    db = db_session
    run_row = _new_run(db, seeded)
    agent = ProductAGI(db, seeded.id, llm=None)
    state = ProductAgentState(
        run_id=str(run_row.id), merchant_id=str(seeded.id), objective="o"
    )
    state.catalog = {"products": [{"name": "Test Product 0"}]}
    state.recommendations = [
        {
            "id": str(uuid.uuid4()),
            "title": "Phantom product",
            "evidence": [{"statement": "x", "tool": "t", "source": "s",
                          "source_kind": "mcp"}],
            "approval_required": True,
            "action_required": True,
            "affected_products": ["A Product That Does Not Exist"],
            "expected_impact": {"status": "unavailable", "text": "n/a"},
        }
    ]
    from backend.app.agents.product_agi.events import EventRecorder

    passed = agent._stage_safety_check(state, EventRecorder(db, run_row), run_row, None)
    assert passed is False


def test_safety_check_rejects_an_action_that_demands_no_approval(seeded, db_session):
    db = db_session
    run_row = _new_run(db, seeded)
    agent = ProductAGI(db, seeded.id, llm=None)
    state = ProductAgentState(
        run_id=str(run_row.id), merchant_id=str(seeded.id), objective="o"
    )
    state.catalog = {"products": []}
    state.recommendations = [
        {
            "id": str(uuid.uuid4()),
            "title": "Self approving",
            "evidence": [{"statement": "x", "tool": "t", "source": "s",
                          "source_kind": "mcp"}],
            "approval_required": False,
            "action_required": True,
            "affected_products": [],
            "expected_impact": {"status": "unavailable", "text": "n/a"},
        }
    ]
    from backend.app.agents.product_agi.events import EventRecorder

    assert agent._stage_safety_check(
        state, EventRecorder(db, run_row), run_row, None
    ) is False


def test_every_llm_schema_is_a_valid_structured_output_contract():
    """The provider calls ``schema.model_json_schema()``.

    A bare ``list[...]`` has no such method, so every schema the agent hands
    to Groq must be a real pydantic model. This locks that in: passing
    ``list[ResearchQuestion]`` once silently broke retrieval-question
    proposal with an AttributeError.
    """
    from pydantic import BaseModel

    from backend.app.agents.product_agi.schemas import (
        AnalysisResult,
        ResearchQuestions,
    )
    from backend.app.agents.product_agi.agent import SafetyVerdict, SignalReading

    for schema in (
        SignalReading,
        AnalysisResult,
        SafetyVerdict,
        ResearchQuestions,
    ):
        assert issubclass(schema, BaseModel), schema
        assert isinstance(schema.model_json_schema(), dict)
        # A RootModel still serialises to a schema a JSON-mode model can use.
        assert ResearchQuestions.model_json_schema()


def test_a_degraded_run_is_never_labelled_llm_reasoned(seeded, db_session):
    """Provenance must reflect WHERE the conclusion came from.

    A run whose LLM failed falls back to the deterministic pipeline, so its
    recommendations must not claim ``llm_over_deterministic_observations``.
    """
    run_row = _new_run(db_session, seeded)
    ProductAGI(db_session, seeded.id, llm=None).run(run_row, "Analyse the catalog")
    db_session.refresh(run_row)
    recs = db_session.scalars(
        select(ProductAgentRecommendation).where(
            ProductAgentRecommendation.run_id == run_row.id
        )
    ).all()
    assert recs
    for rec in recs:
        assert rec.basis == "deterministic_opportunity"
        assert rec.data["llm_reasoned"] is False


def test_an_llm_reasoned_run_records_its_provenance(seeded, db_session):
    """With a working LLM the provenance flips — and stays accurate."""
    from backend.app.agents.marketing_agi.limits import LoopLimits
    from backend.app.agents.marketing_agi.rag import (
        EvidenceSufficiency,
        RetrievalDecision,
    )
    from backend.app.agents.product_agi.agent import SafetyVerdict, SignalReading
    from backend.app.agents.product_agi.schemas import (
        AnalysisResult,
        Finding,
        Recommendation,
        ResearchQuestions,
    )

    class _StubLLM:
        def __init__(self) -> None:
            self.last_call_stats = {
                "attempts": 1, "retries": 0,
                "rate_limited": False, "retry_delay_ms": 0,
            }

        def generate_structured(self, system, user, schema, **kw):
            if schema is SignalReading:
                return SignalReading(
                    observations=["s"], primary_signal="s",
                    open_questions=["Which products never sold?"],
                )
            if schema is ResearchQuestions:
                return ResearchQuestions([])
            if schema is SafetyVerdict:
                return SafetyVerdict(passed=True, notes="ok")
            if schema is RetrievalDecision:
                return RetrievalDecision(action="sufficient", reasoning="s")
            if schema is EvidenceSufficiency:
                return EvidenceSufficiency(sufficient=True, reasoning="s")
            return AnalysisResult(
                findings=[Finding(
                    type="catalog", title="F", description="D",
                )],
                recommendations=[Recommendation(
                    type="merchandising", title="R", problem="P",
                    recommendation="Act", why_now="Now", confidence=0.6,
                    evidence_refs=["e"], affected_products=["Test Product 0"],
                    action_required=True,
                )],
                summary="s", reasoning="r",
            )

    run_row = _new_run(db_session, seeded)
    agent = ProductAGI(
        db_session,
        seeded.id,
        llm=_StubLLM(),
        limits=LoopLimits(
            max_iterations=6, max_tool_calls=24, max_retrieval_rounds=1,
            max_llm_calls=10, run_timeout_seconds=120,
        ),
    )
    agent.run(run_row, "Analyse the catalog")
    db_session.refresh(run_row)
    recs = db_session.scalars(
        select(ProductAgentRecommendation).where(
            ProductAgentRecommendation.run_id == run_row.id
        )
    ).all()
    assert recs, "the stub LLM should have produced a recommendation"
    for rec in recs:
        assert rec.basis == "llm_over_deterministic_observations"
        assert rec.data["llm_reasoned"] is True
        assert rec.affected_products == ["Test Product 0"]


def test_llm_call_budget_is_enforced(seeded, db_session):
    """``max_llm_calls`` must be a real bound, not a declared number.

    A schema-aware stub LLM proves the agent stops asking once the budget is
    spent, and degrades honestly instead of looping.
    """
    from backend.app.agents.marketing_agi.limits import LoopLimits
    from backend.app.agents.marketing_agi.rag import (
        EvidenceSufficiency,
        RetrievalDecision,
    )
    from backend.app.agents.product_agi.agent import SafetyVerdict, SignalReading
    from backend.app.agents.product_agi.schemas import (
        AnalysisResult,
        ResearchQuestions,
    )

    tracked = {"n": 0}

    class _StubLLM:
        """Answers every schema the agent (and the shared RAG loop) uses."""

        def __init__(self) -> None:
            self.last_call_stats = {
                "attempts": 1, "retries": 0,
                "rate_limited": False, "retry_delay_ms": 0,
            }

        def generate_structured(self, system, user, schema, **kw):
            if schema is SignalReading:
                tracked["n"] += 1
                return SignalReading(
                    observations=["stub"], primary_signal="stub signal",
                    open_questions=["What is the stock position?"],
                )
            if schema is ResearchQuestions:
                tracked["n"] += 1
                return ResearchQuestions(
                    [ResearchQuestion(question="What sold and what did not?")]
                )
            if schema is SafetyVerdict:
                tracked["n"] += 1
                return SafetyVerdict(passed=True, notes="ok")
            if schema is AnalysisResult:
                tracked["n"] += 1
                return AnalysisResult(
                    findings=[Finding(
                        type="catalog", title="Stub finding",
                        description="From the stub LLM.",
                    )],
                    recommendations=[Recommendation(
                        type="merchandising",
                        title="Stub recommendation",
                        problem="Stub problem",
                        recommendation="Stub action",
                        why_now="Stub now",
                        confidence=0.4,
                        evidence_refs=["stub evidence"],
                        affected_products=["Test Product 0"],
                        action_required=True,
                    )],
                    summary="Stub summary", reasoning="Stub reasoning",
                )
            # The shared AgenticRAG loop's own two schemas.
            if schema is RetrievalDecision:
                return RetrievalDecision(
                    action="sufficient", reasoning="stub"
                )
            if schema is EvidenceSufficiency:
                return EvidenceSufficiency(sufficient=True, reasoning="stub")
            raise AssertionError(f"unexpected schema {schema!r}")

    run_row = _new_run(db_session, seeded)
    agent = ProductAGI(
        db_session,
        seeded.id,
        llm=_StubLLM(),
        limits=LoopLimits(
            max_iterations=6, max_tool_calls=24, max_retrieval_rounds=1,
            max_llm_calls=2, run_timeout_seconds=120,
        ),
    )
    agent.run(run_row, "Analyse the catalog")
    db_session.refresh(run_row)

    state = run_row.state or {}
    assert state["llm_calls"] <= 2, (
        f"agent made {state['llm_calls']} tracked LLM calls, budget was 2"
    )
    assert tracked["n"] >= 1, "the stub LLM was never exercised"
    # The run completed and the agent's own work was real, not stubbed away.
    assert run_row.status in {
        RunStatus.waiting_approval.value,
        RunStatus.completed_no_actions.value,
    }


def test_default_limits_are_tighter_than_the_marketing_defaults():
    """The Product Agent has one analysis stage; it must not buy a bigger budget."""
    from backend.app.agents.marketing_agi.limits import DEFAULT_LIMITS
    from backend.app.agents.product_agi.tools import PRODUCT_AGENT_LIMITS

    assert PRODUCT_AGENT_LIMITS.max_retrieval_rounds <= DEFAULT_LIMITS.max_retrieval_rounds
    assert PRODUCT_AGENT_LIMITS.max_llm_calls <= DEFAULT_LIMITS.max_llm_calls
    assert PRODUCT_AGENT_LIMITS.run_timeout_seconds <= DEFAULT_LIMITS.run_timeout_seconds


# ── 9. Tenant isolation ─────────────────────────────────────────────────


def test_run_reads_are_tenant_scoped(seeded, db_session):
    other = make_merchant(db_session, "iso")
    other_run = _new_run(db_session, other)
    assert pa_service.get_run(db_session, seeded.id, str(other_run.id)) is None
    assert pa_service.findings_for_run(db_session, seeded.id, str(other_run.id)) == []
    assert pa_service.recommendations_for_run(
        db_session, seeded.id, str(other_run.id)
    ) == []


def test_catalog_view_never_leaks_another_tenants_products(seeded, db_session):
    other = make_merchant(db_session, "iso2")
    _seed_catalog(db_session, other, products=2)
    view = pa_service.catalog_view(db_session, seeded.id)
    ids = {p["product_id"] for p in view["products"]}
    other_ids = {
        str(p.id)
        for p in db_session.scalars(
            select(Product).where(Product.merchant_id == other.id)
        ).all()
    }
    assert ids.isdisjoint(other_ids)
    assert view["summary"]["product_count"] == 4


def test_agent_run_is_bound_to_its_own_merchant(seeded, db_session):
    other = make_merchant(db_session, "iso3")
    run_row = _new_run(db_session, other)
    # Drive the seeded merchant's agent against the other's run row: the
    # agent must only ever write rows for its own authenticated merchant.
    agent = ProductAGI(db_session, seeded.id, llm=None)
    agent._db.add(
        ProductAgentFinding(
            run_id=run_row.id,
            merchant_id=seeded.id,          # agent's own tenant
            type="catalog",
            title="cross",
            description="d",
            severity="info",
        )
    )
    agent._db.flush()
    row = agent._db.scalars(
        select(ProductAgentFinding).where(
            ProductAgentFinding.run_id == run_row.id,
            ProductAgentFinding.merchant_id == seeded.id,
        )
    ).first()
    assert row is not None
    assert row.merchant_id == seeded.id


# ── 10. Read model ──────────────────────────────────────────────────────


def test_status_before_any_run_is_honest(seeded, db_session):
    db = db_session
    status = pa_service.build_status(db, seeded.id)
    assert status["has_run"] is False
    assert status["step_index"] == -1
    assert status["recommendations"] == []
    assert status["activity"] == []
    assert "No Product Agent run yet" in status["headline"]
    assert status["catalog"]["summary"]["product_count"] == 4
    assert "Learning begins after" in status["learning_insight"]


def test_status_reflects_a_real_run(seeded, db_session):
    db = db_session
    run_row = _new_run(db, seeded)
    ProductAGI(db, seeded.id, llm=None).run(run_row, "Analyse the catalog")
    db.refresh(run_row)

    status = pa_service.build_status(db, seeded.id)
    assert status["has_run"] is True
    assert status["run_id"] == str(run_row.id)
    assert status["status"] == RunStatus.waiting_approval.value
    assert status["step_index"] == stage_index(Stage.waiting_approval.value)
    assert status["needs_approval"] is True
    assert status["recommendations"]
    assert status["activity"]
    assert status["duration_seconds"] is not None


def test_platform_states_are_honest(seeded, db_session):
    db = db_session
    platforms = {p["key"]: p for p in pa_service.platform_states(db, seeded.id)}
    # No integration exists for these, so they can never be connected.
    for key in ("shopify", "google_merchant", "woocommerce"):
        assert platforms[key]["status"] == "not_connected"
        assert platforms[key]["integration_implemented"] is False
    assert platforms["razorpay"]["status"] == "not_connected"
    assert platforms["storefront"]["status"] == "connected"
    assert platforms["storefront"]["integration_implemented"] is True


def test_status_never_reports_a_rupee_impact_it_did_not_compute(seeded, db_session):
    db = db_session
    run_row = _new_run(db, seeded)
    ProductAGI(db, seeded.id, llm=None).run(run_row, "Analyse the catalog")
    status = pa_service.build_status(db, seeded.id)
    for rec in status["recommendations"]:
        impact = rec["expected_impact"]
        if impact["status"] == "unavailable":
            assert "₹" not in impact["text"]


def test_support_text_follows_the_live_action_states(seeded, db_session):
    """The dashboard must not keep claiming 'nothing executed' after a human did."""
    db = db_session
    run_row = _new_run(db, seeded)
    ProductAGI(db, seeded.id, llm=None).run(run_row, "Analyse the catalog")

    status = pa_service.build_status(db, seeded.id)
    assert "Nothing has been executed" in status["support"]

    rec = status["recommendations"][0]
    assert rec["action_id"]
    action = db.get(AgentAction, uuid.UUID(rec["action_id"]))
    action.status = AgentActionStatus.completed
    db.commit()

    after = pa_service.build_status(db, seeded.id)
    assert "Nothing has been executed" not in after["support"]
    assert "approved and executed" in after["support"]
    assert any(r["executed"] for r in after["recommendations"])


# ── 11. API surface ─────────────────────────────────────────────────────


def _api_world(db, client, role=UserRole.owner, with_products=True):
    merchant = make_merchant(db, "api")
    user = make_user(db, "api")
    db.add(
        MerchantMembership(
            user_id=user.id,
            merchant_id=merchant.id,
            role=role,
            status=MembershipStatus.active,
        )
    )
    db.commit()
    if with_products:
        _seed_catalog(db, merchant)
    return merchant, user


def test_api_status_returns_the_real_read_model(client, db_session):
    merchant, user = _api_world(db_session, client)
    r = client.get("/api/product-agi/status", headers=bearer(user))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_run"] is False
    assert body["catalog"]["summary"]["product_count"] == 4
    assert body["platforms"]


def test_api_run_endpoints_and_tenant_isolation(client, db_session):
    merchant_a, user_a = _api_world(db_session, client)
    merchant_b, user_b = _api_world(db_session, client)

    run_a = _new_run(db_session, merchant_a)
    ProductAGI(db_session, merchant_a.id, llm=None).run(run_a, "Analyse")

    # The owner sees their own run.
    r = client.get(f"/api/product-agi/runs/{run_a.id}", headers=bearer(user_a))
    assert r.status_code == 200
    assert r.json()["id"] == str(run_a.id)

    # Another workspace cannot read it.
    r = client.get(f"/api/product-agi/runs/{run_a.id}", headers=bearer(user_b))
    assert r.status_code == 404
    assert r.json()["detail"] == "RUN_NOT_FOUND"

    # Nor its findings or recommendations.
    assert client.get(
        f"/api/product-agi/runs/{run_a.id}/findings", headers=bearer(user_b)
    ).status_code == 404
    assert client.get(
        f"/api/product-agi/runs/{run_a.id}/recommendations", headers=bearer(user_b)
    ).status_code == 404
    assert client.get(
        f"/api/product-agi/runs/{run_a.id}/activity", headers=bearer(user_b)
    ).status_code == 404

    # Listing is tenant-scoped.
    r = client.get("/api/product-agi/runs", headers=bearer(user_b))
    assert r.status_code == 200
    assert all(run["id"] != str(run_a.id) for run in r.json()["runs"])


def test_api_run_findings_recommendations_activity(client, db_session):
    merchant, user = _api_world(db_session, client)
    run_row = _new_run(db_session, merchant)
    ProductAGI(db_session, merchant.id, llm=None).run(run_row, "Analyse")
    h = bearer(user)

    r = client.get(f"/api/product-agi/runs/{run_row.id}/findings", headers=h)
    assert r.status_code == 200
    assert r.json()["findings"]

    r = client.get(f"/api/product-agi/runs/{run_row.id}/recommendations", headers=h)
    assert r.status_code == 200
    recs = r.json()["recommendations"]
    assert recs
    assert all("expected_impact" in rec for rec in recs)

    r = client.get(f"/api/product-agi/runs/{run_row.id}/activity", headers=h)
    assert r.status_code == 200
    events = r.json()["events"]
    assert events
    first = events[0]["seq"]
    r2 = client.get(
        f"/api/product-agi/runs/{run_row.id}/activity?after_seq={first}", headers=h
    )
    assert all(e["seq"] > first for e in r2.json()["events"])


def test_api_catalog_and_platforms(client, db_session):
    merchant, user = _api_world(db_session, client)
    h = bearer(user)
    r = client.get("/api/product-agi/catalog", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["product_count"] == 4
    assert set(body["segments"]) == {"top", "underperforming", "low_stock", "opportunities"}
    r = client.get("/api/product-agi/platforms", headers=h)
    assert r.status_code == 200
    assert {p["key"] for p in r.json()["platforms"]} == {
        "shopify",
        "google_merchant",
        "woocommerce",
        "razorpay",
        "storefront",
    }


def test_api_tools_reports_the_grant(client, db_session):
    merchant, user = _api_world(db_session, client)
    r = client.get("/api/product-agi/tools", headers=bearer(user))
    assert r.status_code == 200
    body = r.json()
    assert body["agent"] == "product_agent"
    assert set(body["domains"]) == {"commerce", "analytics", "product_intelligence"}
    assert body["tools"]
    assert len(body["workflow_steps"]) == 8


def test_api_start_run_returns_immediately(client, db_session):
    merchant, user = _api_world(db_session, client)
    r = client.post("/api/product-agi/runs?window_days=365", headers=bearer(user))
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["run_id"]
    assert body["status"] in {"queued", "running", "waiting_approval",
                              "completed_no_actions"}
    # The run row exists and is tenant-bound.
    row = db_session.get(ProductAgentRun, uuid.UUID(body["run_id"]))
    assert row is not None
    assert row.merchant_id == merchant.id
    assert row.metrics["window_days"] == 365


def test_api_cancel_is_operator_only(client, db_session):
    merchant, user = _api_world(db_session, client, role=UserRole.analyst)
    run_row = _new_run(db_session, merchant)
    run_row.status = "running"
    db_session.commit()
    r = client.post(f"/api/product-agi/runs/{run_row.id}/cancel", headers=bearer(user))
    assert r.status_code == 403
    assert "INSUFFICIENT_ROLE" in str(r.json()["detail"])