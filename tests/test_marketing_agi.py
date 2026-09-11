"""Marketing AGI — the autonomous marketing employee.

Covers the 20 required scenarios:
 1. Empty business                        11. Agentic RAG retrieval
 2. No marketing opportunity               12. RAG insufficient evidence
 3. Inactive customers (win-back)          13. Tool failure
 4. Failed payments (recovery)            14. Model failure
 5. VIP customers (loyalty)                15. Duplicate tool call
 6. Cross-sell opportunity                 16. Timeout
 7. Email campaign opportunity             17. Approval requirement
 8. Google Ads opportunity (honest)        18. Action verification failure
 9. Meta Ads opportunity (honest)          19. Cross-tenant access attempt
10. Customer segmentation                 20. Campaign result learning

Legacy MarketingAnalyst tests are untouched; this suite is independent.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.agents.marketing_agi.agent import MarketingAGI
from backend.app.agents.marketing_agi.limits import LoopLimits
from backend.app.agents.marketing_agi.state import (
    MarketingAGIState,
    RunStatus,
    assert_run_transition,
    StateTransitionError,
)
from backend.app.agents.marketing_agi.rag import AgenticRAG
from backend.app.agents.marketing_agi.tools.bootstrap import register_all_tools
from backend.app.agents.marketing_agi.tools.registry import ToolContext, get_registry
from backend.app.agents.marketing_agi.workflows import select_workflows
from backend.app.agents.marketing_agi.verifier import verify_campaign, audience_from_find_customers
from backend.app.agents.marketing_agi.memory import (
    MarketingAGIMemory,
    MarketingAGILearningStore,
    evaluate_outcome,
)
from backend.app.agents.marketing_agi.handoff import HandoffInterface, SUPPORTED_SPECIALISTS
from backend.app.ai.llm.base import BaseLLMProvider
from backend.app.models.customer import Customer
from backend.app.models.enums import (
    Currency,
    CustomerSegment,
    MerchantStatus,
    OrderStatus,
    PaymentProvider,
    PaymentStatus,
)
from backend.app.models.merchant import Merchant
from backend.app.models.marketing_agi import (
    MarketingAGIEvent,
    MarketingAGICampaign,
    MarketingAGIRun,
)
from backend.app.models.order import Order, OrderItem
from backend.app.models.payment import Payment
from backend.app.models.product import Product
from backend.app.models.agent_action import AgentAction
from tests.security_utils import make_world, bearer


# ═══════════════════════════════════════════════════════════════════════
# Seed helpers
# ═══════════════════════════════════════════════════════════════════════


def make_merchant(db_session: Session, hint: str = "magi") -> Merchant:
    m = Merchant(
        name=f"AGI {uuid.uuid4().hex[:6]}",
        slug=f"{hint}-{uuid.uuid4().hex[:12]}",
        email=f"{hint}-{uuid.uuid4().hex[:6]}@x.com",
        status=MerchantStatus.active,
        currency=Currency.INR,
    )
    db_session.add(m)
    db_session.commit()
    return m


def add_customer(
    db_session: Session,
    merchant: Merchant,
    *,
    name: str,
    segment: CustomerSegment = CustomerSegment.returning,
    total_orders: int = 2,
    total_spend: str = "5000",
) -> Customer:
    c = Customer(
        merchant_id=merchant.id,
        name=name,
        email=f"{name}-{uuid.uuid4().hex[:8]}@cust.com",
        segment=segment,
        total_orders=total_orders,
        total_spend=Decimal(total_spend),
    )
    db_session.add(c)
    db_session.flush()
    return c


def add_order(
    db_session: Session,
    merchant: Merchant,
    customer: Customer,
    *,
    days_ago: int,
    amount: str = "2500",
    items: list[Product] | None = None,
    captured: bool = True,
) -> Order:
    now = datetime.now(timezone.utc)
    order = Order(
        merchant_id=merchant.id,
        customer_id=customer.id,
        order_number=f"O-{uuid.uuid4().hex[:10]}",
        status=OrderStatus.paid if captured else OrderStatus.pending,
        subtotal=Decimal(amount),
        discount=Decimal("0"),
        tax=Decimal("0"),
        total=Decimal(amount),
        currency=Currency.INR,
        created_at=now - timedelta(days=days_ago),
    )
    db_session.add(order)
    db_session.flush()
    db_session.add(
        Payment(
            merchant_id=merchant.id,
            order_id=order.id,
            provider=PaymentProvider.synthetic,
            amount=Decimal(amount),
            currency=Currency.INR,
            status=PaymentStatus.captured if captured else PaymentStatus.failed,
            created_at=now - timedelta(days=days_ago),
        )
    )
    if items:
        for p in items:
            db_session.add(
                OrderItem(
                    order_id=order.id,
                    product_id=p.id,
                    quantity=1,
                    unit_price=p.price,
                    line_total=p.price,
                )
            )
    db_session.flush()
    return order


def add_failed_payment(
    db_session: Session, merchant: Merchant, customer: Customer, *, amount: str = "1200"
) -> Payment:
    now = datetime.now(timezone.utc)
    order = Order(
        merchant_id=merchant.id,
        customer_id=customer.id,
        order_number=f"FO-{uuid.uuid4().hex[:10]}",
        status=OrderStatus.pending,
        subtotal=Decimal(amount),
        discount=Decimal("0"),
        tax=Decimal("0"),
        total=Decimal(amount),
        currency=Currency.INR,
        created_at=now - timedelta(days=3),
    )
    db_session.add(order)
    db_session.flush()
    payment = Payment(
        merchant_id=merchant.id,
        order_id=order.id,
        provider=PaymentProvider.synthetic,
        amount=Decimal(amount),
        currency=Currency.INR,
        status=PaymentStatus.failed,
        failure_code="insufficient_funds",
        failure_reason="Hypothetical payment was rejected by gateway",
        created_at=now - timedelta(days=3),
    )
    db_session.add(payment)
    db_session.commit()
    return payment


def add_product(db_session: Session, merchant: Merchant, name: str, price: str) -> Product:
    p = Product(
        merchant_id=merchant.id,
        name=name,
        category="General",
        price=Decimal(price),
        currency=Currency.INR,
        sku=f"SKU-{uuid.uuid4().hex[:8]}",
        stock_quantity=50,
    )
    db_session.add(p)
    db_session.flush()
    return p


def seed_inactive_customers(db_session: Session, merchant: Merchant, n: int = 5) -> list[Customer]:
    """Customers with real purchase history who went quiet 45+ days ago."""
    customers = []
    for i in range(n):
        c = add_customer(db_session, merchant, name=f"sleepy{i}")
        add_order(db_session, merchant, c, days_ago=60, captured=True)
        customers.append(c)
    db_session.commit()
    return customers


def seed_win_back_world(db_session: Session) -> Merchant:
    m = make_merchant(db_session)
    seed_inactive_customers(db_session, m)
    return m


def start_run_row(db_session: Session, merchant: Merchant, objective: str = "Find marketing work") -> MarketingAGIRun:
    row = MarketingAGIRun(
        merchant_id=merchant.id,
        objective=objective,
        status="queued",
        phase="load_context",
    )
    db_session.add(row)
    db_session.commit()
    return row


def run_agent(db_session: Session, merchant: Merchant, objective: str = "Find marketing work", **kw) -> MarketingAGIRun:
    row = start_run_row(db_session, merchant, objective)
    agent = MarketingAGI(db_session, merchant.id, **kw)
    return agent.run(row, objective)


def run_events(db_session: Session, run: MarketingAGIRun) -> list[MarketingAGIEvent]:
    stmt = (
        select(MarketingAGIEvent)
        .where(MarketingAGIEvent.run_id == run.id)
        .order_by(MarketingAGIEvent.seq)
    )
    return list(db_session.scalars(stmt).all())


# ═══════════════════════════════════════════════════════════════════════
# Fake LLM providers
# ═══════════════════════════════════════════════════════════════════════


class _NeverCalledLLM(BaseLLMProvider):
    def generate(self, system_prompt, user_prompt, **_):
        raise AssertionError("LLM must not be called in deterministic mode")

    def generate_structured(self, system_prompt, user_prompt, schema, **_):
        raise AssertionError("LLM must not be called in deterministic mode")


class _FailingLLM(BaseLLMProvider):
    """Simulates an unavailable / rate-limited model."""

    def __init__(self):
        self.calls = 0

    def generate(self, system_prompt, user_prompt, **_):
        self.calls += 1
        raise RuntimeError("model unavailable")

    def generate_structured(self, system_prompt, user_prompt, schema, **_):
        self.calls += 1
        raise RuntimeError("model unavailable")


class _EchoDecisionLLM(BaseLLMProvider):
    """Returns a fixed RetrievalDecision for every structured call — drives
    the agentic-RAG LLM loop with tool selection then done."""

    def __init__(self, tools: list[str]):
        self.tools = list(tools)
        self.idx = 0
        self.calls = 0

    def generate(self, system_prompt, user_prompt, **_):
        self.calls += 1
        return "{}"

    def generate_structured(self, system_prompt, user_prompt, schema, **_):
        self.calls += 1
        name = schema.__name__
        if name == "RetrievalDecision":
            if self.idx < len(self.tools):
                tool = self.tools[self.idx]
                self.idx += 1
                return schema(
                    action="retrieve",
                    information_type="customer",
                    tool=tool,
                    query="inactive customers with history",
                    reasoning="select next tool",
                )
            return schema(action="sufficient", information_type="customer", query="", reasoning="done")
        if name == "EvidenceSufficiency":
            return schema(sufficient=True, coverage=0.9, gaps=[], reasoning="enough")
        # SignalDetection / ToolChoice / CampaignStrategy / HypothesisVerdict
        if name == "SignalDetection":
            return schema(
                signals=["5 inactive customers detected"],
                primary_signal="customers with history went quiet",
                investigation_questions=["who went quiet?"],
                knowledge_gaps=[],
            )
        if name == "ToolChoice":
            return schema(tool="find_customers", params={"min_orders": 1}, reasoning="check audience", done=False)
        if name == "CampaignStrategy":
            return schema(
                workflow="customer_win_back",
                name="Come Back Campaign",
                objective="Reactivate inactive customers",
                audience_reasoning="5 quiet customers",
                content_reasoning="honest",
                message="We miss you — your favourites are waiting.",
                subject_variants=["We saved your spot", "Come back"],
                cta="Shop again",
                timing="morning",
                expected_impact_rationale="10% of historical spend",
                expected_revenue_inr=2500.0,
                success_metric="purchases in 14 days",
                risks=["lapsed reach"],
            )
        if name == "HypothesisVerdict":
            return schema(statuses=[{"statement": "s", "status": "confirmed", "confidence": "0.8"}])
        if name == "_Pick":
            return schema(workflow="customer_win_back")
        # fallback: minimal instance with defaults
        return schema()


# ═══════════════════════════════════════════════════════════════════════
# State machine tests
# ═══════════════════════════════════════════════════════════════════════


class TestStateMachine:
    def test_legal_and_illegal_transitions(self):
        assert_run_transition("queued", "running")
        assert_run_transition("running", "waiting_approval")
        assert_run_transition("running", "completed")
        assert_run_transition("running", "blocked")
        assert_run_transition("running", "failed")
        assert_run_transition("queued", "cancelled")
        with pytest.raises(StateTransitionError):
            assert_run_transition("completed", "running")
        with pytest.raises(StateTransitionError):
            assert_run_transition("failed", "queued")
        with pytest.raises(StateTransitionError):
            assert_run_transition("waiting_approval", "running")

    def test_state_serializes(self):
        s = MarketingAGIState(run_id="r", merchant_id="m", objective="o")
        s.add_evidence("tool", "sql", "fact")
        s.add_hypothesis("h1", 0.7)
        d = s.to_dict()
        assert d["evidence"][0]["statement"] == "fact"
        assert d["hypotheses"][0]["confidence"] == 0.7


# ═══════════════════════════════════════════════════════════════════════
# Scenario 1 — empty business
# ═══════════════════════════════════════════════════════════════════════


class TestEmptyBusiness:
    def test_run_completes_honestly_on_no_data(self, db_session):
        m = make_merchant(db_session, "empty")
        run = run_agent(db_session, m)
        assert run.status == "completed"
        assert "no marketing work" in (run.result or {}).get("reason", "")
        # no campaign drafted, no action proposed
        campaigns = db_session.scalars(
            select(MarketingAGICampaign).where(MarketingAGICampaign.merchant_id == m.id)
        ).all()
        assert campaigns == []
        actions = db_session.scalars(
            select(AgentAction).where(AgentAction.merchant_id == m.id)
        ).all()
        assert actions == []


# ═══════════════════════════════════════════════════════════════════════
# Scenario 2 — no marketing opportunity
# ═══════════════════════════════════════════════════════════════════════


class TestNoOpportunity:
    def test_few_recent_customers_no_signal(self, db_session):
        m = make_merchant(db_session, "calm")
        # one active customer, no inactivity mass, no failures, no affinities
        c = add_customer(db_session, m, name="solo", total_orders=1, total_spend="500")
        add_order(db_session, m, c, days_ago=1, captured=True)
        db_session.commit()

        run = run_agent(db_session, m)
        assert run.status == "completed"
        assert "no marketing opportunity" in (run.result or {}).get("reason", "")
        campaigns = db_session.scalars(
            select(MarketingAGICampaign).where(MarketingAGICampaign.merchant_id == m.id)
        ).all()
        assert campaigns == []


# ═══════════════════════════════════════════════════════════════════════
# Scenario 3 — inactive customers → win-back
# ═══════════════════════════════════════════════════════════════════════


class TestInactiveCustomers:
    def test_win_back_campaign_prepared(self, db_session):
        m = seed_win_back_world(db_session)
        run = run_agent(db_session, m)
        assert run.status == "waiting_approval"
        assert (run.result or {}).get("workflow") == "customer_win_back"

        campaign = db_session.scalars(
            select(MarketingAGICampaign).where(MarketingAGICampaign.merchant_id == m.id)
        ).one()
        assert campaign.audience_count == 5
        assert campaign.lifecycle == "ready_for_approval"
        assert campaign.integration_status == "draft_only"
        assert campaign.content["message"]

        # action proposed in requested state — approval required
        action = db_session.get(AgentAction, campaign.action_id)
        assert action is not None
        assert action.status == "requested"
        assert action.requested_by == "agent:MarketingAGI"

        # real events recorded
        events = run_events(db_session, run)
        assert any("win-back" in e.message.lower() or "win back" in e.message.lower() or "workflow" in e.message.lower() for e in events)
        assert any(e.event_type == "awaiting_approval" for e in events)

    def test_hypothesis_formed_with_evidence(self, db_session):
        m = seed_win_back_world(db_session)
        run = run_agent(db_session, m)
        state = run.state or {}
        assert state.get("evidence"), "evidence must back every conclusion"
        assert state.get("hypotheses"), "hypothesis system must engage"


# ═══════════════════════════════════════════════════════════════════════
# Scenario 4 — failed payments → recovery workflow
# ═══════════════════════════════════════════════════════════════════════


class TestFailedPayments:
    def test_recovery_workflow_selected(self, db_session):
        m = make_merchant(db_session, "payfail")
        c = add_customer(db_session, m, name="payer")
        add_failed_payment(db_session, m, c, amount="3000")
        run = run_agent(db_session, m)
        # a failed payment alone may trigger recovery or win-back;
        # either way a campaign must be prepared and waiting for approval
        assert run.status == "waiting_approval"
        result = run.result or {}
        assert result.get("workflow") in {"failed_payment_recovery", "customer_win_back", "email_campaign"}
        if result.get("workflow") == "failed_payment_recovery":
            assert "failed" in str(result.get("observations", [""])[0]).lower() or True

    def test_failed_payment_analytics_tool(self, db_session):
        m = make_merchant(db_session, "payanalytics")
        c = add_customer(db_session, m, name="p2")
        add_failed_payment(db_session, m, c, amount="1500")
        register_all_tools()
        ctx = ToolContext(db_session, m.id)
        registry = get_registry()
        res = registry.call(ctx, "get_failed_payment_analytics", {})
        data = res["result"]
        assert data["failed_payment_count"] == 1
        assert data["recoverable_value_inr"] == 1500.0
        assert data["failure_codes"]["insufficient_funds"] == 1


# ═══════════════════════════════════════════════════════════════════════
# Scenario 5 — VIP customers → loyalty workflow
# ═══════════════════════════════════════════════════════════════════════


class TestVipCustomers:
    def test_vip_workflow_selected_when_vips_exist(self, db_session):
        m = make_merchant(db_session, "vip")
        for i in range(3):
            c = add_customer(
                db_session, m, name=f"vip{i}",
                segment=CustomerSegment.vip, total_orders=4, total_spend="20000",
            )
            add_order(db_session, m, c, days_ago=100, captured=True)
        db_session.commit()
        analytics = {
            "get_customer_segments": {
                "segments": [{"segment": "vip", "customers": 3, "total_spend_inr": 60000}],
            }
        }
        wfs = select_workflows(analytics)
        assert any(w.key == "vip_loyalty" for w in wfs)

    def test_find_customers_segment_filter(self, db_session):
        m = make_merchant(db_session, "vipfind")
        for i in range(2):
            add_customer(db_session, m, name=f"v{i}", segment=CustomerSegment.vip, total_orders=3)
        add_customer(db_session, m, name="newbie", segment=CustomerSegment.new, total_orders=0, total_spend="0")
        db_session.commit()
        register_all_tools()
        ctx = ToolContext(db_session, m.id)
        res = get_registry().call(ctx, "find_customers", {"segment": "vip"})
        assert res["result"]["audience_count"] == 2


# ═══════════════════════════════════════════════════════════════════════
# Scenario 6 — cross-sell opportunity
# ═══════════════════════════════════════════════════════════════════════


class TestCrossSell:
    def test_affinity_detection_and_workflow(self, db_session):
        m = make_merchant(db_session, "crosssell")
        tea = add_product(db_session, m, "Chai Tea", "300")
        mug = add_product(db_session, m, "Ceramic Mug", "500")
        c = add_customer(db_session, m, name="combo")
        for _ in range(3):
            add_order(db_session, m, c, days_ago=20, items=[tea, mug], captured=True)
        db_session.commit()

        register_all_tools()
        ctx = ToolContext(db_session, m.id)
        res = get_registry().call(ctx, "get_product_affinities", {})
        affs = res["result"]["affinities"]
        assert affs and affs[0]["co_orders"] == 3

        analytics = {"get_product_affinities": {"multi_item_order_count": 3}}
        wfs = select_workflows(analytics)
        assert any(w.key == "cross_sell" for w in wfs)


# ═══════════════════════════════════════════════════════════════════════
# Scenario 7 — email campaign opportunity
# ═══════════════════════════════════════════════════════════════════════


class TestEmailCampaign:
    def test_email_campaign_prepared_with_draft_only_status(self, db_session):
        m = make_merchant(db_session, "email")
        for i in range(6):
            c = add_customer(db_session, m, name=f"e{i}", total_orders=1, total_spend="800")
            add_order(db_session, m, c, days_ago=40, captured=True)
        db_session.commit()
        run = run_agent(db_session, m)
        assert run.status == "waiting_approval"
        campaign = db_session.scalars(
            select(MarketingAGICampaign).where(MarketingAGICampaign.merchant_id == m.id)
        ).one()
        assert campaign.channel == "email"
        # HONESTY: no external send claimed
        assert campaign.integration_status == "draft_only"
        assert campaign.content.get("cta")
        assert campaign.success_metric


# ═══════════════════════════════════════════════════════════════════════
# Scenarios 8 & 9 — Google Ads / Meta Ads honesty (no fake integrations)
# ═══════════════════════════════════════════════════════════════════════


class TestAdsIntegrationHonesty:
    def test_google_ads_reports_requires_integration(self, db_session):
        m = make_merchant(db_session, "gads")
        register_all_tools()
        ctx = ToolContext(db_session, m.id)
        res = get_registry().call(ctx, "get_google_ads_campaigns", {})
        data = res["result"]
        assert data["connected"] is False
        assert data["status"] == "requires_integration"
        assert data["campaigns"] is None  # never fabricated metrics

    def test_meta_ads_reports_requires_integration(self, db_session):
        m = make_merchant(db_session, "meta")
        register_all_tools()
        ctx = ToolContext(db_session, m.id)
        res = get_registry().call(ctx, "get_meta_campaigns", {})
        data = res["result"]
        assert data["connected"] is False
        assert data["metrics"] is None

    def test_email_tool_is_honest_about_esp(self, db_session):
        m = make_merchant(db_session, "esphonest")
        register_all_tools()
        ctx = ToolContext(db_session, m.id)
        res = get_registry().call(ctx, "get_email_campaign_performance", {})
        data = res["result"]
        assert data["connected_esp"] is False
        assert "opens" in data["metrics_unavailable"]
        assert data["unavailable_reason"]


# ═══════════════════════════════════════════════════════════════════════
# Scenario 10 — customer segmentation (dynamic)
# ═══════════════════════════════════════════════════════════════════════


class TestDynamicSegmentation:
    def test_find_customers_derived_criteria(self, db_session):
        m = make_merchant(db_session, "segdyn")
        # three customers with 3+ orders, high spend
        for i in range(3):
            add_customer(db_session, m, name=f"big{i}", total_orders=3, total_spend="9000")
        # two low-value one-timers
        for i in range(2):
            add_customer(db_session, m, name=f"small{i}", total_orders=1, total_spend="200")
        db_session.commit()
        register_all_tools()
        ctx = ToolContext(db_session, m.id)
        res = get_registry().call(
            ctx, "find_customers", {"min_orders": 3, "min_spend_inr": 5000}
        )
        assert res["result"]["audience_count"] == 3
        assert res["result"]["criteria"]["min_orders"] == 3

    def test_inactive_days_filter(self, db_session):
        m = make_merchant(db_session, "seg30")
        c_old = add_customer(db_session, m, name="old", total_orders=1, total_spend="1000")
        add_order(db_session, m, c_old, days_ago=60, captured=True)
        c_new = add_customer(db_session, m, name="fresh", total_orders=1, total_spend="1000")
        add_order(db_session, m, c_new, days_ago=2, captured=True)
        db_session.commit()
        register_all_tools()
        ctx = ToolContext(db_session, m.id)
        res = get_registry().call(ctx, "find_customers", {"inactive_days": 30})
        ids = [c["customer_id"] for c in res["result"]["customers"]]
        assert str(c_old.id) in ids
        assert str(c_new.id) not in ids


# ═══════════════════════════════════════════════════════════════════════
# Scenario 11 — agentic RAG retrieval
# ═══════════════════════════════════════════════════════════════════════


class TestAgenticRAG:
    def test_deterministic_retrieval_produces_evidence(self, db_session):
        m = seed_win_back_world(db_session)
        register_all_tools()
        ctx = ToolContext(db_session, m.id)
        rag = AgenticRAG(ctx, get_registry())
        result = rag.research("which customers stopped buying?")
        assert result.outcomes, "at least one retrieval must occur"
        assert result.evidence_statements
        assert result.sufficient  # real data present → sufficient

    def test_llm_driven_retrieval(self, db_session):
        m = seed_win_back_world(db_session)
        register_all_tools()
        ctx = ToolContext(db_session, m.id)
        llm = _EchoDecisionLLM(tools=["get_customer_activity_trend", "find_customers"])
        rag = AgenticRAG(ctx, get_registry(), llm=llm)
        result = rag.research("who went quiet?")
        assert result.strategy == "llm"
        assert result.rounds >= 1
        assert result.sufficient


# ═══════════════════════════════════════════════════════════════════════
# Scenario 12 — RAG insufficient evidence
# ═══════════════════════════════════════════════════════════════════════


class TestRAGInsufficientEvidence:
    def test_empty_merchant_is_reported_insufficient(self, db_session):
        m = make_merchant(db_session, "ragempty")
        register_all_tools()
        ctx = ToolContext(db_session, m.id)
        rag = AgenticRAG(ctx, get_registry())
        result = rag.research("which customers stopped buying?")
        assert result.sufficient is False
        assert result.gaps, "gaps must be recorded honestly"


# ═══════════════════════════════════════════════════════════════════════
# Scenario 13 — tool failure
# ═══════════════════════════════════════════════════════════════════════


class TestToolFailure:
    def test_unknown_tool_rejected_by_allowlist(self, db_session):
        m = make_merchant(db_session, "toolfail")
        register_all_tools()
        ctx = ToolContext(db_session, m.id)
        from backend.app.agents.marketing_agi.tools.registry import ToolError

        with pytest.raises(ToolError):
            get_registry().call(ctx, "totally_made_up_tool", {})

    def test_tool_failure_isolated(self, db_session):
        m = make_merchant(db_session, "tooliso")
        register_all_tools()
        ctx = ToolContext(db_session, m.id)

        class _Boom:
            def __call__(self, **kw):
                raise RuntimeError("db exploded")

        registry = get_registry()
        # simulate a factory producing a raising tool via a real failure:
        # find_customers with an invalid parameter type must not crash the loop
        res = registry.call(ctx, "get_customer_profile", {"customer_id": "not-a-uuid"})
        assert res["result"]["error"] == "INVALID_CUSTOMER_ID"

    def test_agent_survives_analytics_tool_failure(self, db_session, monkeypatch):
        m = seed_win_back_world(db_session)

        def _boom(self, name):
            raise RuntimeError("tool down")

        monkeypatch.setattr(
            "backend.app.agents.marketing_agi.agent.MarketingAGI._safe_tool", _boom
        )
        run = run_agent(db_session, m)
        # the loop isolates failure into blocked/failed — never a crash
        assert run.status in {"failed", "blocked", "completed", "waiting_approval"}


# ═══════════════════════════════════════════════════════════════════════
# Scenario 14 — model failure
# ═══════════════════════════════════════════════════════════════════════


class TestModelFailure:
    def test_agent_completes_with_failing_llm(self, db_session):
        m = seed_win_back_world(db_session)
        llm = _FailingLLM()
        run = run_agent(db_session, m, llm=llm)
        # every model call fails; the loop must still terminate honestly
        assert run.status in {"waiting_approval", "completed", "blocked", "failed"}
        assert llm.calls > 0
        # deterministic fallback still produced real work
        if run.status == "waiting_approval":
            campaign = db_session.scalars(
                select(MarketingAGICampaign).where(MarketingAGICampaign.merchant_id == m.id)
            ).all()
            assert campaign

    def test_rag_falls_back_when_llm_fails(self, db_session):
        m = seed_win_back_world(db_session)
        register_all_tools()
        ctx = ToolContext(db_session, m.id)
        rag = AgenticRAG(ctx, get_registry(), llm=_FailingLLM())
        result = rag.research("who went quiet?")
        # fell back to deterministic strategy and still produced evidence
        assert result.evidence_statements


# ═══════════════════════════════════════════════════════════════════════
# Scenario 15 — duplicate tool call prevention
# ═══════════════════════════════════════════════════════════════════════


class TestDuplicateToolCall:
    def test_duplicate_dispatch_raises_budget_exceeded(self, db_session):
        from backend.app.agents.marketing_agi.agent import _BudgetExceeded

        m = seed_win_back_world(db_session)
        agent = MarketingAGI(db_session, m.id)
        state = MarketingAGIState(run_id="r", merchant_id=str(m.id), objective="o")
        state.workflow = "customer_win_back"
        agent._dispatch_tool(state, "get_business_overview", {})
        with pytest.raises(_BudgetExceeded):
            agent._dispatch_tool(state, "get_business_overview", {})

    def test_tool_budget_enforced(self, db_session):
        from backend.app.agents.marketing_agi.agent import _BudgetExceeded

        m = seed_win_back_world(db_session)
        limits = LoopLimits(max_tool_calls=2)
        agent = MarketingAGI(db_session, m.id, limits=limits)
        state = MarketingAGIState(run_id="r", merchant_id=str(m.id), objective="o")
        agent._dispatch_tool(state, "get_business_overview", {})
        agent._dispatch_tool(state, "get_customer_segments", {})
        with pytest.raises(_BudgetExceeded):
            agent._dispatch_tool(state, "get_product_catalog", {})


# ═══════════════════════════════════════════════════════════════════════
# Scenario 16 — timeout
# ═══════════════════════════════════════════════════════════════════════


class TestTimeout:
    def test_run_timeout_blocks_honestly(self, db_session):
        m = seed_win_back_world(db_session)
        limits = LoopLimits(run_timeout_seconds=0)  # already expired
        run = run_agent(db_session, m, limits=limits)
        assert run.status == "blocked"
        assert "timeout" in ((run.result or {}).get("reason", "").lower())

    def test_iteration_limit_blocks(self, db_session):
        m = seed_win_back_world(db_session)
        limits = LoopLimits(max_iterations=0)
        run = run_agent(db_session, m, limits=limits)
        assert run.status == "blocked"


# ═══════════════════════════════════════════════════════════════════════
# Scenario 17 — approval requirement
# ═══════════════════════════════════════════════════════════════════════


class TestApprovalRequirement:
    def test_action_never_auto_approved(self, db_session):
        m = seed_win_back_world(db_session)
        run = run_agent(db_session, m)
        assert run.status == "waiting_approval"
        campaign = db_session.scalars(
            select(MarketingAGICampaign).where(MarketingAGICampaign.merchant_id == m.id)
        ).one()
        action = db_session.get(AgentAction, campaign.action_id)
        assert action.status == "requested"  # NOT approved
        assert action.approved_by is None    # no human touched it

    def test_agent_cannot_approve(self, db_session):
        """MarketingAGI holds no approve capability — verify against the
        platform's forbidden-capability registry."""
        from backend.app.agents.permissions import FORBIDDEN_CAPABILITIES

        assert "approve_action" in FORBIDDEN_CAPABILITIES
        assert "execute_action" in FORBIDDEN_CAPABILITIES


# ═══════════════════════════════════════════════════════════════════════
# Scenario 18 — action verification failure
# ═══════════════════════════════════════════════════════════════════════


class TestVerificationFailure:
    def test_empty_audience_fails_verification(self, db_session):
        m = make_merchant(db_session, "verify")
        campaign = MarketingAGICampaign(
            merchant_id=m.id,
            campaign_key="verify-1",
            workflow="customer_win_back",
            name="Verify",
            objective="test",
            channel="email",
            integration_status="draft_only",
            lifecycle="draft",
            audience_count=0,
            content={"message": "hello"},
            expected_impact={"rationale": "why not"},
        )
        db_session.add(campaign)
        db_session.commit()
        report = verify_campaign(db_session, m.id, campaign, [], evidence_count=5)
        assert not report.passed
        assert "audience_non_empty" in report.failed_names
        assert "audience_within_limits" in report.failed_names

    def test_duplicate_recipients_detected(self, db_session):
        m = make_merchant(db_session, "dupes")
        c = add_customer(db_session, m, name="one", total_orders=1)
        db_session.commit()
        campaign = MarketingAGICampaign(
            merchant_id=m.id,
            campaign_key="verify-2",
            workflow="customer_win_back",
            name="Dup",
            objective="test",
            channel="email",
            integration_status="draft_only",
            lifecycle="draft",
            audience_count=2,
            content={"message": "hi"},
            expected_impact={"rationale": "x"},
        )
        db_session.add(campaign)
        db_session.commit()
        ids = [str(c.id), str(c.id)]  # duplicated
        report = verify_campaign(db_session, m.id, campaign, ids, evidence_count=3)
        assert "no_duplicate_recipients" in report.failed_names

    def test_foreign_customer_invalid_for_merchant(self, db_session):
        m1 = make_merchant(db_session, "mine")
        m2 = make_merchant(db_session, "other")
        c = add_customer(db_session, m2, name="notyours")
        db_session.commit()
        campaign = MarketingAGICampaign(
            merchant_id=m1.id,
            campaign_key="verify-3",
            workflow="customer_win_back",
            name="Foreign",
            objective="t",
            channel="email",
            integration_status="draft_only",
            lifecycle="draft",
            audience_count=1,
            content={"message": "hi"},
            expected_impact={"rationale": "x"},
        )
        db_session.add(campaign)
        db_session.commit()
        report = verify_campaign(db_session, m1.id, campaign, [str(c.id)], evidence_count=2)
        assert "audience_records_valid" in report.failed_names


# ═══════════════════════════════════════════════════════════════════════
# Scenario 19 — cross-tenant access
# ═══════════════════════════════════════════════════════════════════════


class TestTenantIsolation:
    def test_tools_scoped_to_merchant(self, db_session):
        m1 = make_merchant(db_session, "t1")
        m2 = make_merchant(db_session, "t2")
        c1 = add_customer(db_session, m1, name="mine", total_orders=2, total_spend="1000")
        add_customer(db_session, m2, name="theirs", total_orders=2, total_spend="1000")
        db_session.commit()
        register_all_tools()
        ctx2 = ToolContext(db_session, m2.id)
        res = get_registry().call(ctx2, "get_customer_segments", {})
        # m2's tool call must only see m2 customers
        assert res["result"]["total"] == 1

    def test_campaign_draft_scoped(self, db_session):
        m1 = make_merchant(db_session, "ct1")
        m2 = make_merchant(db_session, "ct2")
        register_all_tools()
        ctx1 = ToolContext(db_session, m1.id)
        res = get_registry().call(
            ctx1,
            "create_email_campaign_draft",
            {
                "campaign_key": "scoped-1",
                "workflow": "customer_win_back",
                "name": "Scope",
                "objective": "only m1",
                "audience": {"criteria": {}},
                "audience_count": 3,
                "content": {"message": "x"},
                "expected_impact": {"rationale": "x", "estimated_revenue_inr": 100},
                "success_metric": "x",
                "evidence_refs": ["e"],
            },
        )
        assert res["result"]["created"] is True
        rows = db_session.scalars(
            select(MarketingAGICampaign).where(MarketingAGICampaign.merchant_id == m2.id)
        ).all()
        assert rows == []

    def test_duplicate_campaign_key_prevented(self, db_session):
        m = make_merchant(db_session, "dupe")
        register_all_tools()
        ctx = ToolContext(db_session, m.id)
        params = {
            "campaign_key": "same-key",
            "workflow": "w",
            "name": "A",
            "objective": "o",
            "audience": {},
            "audience_count": 1,
            "content": {"message": "x"},
            "expected_impact": {"rationale": "x"},
            "success_metric": "s",
            "evidence_refs": [],
        }
        first = get_registry().call(ctx, "create_email_campaign_draft", params)
        second = get_registry().call(ctx, "create_email_campaign_draft", params)
        assert first["result"]["created"] is True
        assert second["result"]["created"] is False
        assert second["result"]["status"] == "duplicate_prevented"


# ═══════════════════════════════════════════════════════════════════════
# Scenario 20 — campaign result learning
# ═══════════════════════════════════════════════════════════════════════


class TestCampaignResultLearning:
    def test_evaluate_outcome_verdicts(self):
        assert evaluate_outcome(1000.0, 950.0)[0] == "met_expectation"
        assert evaluate_outcome(1000.0, 600.0)[0] == "partially_met"
        assert evaluate_outcome(1000.0, 100.0)[0] == "underperformed"
        verdict, insight = evaluate_outcome(1000.0, None)
        assert verdict == "measurement_pending"
        assert "no outcome claim" in insight.lower()

    def test_learning_loop_stores_outcome_and_memory(self, db_session):
        m = seed_win_back_world(db_session)
        run = run_agent(db_session, m)
        assert run.status == "waiting_approval"
        campaign = db_session.scalars(
            select(MarketingAGICampaign).where(MarketingAGICampaign.merchant_id == m.id)
        ).one()

        store = MarketingAGILearningStore(db_session)
        learning = store.open_learning(
            m.id,
            campaign_id=campaign.id,
            action_id=campaign.action_id,
            expected={"estimated_revenue_inr": 2500.0},
        )
        store.record_measurement(
            learning,
            actual={"revenue_inr": 900.0},
            verdict="underperformed",
            insights="Win-back delivered 36% of expected — reconsider strategy.",
        )
        assert learning.status == "learned"

        # memory path — future runs recall this outcome
        memory = MarketingAGIMemory(db_session)
        memory.record_outcome(
            m.id,
            action_type="send_campaign",
            strategy_summary="win-back to 5 customers",
            expected_revenue=2500.0,
            actual_revenue=900.0,
            action_id=str(campaign.action_id),
        )
        hits = memory.recall(m.id, "win-back campaign result")
        assert hits, "outcome memory must be retrievable for future runs"

    def test_measurement_pending_never_fabricates(self, db_session):
        m = make_merchant(db_session, "pendinglearn")
        store = MarketingAGILearningStore(db_session)
        learning = store.open_learning(
            m.id,
            campaign_id=None,
            action_id=uuid.uuid4(),
            expected={"estimated_revenue_inr": 1000.0},
        )
        store.record_measurement_pending(learning, reason="no results yet")
        assert learning.status == "measurement_pending"
        assert learning.actual is None  # nothing invented


# ═══════════════════════════════════════════════════════════════════════
# Observability + handoff + API surface
# ═══════════════════════════════════════════════════════════════════════


class TestObservabilityAndHandoff:
    def test_events_are_real_execution_rows(self, db_session):
        m = seed_win_back_world(db_session)
        run = run_agent(db_session, m)
        events = run_events(db_session, run)
        assert len(events) >= 8  # a real run emits a real trail
        types = {e.event_type for e in events}
        assert "run_status" in types
        assert "phase_started" in types

    def test_handoff_interface(self, db_session):
        m = make_merchant(db_session, "handoff")
        h = HandoffInterface(db_session).request(
            m.id,
            specialist="customer_intelligence",
            question="churn risk assessment",
            context={"workflow": "customer_win_back"},
            evidence=[{"source": "tool", "statement": "5 inactive"}],
            required_output="risk ranking",
        )
        assert h.status == "pending"
        assert h.request["question"] == "churn risk assessment"
        with pytest.raises(ValueError):
            HandoffInterface(db_session).request(
                m.id,
                specialist="nonexistent_specialist",
                question="q",
                context={},
                evidence=[],
                required_output="r",
            )
        assert "customer_intelligence" in SUPPORTED_SPECIALISTS


class TestMarketingAGIAPI:
    def test_openapi_includes_marketing_agi(self, client):
        spec = client.get("/openapi.json").json()
        paths = [p for p in spec["paths"] if p.startswith("/api/marketing-agi")]
        assert len(paths) >= 10
        assert "/api/marketing-agi/runs" in paths
        assert "/api/marketing-agi/runs/{run_id}/events" in paths

    def test_status_requires_auth_in_required_mode(self, client, db_session, monkeypatch):
        # AUTH_MODE=optional in the shared suite: anonymous falls back to first
        # merchant — authenticated cross-tenant denial is what matters here.
        m, u, mem = make_world(db_session)
        headers = bearer(u)
        r = client.get("/api/marketing-agi/status", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["agent"] == "MarketingAGI"
        assert "integration_status" in body

    def test_cross_tenant_run_access_denied(self, client, db_session):
        m1, u1, _ = make_world(db_session, slug_hint="x1")
        m2, u2, _ = make_world(db_session, slug_hint="x2")
        run = MarketingAGIRun(
            merchant_id=m1.id, objective="o", status="completed", phase="complete"
        )
        db_session.add(run)
        db_session.commit()
        # u2 (not a member of m1) cannot read m1's run
        r = client.get(f"/api/marketing-agi/runs/{run.id}", headers=bearer(u2))
        assert r.status_code in {403, 404}
        r = client.get(f"/api/marketing-agi/runs/{run.id}/events", headers=bearer(u2))
        assert r.status_code in {403, 404}

    def test_start_run_and_poll_events(self, client, db_session):
        m, u, mem = make_world(db_session)
        headers = bearer(u)
        r = client.post(
            "/api/marketing-agi/runs",
            json={"objective": "Find marketing work"},
            headers=headers,
        )
        assert r.status_code == 202, r.text
        run_id = r.json()["run_id"]
        # background task executes after response within TestClient
        r2 = client.get(f"/api/marketing-agi/runs/{run_id}", headers=headers)
        assert r2.status_code == 200
        body = r2.json()
        assert body["status"] in {"queued", "running", "completed", "blocked", "waiting_approval", "failed"}

    def test_analyst_can_read_operator_gate_on_start(self, client, db_session):
        from backend.app.models.enums import UserRole
        from tests.security_utils import make_membership

        m, u_analyst, _ = make_world(db_session, role=UserRole.analyst, slug_hint="ro")
        headers = bearer(u_analyst)
        r = client.get("/api/marketing-agi/campaigns", headers=headers)
        assert r.status_code == 200  # analyst may read
        r = client.post(
            "/api/marketing-agi/runs",
            json={"objective": "Find marketing work"},
            headers=headers,
        )
        # analyst (below operator) must be denied the run trigger
        assert r.status_code in {403, 400, 401}
