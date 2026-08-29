"""Phase 5 — multi-agent system: permissions, orchestration, audit,
Phase 4 integration, failure isolation, idempotency."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.agents.base import AgentContext, BaseGrowthAgent
from backend.app.agents.orchestrator import (
    GrowthAgentOrchestrator,
    MerchantNotFoundError,
)
from backend.app.agents.permissions import (
    AGENT_PERMISSIONS,
    FORBIDDEN_CAPABILITIES,
    AgentPermissionError,
    assert_permission,
)
from backend.app.agents.registry import AGENT_INSTANCES, agent_catalog
from backend.app.models.agent_action import AgentAction
from backend.app.models.agent_run import AgentRun
from backend.app.models.customer import Customer
from backend.app.models.enums import (
    Currency,
    MerchantStatus,
    OrderStatus,
    PaymentProvider,
    PaymentStatus,
)
from backend.app.models.merchant import Merchant
from backend.app.models.opportunity import GrowthOpportunity
from backend.app.models.order import Order
from backend.app.models.payment import Payment
from backend.app.services.action_service import (
    approve_action,
    execute_action,
)


# ────────────────────────────────────────────────────────────────────────────
# Seed helpers
# ────────────────────────────────────────────────────────────────────────────


def make_merchant(db_session: Session) -> Merchant:
    m = Merchant(
        name=f"P5 Agents {uuid.uuid4().hex[:6]}",
        slug=f"p5-agents-{uuid.uuid4().hex[:10]}",
        email="p5agents@x.com",
        status=MerchantStatus.active,
        currency=Currency.INR,
    )
    db_session.add(m)
    db_session.commit()
    return m


def seed_commerce(db_session: Session, merchant: Merchant) -> None:
    """4 customers, prior-window orders, current failures — enough for signals."""
    now = datetime.now(timezone.utc)
    for i in range(4):
        c = Customer(
            merchant_id=merchant.id,
            name=f"C{i}",
            email=f"c{i}-{uuid.uuid4().hex[:6]}@c.com",
            total_orders=1,
            total_spend=Decimal("10000"),
        )
        db_session.add(c)
        db_session.flush()
        order = Order(
            merchant_id=merchant.id,
            customer_id=c.id,
            order_number=f"O-{uuid.uuid4().hex[:8]}",
            status=OrderStatus.paid,
            subtotal=Decimal("10000"),
            discount=Decimal("0"),
            tax=Decimal("0"),
            total=Decimal("10000"),
            currency=Currency.INR,
            created_at=now - timedelta(days=45),
        )
        db_session.add(order)
        db_session.flush()
        db_session.add(
            Payment(
                merchant_id=merchant.id,
                order_id=order.id,
                provider=PaymentProvider.synthetic,
                amount=Decimal("10000"),
                currency=Currency.INR,
                status=PaymentStatus.captured,
                created_at=now - timedelta(days=45),
            )
        )
        # a failed payment in the current window for two customers
        if i < 2:
            fail_order = Order(
                merchant_id=merchant.id,
                customer_id=c.id,
                order_number=f"F-{uuid.uuid4().hex[:8]}",
                status=OrderStatus.pending,
                subtotal=Decimal("5000"),
                discount=Decimal("0"),
                tax=Decimal("0"),
                total=Decimal("5000"),
                currency=Currency.INR,
                created_at=now - timedelta(days=3),
            )
            db_session.add(fail_order)
            db_session.flush()
            db_session.add(
                Payment(
                    merchant_id=merchant.id,
                    order_id=fail_order.id,
                    provider=PaymentProvider.synthetic,
                    amount=Decimal("5000"),
                    currency=Currency.INR,
                    status=PaymentStatus.failed,
                    created_at=now - timedelta(days=3),
                )
            )
    db_session.commit()


@pytest.fixture()
def merchant_with_data(db_session: Session) -> Merchant:
    m = make_merchant(db_session)
    seed_commerce(db_session, m)
    return m


# ────────────────────────────────────────────────────────────────────────────
# Feature 13 — permissions
# ────────────────────────────────────────────────────────────────────────────


class TestAgentPermissions:
    def test_no_agent_holds_forbidden_capabilities(self):
        for name, perms in AGENT_PERMISSIONS.items():
            overlap = perms & FORBIDDEN_CAPABILITIES
            assert not overlap, f"{name} holds forbidden capabilities: {overlap}"

    def test_registry_matches_permission_matrix(self):
        assert set(AGENT_INSTANCES) == set(AGENT_PERMISSIONS)
        for agent in AGENT_INSTANCES.values():
            assert agent.PERMISSIONS == AGENT_PERMISSIONS[agent.NAME]

    def test_catalog_reports_no_approve_execute(self):
        for entry in agent_catalog():
            assert entry["can_approve"] is False
            assert entry["can_execute"] is False
            assert "approve_action" not in entry["permissions"]
            assert "execute_action" not in entry["permissions"]

    def test_catalog_has_all_13_agents(self):
        """Verify all 13 agents (8 domain + 5 main) are in catalog."""
        catalog = agent_catalog()
        assert len(catalog) == 13
        names = {entry["name"] for entry in catalog}
        # 8 domain specialists
        assert "GrowthDiscoveryAgent" in names
        assert "CustomerIntelligenceAgent" in names
        assert "RevenueOptimizationAgent" in names
        assert "CampaignStrategistAgent" in names
        assert "PaymentRecoveryAgent" in names
        assert "OpportunityPrioritizationAgent" in names
        assert "ExperimentAgent" in names
        assert "GrowthMemoryAgent" in names
        # 5 main growth team
        assert "ManagerAgent" in names
        assert "MarketingAgent" in names
        assert "ProductAgent" in names
        assert "DesignerAgent" in names
        assert "SoftwareAgent" in names

    def test_catalog_categories_correct(self):
        """Verify agent categories are correctly assigned."""
        catalog = agent_catalog()
        main_team = [e for e in catalog if e["category"] == "main_growth_team"]
        domain = [e for e in catalog if e["category"] == "domain_specialist"]
        assert len(main_team) == 5
        assert len(domain) == 8

    def test_assert_permission_blocks_unauthorised(self):
        with pytest.raises(AgentPermissionError):
            assert_permission("OpportunityPrioritizationAgent", "propose_action")
        with pytest.raises(AgentPermissionError):
            assert_permission("GrowthDiscoveryAgent", "execute_action")

    def test_base_agent_helper_enforces_gate(self, db_session):
        class RogueAgent(BaseGrowthAgent):
            NAME = "OpportunityPrioritizationAgent"  # lacks propose_action

            def _run(self, ctx, result):
                from backend.app.services import action_service

                self._propose_phase4_action(
                    action_service,
                    db=db_session,
                    merchant_id=uuid.uuid4(),
                    action_type="send_campaign",
                    payload={},
                )

        rogue = RogueAgent()
        result = rogue.execute(
            AgentContext(db=db_session, merchant_id=uuid.uuid4())
        )
        assert result.status == "failed"
        assert any("PERMISSION_DENIED" in e for e in result.errors)


# ────────────────────────────────────────────────────────────────────────────
# Orchestrator behaviour
# ────────────────────────────────────────────────────────────────────────────


class TestOrchestrator:
    def test_unknown_merchant_rejected(self, db_session):
        with pytest.raises(MerchantNotFoundError):
            GrowthAgentOrchestrator(db_session).run(uuid.uuid4())

    def test_invalid_mode_rejected(self, db_session, merchant_with_data):
        with pytest.raises(ValueError):
            GrowthAgentOrchestrator(db_session).run(merchant_with_data.id, mode="yolo")

    def test_fast_run_produces_signals_and_opportunities(
        self, db_session, merchant_with_data
    ):
        summary = GrowthAgentOrchestrator(db_session).run(
            merchant_with_data.id, mode="fast"
        )
        assert summary.status == "completed"
        assert summary.totals["signals_detected"] > 0
        assert summary.totals["opportunities_created"] > 0
        statuses = {a["status"] for a in summary.agents_run}
        assert "failed" not in statuses

    def test_deep_run_full_pipeline(self, db_session, merchant_with_data):
        summary = GrowthAgentOrchestrator(db_session).run(
            merchant_with_data.id, mode="deep"
        )
        names = [a["agent"] for a in summary.agents_run]
        assert len(names) == 8
        assert summary.totals["actions_proposed"] >= 1
        assert summary.totals["experiments_proposed"] >= 1
        assert summary.totals["insights_generated"] > 0

    def test_failure_isolation_partial_results(self, db_session, merchant_with_data, monkeypatch):
        from backend.app.agents.campaign_strategist import CampaignStrategistAgent

        def boom(self, ctx, result):
            raise RuntimeError("simulated strategist crash")

        monkeypatch.setattr(CampaignStrategistAgent, "_run", boom)
        summary = GrowthAgentOrchestrator(db_session).run(
            merchant_with_data.id, mode="deep"
        )
        by_name = {a["agent"]: a["status"] for a in summary.agents_run}
        assert by_name["CampaignStrategistAgent"] == "failed"
        assert by_name["PaymentRecoveryAgent"] == "completed"
        assert summary.status == "partial_success"
        assert summary.totals["failed_agents"] == 1
        # healthy agents' work survived the failed agent's rollback
        assert summary.totals["signals_detected"] > 0

    def test_all_agents_failing_reports_failed(self, db_session, merchant_with_data, monkeypatch):
        def boom(self, ctx, result):
            raise RuntimeError("total outage")

        # patch each CONCRETE class — base-class patching is shadowed by overrides
        classes = {type(agent) for agent in AGENT_INSTANCES.values()}
        for cls in classes:
            monkeypatch.setattr(cls, "_run", boom)

        summary = GrowthAgentOrchestrator(db_session).run(merchant_with_data.id)
        assert summary.status == "failed"

    def test_repeated_runs_reinforce_not_duplicate(self, db_session, merchant_with_data):
        orch = GrowthAgentOrchestrator(db_session)
        orch.run(merchant_with_data.id, mode="fast")
        opps_after_first = len(
            list(
                db_session.scalars(
                    select(GrowthOpportunity).where(
                        GrowthOpportunity.merchant_id == merchant_with_data.id
                    )
                ).all()
            )
        )
        orch.run(merchant_with_data.id, mode="fast")
        opps_after_second = len(
            list(
                db_session.scalars(
                    select(GrowthOpportunity).where(
                        GrowthOpportunity.merchant_id == merchant_with_data.id
                    )
                ).all()
            )
        )
        assert opps_after_second == opps_after_first


# ────────────────────────────────────────────────────────────────────────────
# AgentRun audit trail (Feature 14)
# ────────────────────────────────────────────────────────────────────────────


class TestAgentRunAudit:
    def test_every_agent_run_persisted_with_metadata(self, db_session, merchant_with_data):
        summary = GrowthAgentOrchestrator(db_session).run(merchant_with_data.id, mode="deep")
        runs = list(
            db_session.scalars(
                select(AgentRun).where(
                    AgentRun.orchestrator_run_id == summary.orchestrator_run_id
                )
            ).all()
        )
        assert len(runs) == 8
        for run in runs:
            assert run.started_at is not None
            assert run.completed_at is not None
            assert run.total_latency_ms >= 0
            # provider NAME may be recorded (never the key itself)
            assert getattr(run.llm_provider, "value", run.llm_provider) in (
                None, "openai", "groq",
            )
            assert isinstance(run.llm_model, str)
            assert "key" not in run.llm_model.lower()
            assert isinstance(run.tools_used, list)

    def test_failed_run_records_error(self, db_session, merchant_with_data, monkeypatch):
        from backend.app.agents.experiment_agent import ExperimentAgent

        def boom(self, ctx, result):
            raise RuntimeError("kaboom")

        monkeypatch.setattr(ExperimentAgent, "_run", boom)
        summary = GrowthAgentOrchestrator(db_session).run(merchant_with_data.id, mode="deep")
        run_row = next(
            r
            for r in db_session.scalars(
                select(AgentRun).where(
                    AgentRun.orchestrator_run_id == summary.orchestrator_run_id,
                    AgentRun.agent_name == "ExperimentAgent",
                )
            ).all()
        )
        assert getattr(run_row.status, "value", run_row.status) == "failed"
        assert any("kaboom" in str(err) for err in (run_row.errors or []))

    def test_no_secrets_in_stored_payloads(self, db_session, merchant_with_data):
        summary = GrowthAgentOrchestrator(db_session).run(merchant_with_data.id, mode="deep")
        runs = list(db_session.scalars(select(AgentRun)).all())
        blob = "".join(
            str(r.input_summary) + str(r.output_summary) + str(r.tools_used)
            for r in runs
        ).lower()
        for token in ("api_key", "apikey", "secret", "groq_api_key", "password"):
            assert token not in blob, f"leaked {token} in agent_runs"


# ────────────────────────────────────────────────────────────────────────────
# Phase 4 integration — proposals → approval → execution
# ────────────────────────────────────────────────────────────────────────────


class TestPhase4Integration:
    def test_proposed_actions_start_requested_and_need_human(self, db_session, merchant_with_data):
        summary = GrowthAgentOrchestrator(db_session).run(merchant_with_data.id, mode="deep")
        assert summary.totals["actions_proposed"] >= 1
        actions = list(
            db_session.scalars(
                select(AgentAction).where(
                    AgentAction.merchant_id == merchant_with_data.id
                )
            ).all()
        )
        assert all(a.requested_by.startswith("agent:") for a in actions)
        assert all(str(a.status) == "requested" for a in actions)

    def test_human_approval_then_execution_flow(self, db_session, merchant_with_data):
        GrowthAgentOrchestrator(db_session).run(merchant_with_data.id, mode="deep")
        action = db_session.scalars(
            select(AgentAction).where(
                AgentAction.merchant_id == merchant_with_data.id,
                AgentAction.action_type == "retry_payment",
            )
        ).first()
        assert action is not None

        approved = approve_action(db_session, action.id, actor="human_merchant")
        db_session.flush()
        assert getattr(approved.status, "value", approved.status) == "approved"
        assert approved.approved_by == "human_merchant"

        exec_result = execute_action(db_session, action.id, actor="human_merchant")
        # RAZORPAY_ENABLED=false ⇒ honest refusal, never fake success
        assert exec_result.success is False
        assert exec_result.error in ("RAZORPAY_DISABLED", "RAZORPAY_NOT_CONFIGURED")

    def test_guardrails_block_oversized_proposal_at_approval(self, db_session, merchant_with_data):
        """Even an agent-proposed discount cannot exceed guardrail bounds."""
        from backend.app.services.action_service import create_action, InvalidTransitionError

        action = create_action(
            db_session,
            merchant_id=merchant_with_data.id,
            action_type="create_discount",
            input_payload={
                "percentage": 30,
                "proposed_amount": 999999,
                "metadata": {"source_agent": "test"},
            },
            requested_by="agent:test",
        )
        db_session.flush()
        with pytest.raises(InvalidTransitionError, match="GUARDRAIL_REJECTED"):
            approve_action(db_session, action.id, actor="human")

    def test_retry_proposal_idempotent_across_runs(self, db_session, merchant_with_data):
        orch = GrowthAgentOrchestrator(db_session)
        s1 = orch.run(merchant_with_data.id, mode="deep")
        s2 = orch.run(merchant_with_data.id, mode="deep")
        retries = list(
            db_session.scalars(
                select(AgentAction).where(
                    AgentAction.merchant_id == merchant_with_data.id,
                    AgentAction.action_type == "retry_payment",
                )
            ).all()
        )
        # only ONE live retry proposal per payment even after repeated runs
        internal_ids = [
            (a.input_payload or {}).get("metadata", {}).get("internal_payment_id")
            for a in retries
        ]
        assert len(internal_ids) == len(set(internal_ids))


# ────────────────────────────────────────────────────────────────────────────
# Cross-merchant isolation through the whole pipeline
# ────────────────────────────────────────────────────────────────────────────


class TestCrossTenantIsolation:
    def test_orchestrator_scoped_to_single_merchant(self, db_session, merchant_with_data):
        other = make_merchant(db_session)
        GrowthAgentOrchestrator(db_session).run(merchant_with_data.id, mode="deep")

        other_opps = list(
            db_session.scalars(
                select(GrowthOpportunity).where(GrowthOpportunity.merchant_id == other.id)
            ).all()
        )
        assert other_opps == []
        other_actions = list(
            db_session.scalars(
                select(AgentAction).where(AgentAction.merchant_id == other.id)
            ).all()
        )
        assert other_actions == []

        other_summary = GrowthAgentOrchestrator(db_session).run(other.id, mode="fast")
        assert other_summary.totals["signals_detected"] == 0
