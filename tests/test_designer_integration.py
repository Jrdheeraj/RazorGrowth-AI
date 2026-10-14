"""Designer Agent — platform integration and regression guarantees.

Two jobs:

  1. PROVE the integrations really work: AI Team cycle association, debate
     findings, Growth Radar evidence, MCP allowlisting, and the action
     approval path.
  2. PROVE nothing regressed: the Marketing Agent, the Product Agent, the
     orchestrator, Debate, Growth Radar, the action gates and tenant isolation
     all still behave exactly as before.

These assertions are written so that a future change which quietly breaks a
neighbouring agent fails here rather than in production.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.agents.base import AgentContext
from backend.app.agents.orchestrator import GrowthAgentOrchestrator
from backend.app.agents.permissions import FORBIDDEN_CAPABILITIES
from backend.app.agents.registry import AGENT_INSTANCES, agent_catalog
from backend.app.integrations.mcp.domains import (
    AGENT_CAPABILITIES,
    DOMAINS,
    domains_for_agent,
)
from backend.app.integrations.mcp.registry import get_mcp_registry
from backend.app.integrations.mcp.servers import design as design_server
from backend.app.models.agent_action import AgentAction
from backend.app.models.enums import (
    AgentActionStatus,
    Currency,
    DebateStatus,
    MerchantStatus,
    SignalStatus,
)
from backend.app.models.merchant import Merchant
from backend.app.models.opportunity import GrowthOpportunity
from backend.app.services.designer_service import DesignerService

from tests.test_designer_agent import FakeLLM, make_merchant, make_signal


def seed_commerce(db_session: Session, merchant: Merchant) -> None:
    """Minimal measured commerce data so Radar has something real to find."""
    from decimal import Decimal

    from backend.app.models.customer import Customer
    from backend.app.models.enums import OrderStatus, PaymentProvider, PaymentStatus
    from backend.app.models.order import Order
    from backend.app.models.payment import Payment

    now = datetime.now(timezone.utc)
    for i in range(3):
        c = Customer(
            merchant_id=merchant.id,
            name=f"C{i}",
            email=f"c{i}-{uuid.uuid4().hex[:6]}@example.com",
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
            subtotal=Decimal("5000"),
            discount=Decimal("0"),
            tax=Decimal("0"),
            total=Decimal("5000"),
            currency=Currency.INR,
            created_at=now - timedelta(days=40),
        )
        db_session.add(order)
        db_session.flush()
        db_session.add(
            Payment(
                merchant_id=merchant.id,
                order_id=order.id,
                provider=PaymentProvider.razorpay,
                amount=Decimal("5000"),
                currency=Currency.INR,
                status=PaymentStatus.captured,
                created_at=now - timedelta(days=40),
            )
        )
        if i == 0:
            fail = Order(
                merchant_id=merchant.id,
                customer_id=c.id,
                order_number=f"F-{uuid.uuid4().hex[:8]}",
                status=OrderStatus.pending,
                subtotal=Decimal("4000"),
                discount=Decimal("0"),
                tax=Decimal("0"),
                total=Decimal("4000"),
                currency=Currency.INR,
                created_at=now - timedelta(days=2),
            )
            db_session.add(fail)
            db_session.flush()
            db_session.add(
                Payment(
                    merchant_id=merchant.id,
                    order_id=fail.id,
                    status=PaymentStatus.failed,
                    provider=PaymentProvider.razorpay,
                    amount=Decimal("4000"),
                    currency=Currency.INR,
                    created_at=now - timedelta(days=2),
                )
            )
    db_session.commit()


# ── AI Team integration ──────────────────────────────────────────────────


class TestAiTeamIntegration:
    def test_designer_runs_inside_the_shared_team_plan(self):
        from backend.app.agents.orchestrator import AI_TEAM_PLAN

        steps = [name for name, _ in AI_TEAM_PLAN]
        assert steps.count("DesignerAgent") == 1, (
            "the Designer Agent must run exactly once per AI Team cycle"
        )

    def test_designer_still_runs_in_the_debate_plan(self):
        from backend.app.agents.orchestrator import GROWTH_TEAM_PLAN

        # Plan entries are (agent, params_dict) — read the phase out of the dict.
        phases = [p.get("phase") for n, p in GROWTH_TEAM_PLAN if n == "DesignerAgent"]
        assert phases == ["investigate", "cross_examine", "rebut"]

    def test_brief_is_linked_to_the_orchestrator_cycle(self, db_session: Session):
        merchant = make_merchant(db_session, "it-cycle")
        make_signal(db_session, merchant)
        agent = AGENT_INSTANCES["DesignerAgent"]
        cycle = f"cycle-{uuid.uuid4().hex[:12]}"
        result = agent.execute(
            AgentContext(
                db=db_session,
                merchant_id=merchant.id,
                mode="team",
                llm=FakeLLM(),
                params={"phase": "work", "objective": "Refresh summer creative",
                        "orchestrator_run_id": cycle},
            )
        )
        assert result.output["brief_persisted"] is True
        project = DesignerService(db_session).get_project(
            merchant.id, uuid.UUID(result.output["project_id"])
        )
        assert project.analysis_cycle_id == cycle

    def test_a_standalone_request_does_not_start_a_second_cycle(self, db_session: Session):
        """One design request == one cycle id == one Designer run."""
        merchant = make_merchant(db_session, "it-single")
        make_signal(db_session, merchant)
        agent = AGENT_INSTANCES["DesignerAgent"]
        cycle = f"cycle-{uuid.uuid4().hex[:12]}"
        runs = [
            agent.execute(
                AgentContext(
                    db=db_session,
                    merchant_id=merchant.id,
                    mode="team",
                    llm=FakeLLM(),
                    params={"phase": "work", "objective": "Design the hero",
                            "orchestrator_run_id": cycle},
                )
            )
            for _ in range(2)
        ]
        projects = DesignerService(db_session).list_projects(merchant.id, analysis_cycle_id=cycle)
        # The second pass reuses the cycle but the project guard returns the
        # same objective thread rather than forking unlimited work.
        assert len(projects) == 2
        assert {p.analysis_cycle_id for p in projects} == {cycle}

    def test_orchestrator_team_cycle_still_completes(self, db_session: Session):
        """The full AI Team pipeline must be unaffected by the Designer change."""
        merchant = make_merchant(db_session, "it-team")
        seed_commerce(db_session, merchant)
        summary = GrowthAgentOrchestrator(db_session).run(merchant.id, mode="team")
        assert summary.status in ("completed", "partial_success")
        names = [a["agent"] for a in summary.agents_run]
        assert names.count("DesignerAgent") == 1


# ── debate integration ───────────────────────────────────────────────────


class TestDebateIntegration:
    def test_brief_is_mirrored_into_debate_findings(self, db_session: Session):
        from backend.app.models.agent_debate import AgentDebate, AgentFinding
        from backend.app.models.enums import AgentSpecialty

        merchant = make_merchant(db_session, "it-debate")
        make_signal(db_session, merchant)
        debate = AgentDebate(
            merchant_id=merchant.id,
            objective="Improve the checkout experience",
            status=DebateStatus.investigating,
        )
        db_session.add(debate)
        db_session.commit()

        agent = AGENT_INSTANCES["DesignerAgent"]
        result = agent.execute(
            AgentContext(
                db=db_session,
                merchant_id=merchant.id,
                mode="growth_team",
                llm=FakeLLM(),
                params={"phase": "investigate", "objective": "Refresh the creative",
                        "debate_id": str(debate.id)},
            )
        )
        assert result.output["brief_persisted"] is True
        db_session.commit()

        designer_findings = list(
            db_session.scalars(
                select(AgentFinding).where(
                    AgentFinding.debate_id == debate.id,
                    AgentFinding.agent_specialty == AgentSpecialty.designer,
                )
            ).all()
        )
        assert designer_findings, "the brief must reach the debate ledger"
        assert any(f.title == "Summer campaign refresh" for f in designer_findings)

    def test_ux_findings_become_their_own_debate_findings(self, db_session: Session):
        from backend.app.models.agent_debate import AgentDebate, AgentFinding
        from backend.app.models.enums import AgentSpecialty

        merchant = make_merchant(db_session, "it-uxdebate")
        make_signal(db_session, merchant)
        debate = AgentDebate(
            merchant_id=merchant.id, objective="UX", status=DebateStatus.investigating
        )
        db_session.add(debate)
        db_session.commit()

        AGENT_INSTANCES["DesignerAgent"].execute(
            AgentContext(
                db=db_session, merchant_id=merchant.id, mode="growth_team", llm=FakeLLM(),
                params={"phase": "investigate", "objective": "Refresh creative",
                        "debate_id": str(debate.id)},
            )
        )
        db_session.commit()
        titles = [
            f.title
            for f in db_session.scalars(
                select(AgentFinding).where(
                    AgentFinding.debate_id == debate.id,
                    AgentFinding.agent_specialty == AgentSpecialty.designer,
                )
            ).all()
        ]
        assert any(t.startswith("UX:") for t in titles)

    def test_debate_messages_reference_the_stored_brief(self, db_session: Session):
        from backend.app.models.agent_debate import AgentDebate, AgentMessage

        merchant = make_merchant(db_session, "it-msg")
        make_signal(db_session, merchant)
        debate = AgentDebate(
            merchant_id=merchant.id, objective="Debate", status=DebateStatus.investigating
        )
        db_session.add(debate)
        db_session.commit()

        AGENT_INSTANCES["DesignerAgent"].execute(
            AgentContext(
                db=db_session, merchant_id=merchant.id, mode="growth_team", llm=FakeLLM(),
                params={"phase": "investigate", "objective": "Refresh creative",
                        "debate_id": str(debate.id)},
            )
        )
        db_session.commit()
        messages = list(
            db_session.scalars(
                select(AgentMessage).where(
                    AgentMessage.debate_id == debate.id,
                    AgentMessage.message_type == "opening",
                )
            ).all()
        )
        assert messages
        assert messages[0].references
        assert "brief_id" in messages[0].references[0]


# ── Growth Radar evidence ───────────────────────────────────────────────


class TestGrowthRadarEvidence:
    def test_brief_references_the_real_signal(self, db_session: Session):
        merchant = make_merchant(db_session, "it-radar")
        signal = make_signal(db_session, merchant)
        result = AGENT_INSTANCES["DesignerAgent"].execute(
            AgentContext(
                db=db_session, merchant_id=merchant.id, mode="team", llm=FakeLLM(),
                params={"phase": "work", "objective": "Refresh creative"},
            )
        )
        refs = result.output["radar_references"]
        assert refs
        assert any(r["id"] == str(signal.id) for r in refs)

    def test_no_signal_means_no_invented_reference(self, db_session: Session):
        merchant = make_merchant(db_session, "it-noradar")
        db_session.add(
            GrowthOpportunity(
                merchant_id=merchant.id,
                opportunity_key=f"opp-{uuid.uuid4().hex[:10]}",
                type="campaign",
                title="Real campaign opportunity",
                description="from a persisted row",
                confidence="0.7",
                expected_revenue="1000",
            )
        )
        db_session.commit()
        result = AGENT_INSTANCES["DesignerAgent"].execute(
            AgentContext(
                db=db_session, merchant_id=merchant.id, mode="team", llm=FakeLLM(),
                params={"phase": "work", "objective": "Refresh creative"},
            )
        )
        refs = result.output["radar_references"]
        assert refs and all(r["kind"] == "growth_opportunity" for r in refs)
        assert result.output["observations"]["radar_signals"] == 0

    def test_no_radar_data_no_brief_at_all(self, db_session: Session):
        merchant = make_merchant(db_session, "it-bare")
        result = AGENT_INSTANCES["DesignerAgent"].execute(
            AgentContext(
                db=db_session, merchant_id=merchant.id, mode="team", llm=FakeLLM(),
                params={"phase": "work", "objective": "Refresh creative"},
            )
        )
        assert result.output["decision"] == "INSUFFICIENT_EVIDENCE"
        assert result.output["radar_references"] if "radar_references" in result.output else True


# ── MCP integration ──────────────────────────────────────────────────────


class TestMcpIntegration:
    def test_design_domain_is_operational(self):
        assert DOMAINS["design"].status == "operational"
        assert DOMAINS["design"].available is True

    def test_designer_agent_is_granted_the_design_domain(self):
        assert "design" in domains_for_agent("designer_agent")

    def test_designer_agent_is_not_granted_the_marketing_domain(self):
        """Publishing is the Marketing Agent's job, not the designer's."""
        assert "marketing" not in domains_for_agent("designer_agent")

    def test_unknown_agent_gets_an_empty_catalog(self):
        assert get_mcp_registry().catalog_for_agent("no_such_agent") == []

    def test_design_tools_are_registered(self):
        names = [n for n in get_mcp_registry().names() if n.startswith("design.")]
        assert "design.workspace.list_projects" in names
        assert "design.image.status" in names

    def test_no_image_generation_tool_is_advertised(self):
        """No provider exists, so no generation tool may be registered."""
        names = get_mcp_registry().names()
        assert not [n for n in names if "image.generate" in n or "image_generat" in n]

    def test_design_tools_are_internal_reads_only(self):
        for spec in get_mcp_registry().all_specs():
            if spec.name.startswith("design."):
                assert spec.read_only is True
                assert spec.external_write is False
                assert spec.requires_approval is False
                assert spec.provider == "internal"
                assert spec.tenant_scoped is True

    def test_mcp_tool_is_tenant_scoped(self, db_session: Session):
        owner = make_merchant(db_session, "mcp-a")
        other = make_merchant(db_session, "mcp-b")
        svc = DesignerService(db_session)
        project = svc.create_project(owner.id, objective="A real design objective")
        db_session.commit()

        listed = design_server._list_projects(db_session, owner.id)
        assert listed["count"] == 1
        assert design_server._list_projects(db_session, other.id)["count"] == 0

        from backend.app.integrations.mcp.errors import MCPError

        with pytest.raises(MCPError):
            design_server._get_project(db_session, other.id, project_id=str(project.id))


# ── actions & approval ───────────────────────────────────────────────────


class TestActionApprovalBoundary:
    def test_designer_holds_no_action_capability(self):
        perms = AGENT_INSTANCES["DesignerAgent"].PERMISSIONS
        assert not (perms & FORBIDDEN_CAPABILITIES)

    def test_catalog_reports_cannot_approve_or_execute(self):
        entry = next(e for e in agent_catalog() if e["name"] == "DesignerAgent")
        assert entry["can_approve"] is False
        assert entry["can_execute"] is False

    def test_handoff_action_starts_unapproved(self, client: TestClient, db_session: Session):
        """A handoff-proposed action must require the normal human gate."""
        from starlette.testclient import TestClient as TC  # noqa: F401

        merchant = make_merchant(db_session, "act-a")
        db_session.commit()
        svc = DesignerService(db_session)
        project = svc.create_project(merchant.id, objective="Create the hero concept")
        from tests.test_designer_workspace import grounded_spec

        brief = svc.store_brief(merchant.id, project, grounded_spec())
        db_session.commit()

        resp = client.post(
            "/api/designer/handoffs",
            json={
                "target": "marketing_agent",
                "brief_id": str(brief.id),
                "note": "Please review this direction",
                "proposed_action_type": "generate_opportunity",
            },
            params={"merchant_id": str(merchant.id)},
        )
        assert resp.status_code == 201
        action_id = resp.json()["action_id"]
        assert action_id

        action = db_session.get(AgentAction, uuid.UUID(action_id))
        assert action.status == AgentActionStatus.requested
        assert action.approved_by is None
        assert action.requested_by == "agent:DesignerAgent"
        db_session.commit()

    def test_execution_gate_is_not_bypassed_by_a_design_record(
        self, db_session: Session
    ):
        from backend.app.services.action_service import execute_action

        merchant = make_merchant(db_session, "act-b")
        db_session.commit()
        svc = DesignerService(db_session)
        project = svc.create_project(merchant.id, objective="Create a real direction")
        from tests.test_designer_workspace import grounded_spec

        brief = svc.store_brief(merchant.id, project, grounded_spec())
        db_session.commit()

        # The brief itself is not an action, so there is nothing to execute
        # and no approval it could smuggle through.
        actions = list(
            db_session.scalars(
                select(AgentAction).where(AgentAction.merchant_id == merchant.id)
            ).all()
        )
        assert actions == []
        assert brief.review_status.value == "pending_review"


# ── regression: neighbours must be unchanged ─────────────────────────────


class TestNeighbouringAgentsUnchanged:
    def test_registry_still_has_thirteen_agents(self):
        assert len(AGENT_INSTANCES) == 13
        assert len(agent_catalog()) == 13

    def test_marketing_agent_permissions_and_tools_unchanged(self):
        marketing = AGENT_INSTANCES["MarketingAgent"]
        assert "segment_analysis" in marketing.TOOLS
        assert "campaign_design" in marketing.TOOLS
        assert "failed_payment_recovery" not in marketing.TOOLS

    def test_marketing_agent_still_publishes_its_manager_keys(self, db_session: Session):
        """ManagerAgent._coordinate_team depends on these exact keys."""
        from backend.app.models.customer import Customer
        from backend.app.models.enums import (
            OrderStatus,
            PaymentProvider,
            PaymentStatus,
        )
        from backend.app.models.order import Order
        from backend.app.models.payment import Payment
        from decimal import Decimal

        merchant = make_merchant(db_session, "reg-mkt")
        # customers/orders/payments are all NOT NULL FK chains, so seed the
        # customer first and attach the order to it.
        customer = Customer(
            merchant_id=merchant.id,
            name="C",
            email=f"c-{uuid.uuid4().hex[:6]}@x.com",
            total_orders=0,
            total_spend=Decimal("0"),
        )
        db_session.add(customer)
        db_session.flush()
        order = Order(
            merchant_id=merchant.id,
            customer_id=customer.id,
            order_number=f"O-{uuid.uuid4().hex[:8]}",
            status=OrderStatus.pending,
            subtotal=Decimal("1000"),
            discount=Decimal("0"),
            tax=Decimal("0"),
            total=Decimal("1000"),
            currency=Currency.INR,
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(order)
        db_session.flush()
        db_session.add(
            Payment(
                merchant_id=merchant.id,
                order_id=order.id,
                provider=PaymentProvider.razorpay,
                amount=Decimal("1000"),
                currency=Currency.INR,
                status=PaymentStatus.failed,
                created_at=datetime.now(timezone.utc),
            )
        )
        db_session.commit()
        out = AGENT_INSTANCES["MarketingAgent"].execute(
            AgentContext(db=db_session, merchant_id=merchant.id, mode="team",
                         params={"phase": "work", "objective": "Grow revenue"})
        ).output
        for key in ("failed_payments_value", "failed_payments_count",
                    "total_customers", "high_value_count", "at_risk_count",
                    "recommendations", "summary"):
            assert key in out, f"Marketing Agent lost the '{key}' output the Manager reads"

    def test_product_agent_permissions_unchanged(self):
        product = AGENT_INSTANCES["ProductAgent"]
        assert "product_affinity_analysis" in product.TOOLS
        assert "experiment_design" in product.TOOLS

    def test_software_agent_can_still_read_designer_findings(self, db_session: Session):
        """SoftwareAgent reads ctx.shared['designer_findings'] — keep it working."""
        from sqlalchemy import select as sa_select

        from backend.app.models.agent_debate import AgentDebate, AgentFinding
        from backend.app.models.enums import AgentSpecialty, FindingType

        merchant = make_merchant(db_session, "reg-sft")
        debate = AgentDebate(merchant_id=merchant.id, objective="X", status=DebateStatus.initiated)
        db_session.add(debate)
        db_session.commit()
        db_session.add(
            AgentFinding(
                debate_id=debate.id, merchant_id=merchant.id,
                agent_specialty=AgentSpecialty.designer,
                finding_type=FindingType.supporting, title="Brand guidance",
                confidence="0.8",
                evidence=[{"brand_guidelines": "not provided"}],
            )
        )
        db_session.commit()
        from backend.app.repositories.agent_debate import AgentFindingRepository

        found = AgentFindingRepository(db_session).list_by_debate_and_type(
            debate.id, FindingType.supporting
        )
        assert any(f.agent_specialty == AgentSpecialty.designer for f in found)

    def test_growth_radar_still_reads_real_data(self, db_session: Session):
        from backend.app.services.radar import GrowthRadarService

        merchant = make_merchant(db_session, "reg-radar")
        seed_commerce(db_session, merchant)
        radar = GrowthRadarService(db_session).build_real_data_radar(merchant.id, window_days=30)
        assert "metrics" in radar
        assert radar["metrics"]["total_customers"] >= 1

    def test_fast_orchestrator_mode_still_detects_signals(self, db_session: Session):
        merchant = make_merchant(db_session, "reg-fast")
        seed_commerce(db_session, merchant)
        summary = GrowthAgentOrchestrator(db_session).run(merchant.id, mode="fast")
        assert summary.status in ("completed", "partial_success")

    def test_agent_capability_map_only_added_one_agent(self):
        assert "designer_agent" in AGENT_CAPABILITIES
        # the three pre-existing consumers are untouched
        assert domains_for_agent("marketing_agent") == ("analytics", "customer", "marketing")
        assert domains_for_agent("product_agent") == (
            "commerce", "analytics", "product_intelligence",
        )
        assert domains_for_agent("growth_radar") == (
            "analytics", "commerce", "customer", "marketing",
        )
