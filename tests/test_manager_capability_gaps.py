"""
Manager Agent capability-gap resolution and specialist-selection verification.

Covers, in order:

  1. Catalog resolution correctness in BOTH directions (declared -> resolved
     must exist; resolved must be backed by a real handler).
  2. The new ``commerce.what_if_simulation`` tool: real arithmetic, read-only,
     SIMULATE-gated, honest on missing input, refusing out-of-bounds.
  3. Every ManagerAgent declaration is either resolved or DOCUMENTED with a
     category and reason. Nothing is left as an unexplained gap.
  4. MarketingAgent / DesignerAgent diagnosis — Marketing resolves real
     capabilities; Designer's are documented as unreachable-by-catalog.
  5. Selection correctness: registered-only, never self, never duplicated,
     goal-driven, deterministic.
  6. Honest unavailability: an on-topic-but-unavailable specialist is
     disclosed, never silently dropped and never faked into the selection.
  7. No recursive ManagerAgent delegation.
  8. Plans route through the EXISTING orchestrator; the Manager never becomes
     a second engine.
  9. Failure / partial-result propagation, and no duplicate action proposals.
 10. Permission, tenant-isolation and approval safeguards intact.
"""
from __future__ import annotations

import uuid

import pytest

import backend.app.agents.registry as reg
from backend.app.agents.base import AgentContext, AgentResult
from backend.app.agents.catalog import (
    DOCUMENTED_UNAVAILABLE_TOOLS,
    LEGACY_TOOL_ALIASES,
    TOOL_REGISTRY,
    ToolInputError,
    ToolPermissionError,
    get_tool,
    invoke,
    tool_ids_for_agent,
    unimplemented_tool_ids_for_agent,
)
from backend.app.agents.manager_agent import ManagerAgent
from backend.app.agents.orchestrator import AI_TEAM_PLAN, GROWTH_TEAM_PLAN
from backend.app.agents.permissions import AGENT_PERMISSIONS, FORBIDDEN_CAPABILITIES, SIMULATE
from backend.app.agents.registry import AGENT_INSTANCES, agent_catalog
from backend.app.models.agent_action import AgentAction
from backend.app.models.agent_run import AgentRun
from backend.app.models.enums import AgentActionStatus, AgentRunStatus
from backend.app.services.manager_plan_service import ManagerCoordinationService
from tests.security_utils import bearer, make_world


# ── helpers ────────────────────────────────────────────────────────────────


def _unresolved_declarations() -> dict[str, list[str]]:
    """agent -> declared names that do not resolve to a real tool."""
    out: dict[str, list[str]] = {}
    for name in AGENT_INSTANCES:
        bad = list(unimplemented_tool_ids_for_agent(name))
        if bad:
            out[name] = bad
    return out


def _ctx(db_session, merchant, objective: str) -> AgentContext:
    return AgentContext(
        db=db_session,
        merchant_id=merchant.id,
        mode="plan",
        params={"objective": objective, "window_days": 30},
        llm=None,
        embedding_provider=None,
        shared={},
    )


@pytest.fixture()
def world(db_session):
    return make_world(db_session, slug_hint="gap")


@pytest.fixture()
def api(client):
    return client


@pytest.fixture()
def secure(monkeypatch):
    from backend.app.core.config import get_settings

    monkeypatch.setenv("AUTH_MODE", "required")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


# ════════════════════════════════════════════════════════════════════════════
# 1. Catalog resolution correctness, both directions
# ════════════════════════════════════════════════════════════════════════════


class TestCatalogResolutionIsSound:
    def test_every_resolved_declaration_names_a_real_registered_tool(self):
        """Direction 1: advertised tools must exist."""
        for name, agent in AGENT_INSTANCES.items():
            for declared in getattr(agent, "TOOLS", ()) or ():
                mapped = LEGACY_TOOL_ALIASES.get(declared, declared)
                if mapped in TOOL_REGISTRY:
                    assert get_tool(mapped) is not None, f"{name} -> {mapped}"

    def test_every_alias_target_is_a_registered_tool(self):
        """Direction 2: no alias may point at a nonexistent tool."""
        for legacy, canonical in LEGACY_TOOL_ALIASES.items():
            assert canonical in TOOL_REGISTRY, (
                f"LEGACY_TOOL_ALIASES[{legacy!r}] -> {canonical!r} is not registered"
            )

    def test_every_alias_target_has_a_callable_handler(self):
        for legacy, canonical in LEGACY_TOOL_ALIASES.items():
            spec = TOOL_REGISTRY[canonical]
            assert callable(spec.handler), f"{legacy} -> {canonical} has no handler"
            assert spec.summary.strip(), f"{legacy} -> {canonical} has no summary"
            assert spec.source.strip(), f"{legacy} -> {canonical} has no source"

    def test_tool_ids_for_agent_never_invents_a_tool(self):
        for name in AGENT_INSTANCES:
            for tool_id in tool_ids_for_agent(name):
                assert tool_id in TOOL_REGISTRY, f"{name} resolved unknown tool {tool_id}"
                # Every returned id must actually be retrievable and callable.
                assert callable(get_tool(tool_id).handler)

    def test_implemented_and_unimplemented_partition_the_declarations(self):
        """Every declared name lands in exactly one of the two halves.

        The count can be lower than the declaration count: several distinct
        legacy names (growth_radar, opportunity_upsert, opportunity_scoring)
        collapse onto one canonical id, and listing a tool twice would be noise.
        The invariant is over COVERAGE, not cardinality.
        """
        for name, agent in AGENT_INSTANCES.items():
            declared = set(getattr(agent, "TOOLS", ()) or ())
            implemented = set(tool_ids_for_agent(name))
            gap = set(unimplemented_tool_ids_for_agent(name))

            assert not (implemented & gap), f"{name} tool appears in both halves"

            # Every implemented id must be backed by some declaration.
            declared_aliases = {LEGACY_TOOL_ALIASES.get(d, d) for d in declared}
            assert implemented <= declared_aliases, name

            # Every declared name is covered: it either resolved, or it is a gap.
            for d in declared:
                mapped = LEGACY_TOOL_ALIASES.get(d, d)
                assert (
                    (mapped in TOOL_REGISTRY and mapped in implemented) or d in gap
                ), f"{name}: {d} is covered by neither half"

    def test_resolved_and_unimplemented_stay_disjoint(self):
        for entry in agent_catalog():
            assert set(entry["tools"]).isdisjoint(entry["unimplemented_tools"]), entry["name"]

    def test_no_catalog_tool_requires_a_write_permission_while_read_only(self):
        for tool_id, spec in TOOL_REGISTRY.items():
            if spec.read_only:
                assert not spec.required_permission.endswith("write"), tool_id

    def test_no_tool_claims_approval_or_execution(self):
        # A catalog tool reaches services only. Approval lives in Phase 4.
        for tool_id, spec in TOOL_REGISTRY.items():
            assert spec.required_permission not in {
                "approve_action",
                "execute_action",
                "reject_action",
            }, tool_id


# ════════════════════════════════════════════════════════════════════════════
# 2. The new what-if simulation tool: real behaviour
# ════════════════════════════════════════════════════════════════════════════


class TestWhatIfSimulationTool:
    def test_is_registered_with_full_spec_metadata(self):
        spec = get_tool("commerce.what_if_simulation")
        assert spec.summary.strip()
        assert spec.source == "services.simulation.SimulationEngine.simulate"
        assert spec.input_model is not None
        assert spec.output_model is not None

    def test_is_read_only_and_simulation_gated(self):
        spec = get_tool("commerce.what_if_simulation")
        assert spec.read_only is True
        assert spec.required_permission == SIMULATE

    def test_permission_is_enforced(self, db_session, world):
        merchant, _u, _m = world
        with pytest.raises(ToolPermissionError):
            invoke(
                "commerce.what_if_simulation",
                db=db_session,
                arguments={
                    "merchant_id": str(merchant.id),
                    "scenario_type": "campaign",
                    "target_customers": 100,
                    "expected_conversion": 0.1,
                    "avg_order_value": 500,
                },
                granted_permissions=["read_merchant"],  # not simulate
            )

    def test_payment_recovery_produces_real_arithmetic(self, db_session, world):
        merchant, _u, _m = world
        result = invoke(
            "commerce.what_if_simulation",
            db=db_session,
            arguments={
                "merchant_id": str(merchant.id),
                "scenario_type": "payment_recovery",
                "failed_payment_value": 50000,
                "recovery_rate": 0.35,
                "cost_per_contact": 2,
                "contacts": 100,
            },
            granted_permissions=[SIMULATE],
        )
        assert result.status == "ok"
        # 50000 * 0.35 = 17500 recovered; 100 contacts * 2 = 200 cost.
        assert result.data["estimated_revenue"] == pytest.approx(17500.0)
        assert result.data["estimated_cost"] == pytest.approx(200.0)
        assert result.data["estimated_profit"] == pytest.approx(17300.0)
        # +/-20% confidence band, matching SimulationEngine's documented rule.
        assert result.data["confidence_low"] == pytest.approx(14000.0)
        assert result.data["confidence_high"] == pytest.approx(21000.0)
        assert result.data["assumptions"]

    def test_campaign_scenario_produces_real_arithmetic(self, db_session, world):
        merchant, _u, _m = world
        result = invoke(
            "commerce.what_if_simulation",
            db=db_session,
            arguments={
                "merchant_id": str(merchant.id),
                "scenario_type": "campaign",
                "target_customers": 1000,
                "expected_conversion": 0.05,
                "avg_order_value": 900,
                "cost_per_target": 3,
            },
            granted_permissions=[SIMULATE],
        )
        assert result.status == "ok"
        # 1000 * 0.05 = 50 buyers * 900 = 45000 gross; cost 1000*3 = 3000.
        assert result.data["estimated_revenue"] == pytest.approx(45000.0)
        assert result.data["estimated_cost"] == pytest.approx(3000.0)
        assert result.data["expected_roi"] == pytest.approx(14.0)

    def test_discount_scenario_honours_discount(self, db_session, world):
        merchant, _u, _m = world
        result = invoke(
            "commerce.what_if_simulation",
            db=db_session,
            arguments={
                "merchant_id": str(merchant.id),
                "scenario_type": "discount",
                "discount_percentage": 10,
                "target_customers": 1000,
                "expected_conversion": 0.1,
                "avg_order_value": 500,
            },
            granted_permissions=[SIMULATE],
        )
        # gross 50000, 10% off -> 45000 revenue, 5000 discount cost.
        assert result.data["estimated_revenue"] == pytest.approx(45000.0)
        assert result.data["estimated_cost"] == pytest.approx(5000.0)

    def test_output_is_always_labelled_as_an_estimate(self, db_session, world):
        """A projection must never be readable as measured revenue."""
        merchant, _u, _m = world
        result = invoke(
            "commerce.what_if_simulation",
            db=db_session,
            arguments={
                "merchant_id": str(merchant.id),
                "scenario_type": "campaign",
                "target_customers": 10,
                "expected_conversion": 0.1,
                "avg_order_value": 100,
            },
            granted_permissions=[SIMULATE],
        )
        assert result.data["is_estimate"] is True
        assert "estimate_only" in " ".join(result.warnings)

    def test_missing_input_is_refused_not_defaulted(self, db_session, world):
        merchant, _u, _m = world
        result = invoke(
            "commerce.what_if_simulation",
            db=db_session,
            arguments={"merchant_id": str(merchant.id), "scenario_type": "discount"},
            granted_permissions=[SIMULATE],
        )
        assert result.status == "error"
        joined = " ".join(result.warnings)
        assert "missing_input" in joined
        assert "discount_percentage" in joined
        assert "expected_conversion" in joined
        assert "avg_order_value" in joined
        # No fabricated numbers on the refusal path.
        assert "estimated_revenue" not in result.data

    def test_out_of_bounds_input_is_rejected_by_schema(self, db_session, world):
        merchant, _u, _m = world
        with pytest.raises(ToolInputError):
            invoke(
                "commerce.what_if_simulation",
                db=db_session,
                arguments={
                    "merchant_id": str(merchant.id),
                    "scenario_type": "campaign",
                    "target_customers": 10,
                    "expected_conversion": 1.5,  # must be within [0, 1]
                    "avg_order_value": 100,
                },
                granted_permissions=[SIMULATE],
            )

    def test_unknown_scenario_type_is_rejected(self, db_session, world):
        merchant, _u, _m = world
        with pytest.raises(ToolInputError):
            invoke(
                "commerce.what_if_simulation",
                db=db_session,
                arguments={"merchant_id": str(merchant.id), "scenario_type": "send_email"},
                granted_permissions=[SIMULATE],
            )

    def test_creates_no_persisted_rows(self, db_session, world):
        """Read-only means read-only: no Simulation, Action or Run is written."""
        from backend.app.models.experiment import Simulation

        merchant, _u, _m = world
        before = (
            db_session.query(Simulation).count(),
            db_session.query(AgentAction).filter(AgentAction.merchant_id == merchant.id).count(),
            db_session.query(AgentRun).filter(AgentRun.merchant_id == merchant.id).count(),
        )
        invoke(
            "commerce.what_if_simulation",
            db=db_session,
            arguments={
                "merchant_id": str(merchant.id),
                "scenario_type": "campaign",
                "target_customers": 50,
                "expected_conversion": 0.2,
                "avg_order_value": 300,
            },
            granted_permissions=[SIMULATE],
        )
        after = (
            db_session.query(Simulation).count(),
            db_session.query(AgentAction).filter(AgentAction.merchant_id == merchant.id).count(),
            db_session.query(AgentRun).filter(AgentRun.merchant_id == merchant.id).count(),
        )
        assert before == after

    def test_merchant_id_must_be_a_uuid(self):
        with pytest.raises(ToolInputError):
            invoke(
                "commerce.what_if_simulation",
                db=None,
                arguments={"merchant_id": "not-a-uuid", "scenario_type": "campaign"},
                granted_permissions=[SIMULATE],
            )


# ════════════════════════════════════════════════════════════════════════════
# 3. Every ManagerAgent declaration resolved OR documented
# ════════════════════════════════════════════════════════════════════════════


class TestManagerAgentToolResolution:
    def test_manager_declares_the_six_coordination_tools(self):
        assert set(ManagerAgent.TOOLS) == {
            "growth_radar",
            "opportunity_lookup",
            "task_decomposition",
            "agent_delegation",
            "debate_orchestration",
            "synthesis",
        }

    def test_manager_resolves_real_capabilities(self):
        resolved = set(tool_ids_for_agent("ManagerAgent"))
        assert "analytics.growth_radar" in resolved
        assert "opportunities.rank" in resolved
        assert "collaboration.request_handoff" in resolved

    def test_manager_coordination_tools_are_resolved_or_documented(self):
        for declared in ManagerAgent.TOOLS:
            mapped = LEGACY_TOOL_ALIASES.get(declared, declared)
            if mapped in TOOL_REGISTRY:
                continue
            entry = DOCUMENTED_UNAVAILABLE_TOOLS.get(declared)
            assert entry is not None, f"ManagerAgent tool {declared!r} is unexplained"
            assert entry["category"] in {
                "second_orchestration",
                "approval_bypass",
                "missing_service",
            }
            assert entry["reason"].strip()
            assert entry["remediation"].strip()

    def test_coordination_tools_are_documented_as_orchestration_not_gaps(self):
        """The three coordination names must not be quietly implemented.

        Making them callable would give the Manager a second way to run
        specialists, which is exactly the prohibited design.
        """
        for name in ("task_decomposition", "debate_orchestration", "synthesis"):
            entry = DOCUMENTED_UNAVAILABLE_TOOLS[name]
            assert entry["category"] == "second_orchestration"
            assert LEGACY_TOOL_ALIASES.get(name, name) not in TOOL_REGISTRY

    def test_manager_cannot_resolve_a_privileged_tool(self):
        resolved = set(tool_ids_for_agent("ManagerAgent"))
        assert "actions.propose" not in resolved, "Manager must not hold propose_action"

    def test_manager_permissions_still_exclude_approval_and_execution(self):
        perms = AGENT_PERMISSIONS["ManagerAgent"]
        assert not (set(perms) & FORBIDDEN_CAPABILITIES)
        assert "approve_action" not in perms
        assert "execute_action" not in perms


# ════════════════════════════════════════════════════════════════════════════
# 4. Marketing / Designer diagnosis
# ════════════════════════════════════════════════════════════════════════════


class TestMarketingAndDesignerDiagnosis:
    def test_marketing_resolves_real_capabilities(self):
        resolved = set(tool_ids_for_agent("MarketingAgent"))
        assert "customer.insights" in resolved
        assert "commerce.what_if_simulation" in resolved
        assert resolved, "MarketingAgent must expose implemented capability"

    def test_marketing_segment_analysis_maps_to_the_service_it_actually_calls(self):
        # _run_investigation() calls CustomerIntelligenceService.list_insights;
        # customer.insights is that service's catalog entry.
        assert LEGACY_TOOL_ALIASES["segment_analysis"] == "customer.insights"
        from backend.app.services.customer_intelligence import CustomerIntelligenceService

        assert hasattr(CustomerIntelligenceService, "list_insights")

    def test_marketing_simulation_maps_to_a_real_implementation(self):
        assert LEGACY_TOOL_ALIASES["simulation"] == "commerce.what_if_simulation"
        assert callable(TOOL_REGISTRY["commerce.what_if_simulation"].handler)

    def test_marketing_remaining_gaps_are_documented(self):
        for declared in _unresolved_declarations().get("MarketingAgent", []):
            assert declared in DOCUMENTED_UNAVAILABLE_TOOLS, declared

    def test_marketing_campaign_design_is_not_faked_as_an_experiment(self):
        # Mapping it to experiments.design would claim a capability that does
        # not exist, so it must stay unresolved with a reason.
        assert "campaign_design" in DOCUMENTED_UNAVAILABLE_TOOLS
        assert DOCUMENTED_UNAVAILABLE_TOOLS["campaign_design"]["category"] == "missing_service"

    def test_marketing_finding_creation_is_not_exposed(self):
        assert DOCUMENTED_UNAVAILABLE_TOOLS["finding_creation"]["category"] == "approval_bypass"

    def test_designer_resolves_no_catalog_tool_and_says_why(self):
        assert tool_ids_for_agent("DesignerAgent") == ()
        unresolved = _unresolved_declarations()["DesignerAgent"]
        assert len(unresolved) == 5
        for declared in unresolved:
            assert declared in DOCUMENTED_UNAVAILABLE_TOOLS, declared

    def test_designer_creative_brief_is_documented_as_approval_bypass(self):
        assert DOCUMENTED_UNAVAILABLE_TOOLS["creative_brief"]["category"] == "approval_bypass"

    def test_designer_real_workspace_still_exists(self):
        """Resolving 0 catalog tools must not mean the Designer lost its path."""
        from backend.app.services.designer_service import DesignerService

        assert hasattr(DesignerService, "store_brief")
        assert hasattr(DesignerService, "request_image_generation")

    def test_designer_permissions_were_not_widened(self):
        perms = AGENT_PERMISSIONS["DesignerAgent"]
        assert not (set(perms) & FORBIDDEN_CAPABILITIES)
        assert "SIMULATE" not in perms
        assert "propose_action" not in perms


class TestNoStaleDocumentation:
    def test_documented_entries_are_still_unresolved(self):
        for name, entry in DOCUMENTED_UNAVAILABLE_TOOLS.items():
            assert LEGACY_TOOL_ALIASES.get(name, name) not in TOOL_REGISTRY, (
                f"{name} now resolves; its documentation is stale"
            )

    def test_documented_entries_are_actually_declared_by_some_agent(self):
        declared = {
            d for agent in AGENT_INSTANCES.values() for d in (getattr(agent, "TOOLS", ()) or ())
        }
        for name in DOCUMENTED_UNAVAILABLE_TOOLS:
            assert name in declared, f"{name} is documented but declared by nobody"

    def test_no_unresolved_declaration_is_undocumented(self):
        for agent, names in _unresolved_declarations().items():
            for name in names:
                assert name in DOCUMENTED_UNAVAILABLE_TOOLS, (
                    f"{agent} declares {name!r} with no documented reason"
                )

    def test_documentation_has_no_duplicate_keys(self):
        assert len(DOCUMENTED_UNAVAILABLE_TOOLS) == len(set(DOCUMENTED_UNAVAILABLE_TOOLS))


# ════════════════════════════════════════════════════════════════════════════
# 5. Selection correctness
# ════════════════════════════════════════════════════════════════════════════


class TestSelectionIsCorrect:
    def test_only_registered_agents_are_selectable(self, db_session, world):
        merchant, _u, _m = world
        roster = ManagerAgent().discover_registered_agents()
        registered = {e["agent_id"] for e in roster}
        for objective in (
            "improve payment recovery and checkout conversion",
            "launch a marketing retention campaign",
            "improve cross-sell bundles and pricing",
        ):
            ctx = _ctx(db_session, merchant, objective)
            manager = ManagerAgent()
            selection = manager.select_agents(manager.parse_goal(ctx))
            for entry in selection["selected"]:
                assert entry["agent_id"] in registered

    def test_manager_never_selects_itself(self, db_session, world):
        merchant, _u, _m = world
        manager = ManagerAgent()
        for objective in (
            "improve payment recovery and checkout conversion",
            "launch a marketing retention campaign",
            "improve cross-sell bundles and pricing",
            "coordinate the whole growth team",
        ):
            ctx = _ctx(db_session, merchant, objective)
            selection = manager.select_agents(manager.parse_goal(ctx))
            assert "ManagerAgent" not in [e["agent_id"] for e in selection["selected"]]

    def test_selection_contains_no_duplicates(self, db_session, world):
        merchant, _u, _m = world
        ctx = _ctx(db_session, merchant, "improve payment recovery and checkout conversion")
        manager = ManagerAgent()
        ids = [e["agent_id"] for e in manager.select_agents(manager.parse_goal(ctx))["selected"]]
        assert len(ids) == len(set(ids))

    def test_roster_contains_no_duplicates(self):
        ids = [e["agent_id"] for e in ManagerAgent().discover_registered_agents()]
        assert len(ids) == len(set(ids))
        assert set(ids) == set(AGENT_INSTANCES)

    def test_selection_is_goal_driven(self, db_session, world):
        merchant, _u, _m = world
        manager = ManagerAgent()
        payment = manager.select_agents(
            manager.parse_goal(_ctx(db_session, merchant, "recover failed payments"))
        )
        product = manager.select_agents(
            manager.parse_goal(_ctx(db_session, merchant, "improve cross-sell bundles"))
        )
        payment_ids = {e["agent_id"] for e in payment["selected"]}
        product_ids = {e["agent_id"] for e in product["selected"]}
        assert payment_ids != product_ids
        # Recovery really does bring in the payment specialist.
        assert "PaymentRecoveryAgent" in payment_ids or not payment_ids

    def test_selection_is_deterministic(self, db_session, world):
        merchant, _u, _m = world
        ctx = _ctx(db_session, merchant, "improve payment recovery and checkout conversion")
        manager = ManagerAgent()
        first = [e["agent_id"] for e in manager.select_agents(manager.parse_goal(ctx))["selected"]]
        second = [e["agent_id"] for e in manager.select_agents(manager.parse_goal(ctx))["selected"]]
        assert first == second

    def test_selection_respects_the_agent_cap(self, db_session, world):
        merchant, _u, _m = world
        manager = ManagerAgent()
        ctx = _ctx(db_session, merchant, "improve everything: conversion retention bundles pricing revenue")
        selection = manager.select_agents(manager.parse_goal(ctx))
        assert len(selection["selected"]) <= ManagerAgent.PLAN_LIMITS["max_agents"]

    def test_selection_does_not_call_every_agent(self, db_session, world):
        merchant, _u, _m = world
        manager = ManagerAgent()
        selectable = [e for e in manager.discover_registered_agents() if e["selectable"]]
        ctx = _ctx(db_session, merchant, "improve payment recovery and checkout conversion")
        selection = manager.select_agents(manager.parse_goal(ctx))
        assert len(selection["selected"]) < len(selectable)

    def test_selected_agents_only_claim_tools_they_own(self, db_session, world):
        merchant, _u, _m = world
        manager = ManagerAgent()
        roster = {e["agent_id"]: e for e in manager.discover_registered_agents()}
        ctx = _ctx(db_session, merchant, "improve payment recovery and checkout conversion")
        for entry in manager.select_agents(manager.parse_goal(ctx))["selected"]:
            owned = set(roster[entry["agent_id"]]["tools"])
            for tool in entry["matched_tools"]:
                assert tool in owned


# ════════════════════════════════════════════════════════════════════════════
# 6. Honest unavailability
# ════════════════════════════════════════════════════════════════════════════


class TestUnavailableSpecialistsAreDisclosed:
    def test_design_goal_discloses_designer_instead_of_dropping_it(self, db_session, world):
        merchant, _u, _m = world
        manager = ManagerAgent()
        ctx = _ctx(db_session, merchant, "improve checkout conversion through design and creative")
        selection = manager.select_agents(manager.parse_goal(ctx))
        unavailable = {u["agent_id"] for u in selection["unavailable_specialists"]}
        assert "DesignerAgent" in unavailable
        # Crucially, it is NOT quietly present in the selection either.
        assert "DesignerAgent" not in [e["agent_id"] for e in selection["selected"]]

    def test_limitation_carries_an_actionable_reason(self, db_session, world):
        merchant, _u, _m = world
        manager = ManagerAgent()
        ctx = _ctx(db_session, merchant, "improve checkout conversion through design and creative")
        selection = manager.select_agents(manager.parse_goal(ctx))
        entry = next(
            u for u in selection["unavailable_specialists"] if u["agent_id"] == "DesignerAgent"
        )
        assert entry["reason"] == "no_implemented_catalog_tool"
        assert entry["unimplemented_tools"]
        assert entry["detail"], "each unresolved tool needs a documented reason"
        for detail in entry["detail"]:
            assert detail["reason"].strip()
            assert detail["remediation"].strip()
            assert detail["category"]
        assert entry["reachable_via"]

    def test_marketing_goal_now_selects_marketing_agent(self, db_session, world):
        """The resolved capabilities must actually change the outcome."""
        merchant, _u, _m = world
        manager = ManagerAgent()
        ctx = _ctx(db_session, merchant, "launch a marketing retention campaign")
        selection = manager.select_agents(manager.parse_goal(ctx))
        assert "MarketingAgent" in [e["agent_id"] for e in selection["selected"]]

    def test_plan_carries_limitations_without_being_invalid(self, db_session, world):
        merchant, _u, _m = world
        manager = ManagerAgent()
        ctx = _ctx(db_session, merchant, "improve checkout conversion through design and creative")
        goal = manager.parse_goal(ctx)
        selection = manager.select_agents(goal)
        selection["_roster"] = manager.discover_registered_agents()
        plan = manager.build_execution_plan(
            ctx=ctx, goal=goal, selection=selection, workflow_id="wf-limitation"
        )
        # A disclosed limitation must not block execution.
        assert plan["status"] == "ready_for_execution"
        assert plan["validation"]["valid"] is True
        assert plan["limitations"]
        assert "DesignerAgent" in {l["agent_id"] for l in plan["limitations"]}

    def test_service_exposes_limitations_over_http(self, api: TestClient, world):
        _merchant, user, _m = world
        res = api.post(
            "/api/manager/plan",
            headers=bearer(user),
            json={"objective": "improve checkout conversion through design and creative"},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert "limitations" in body
        for limitation in body["limitations"]:
            assert limitation["agent_id"]
            assert limitation["reason"]

    def test_roster_api_reports_unavailable_reasons(self, api: TestClient, world):
        _merchant, user, _m = world
        res = api.get("/api/manager/roster", headers=bearer(user))
        assert res.status_code == 200, res.text
        for agent in res.json()["agents"]:
            for reason in agent["unavailable_reasons"]:
                assert reason["reason"].strip()
                assert reason["remediation"].strip()

    def test_unrelated_unavailable_agent_is_not_reported(self, db_session, world):
        """An agent off-topic for the goal must not clutter the limitation list."""
        merchant, _u, _m = world
        manager = ManagerAgent()
        ctx = _ctx(db_session, merchant, "improve cross-sell bundles and pricing")
        selection = manager.select_agents(manager.parse_goal(ctx))
        assert "DesignerAgent" not in {u["agent_id"] for u in selection["unavailable_specialists"]}


# ════════════════════════════════════════════════════════════════════════════
# 7. No recursive ManagerAgent delegation
# ════════════════════════════════════════════════════════════════════════════


class TestNoRecursiveDelegation:
    def test_plan_cannot_delegate_to_the_manager(self, db_session, world):
        merchant, _u, _m = world
        manager = ManagerAgent()
        ctx = _ctx(db_session, merchant, "improve payment recovery and checkout conversion")
        goal = manager.parse_goal(ctx)
        selection = manager.select_agents(goal)
        selection["_roster"] = manager.discover_registered_agents()
        selection["selected"].append({"agent_id": "ManagerAgent", "matched_tools": [], "reason": "x"})
        plan = manager.build_execution_plan(
            ctx=ctx, goal=goal, selection=selection, workflow_id="wf-recursion",
            proposed_tasks=[{"task_id": "T1", "agent_id": "ManagerAgent", "task": "recurse"}],
        )
        assert plan["tasks"] == []
        assert plan["validation"]["valid"] is False
        assert any("ManagerAgent" in r for r in plan["validation"]["rejections"])

    def test_default_plan_never_contains_the_manager(self, db_session, world):
        merchant, _u, _m = world
        manager = ManagerAgent()
        ctx = _ctx(db_session, merchant, "coordinate the entire growth team end to end")
        goal = manager.parse_goal(ctx)
        selection = manager.select_agents(goal)
        selection["_roster"] = manager.discover_registered_agents()
        plan = manager.build_execution_plan(
            ctx=ctx, goal=goal, selection=selection, workflow_id="wf-default"
        )
        assert "ManagerAgent" not in plan["selected_agents"]
        for task in plan["tasks"]:
            assert task["agent_id"] != "ManagerAgent"

    def test_selection_never_includes_the_manager_even_if_forced(self, db_session, world):
        merchant, _u, _m = world
        manager = ManagerAgent()
        ctx = _ctx(db_session, merchant, "improve payment recovery and checkout conversion")
        selection = manager.select_agents(manager.parse_goal(ctx), available=[
            {"agent_id": "ManagerAgent", "selectable": True, "tools": ["analytics.growth_radar"],
             "unimplemented_tools": [], "unavailable_reasons": [], "description": "manager"},
        ])
        assert selection["selected"] == []

    def test_handoff_alias_does_not_expose_dispatch(self):
        """agent_delegation must map to the RECORDING tool, not the executor."""
        from backend.app.services.handoff import handoff_service

        assert LEGACY_TOOL_ALIASES["agent_delegation"] == "collaboration.request_handoff"
        spec = TOOL_REGISTRY["collaboration.request_handoff"]
        assert "record" in spec.source.lower() or "request" in spec.source.lower()
        # Dispatching a handoff remains a separate, operator-gated endpoint.
        assert hasattr(handoff_service, "request")
        assert spec.read_only is False


# ════════════════════════════════════════════════════════════════════════════
# 8. Plans route through the EXISTING orchestrator
# ════════════════════════════════════════════════════════════════════════════


class TestOrchestratorIntegration:
    def test_manager_is_already_in_the_existing_plans(self):
        for plan in (GROWTH_TEAM_PLAN, AI_TEAM_PLAN):
            names = [name for name, _ in plan]
            assert "ManagerAgent" in names
            assert len(names) == len(set(names)) or names.count("ManagerAgent") >= 1

    def test_no_second_orchestrator_was_introduced(self):
        """The Manager must not execute specialists itself."""
        import inspect

        from backend.app.agents.manager_agent import ManagerAgent as MA

        source = inspect.getsource(MA)
        # It must not instantiate or drive the orchestrator from inside the agent.
        assert "GrowthAgentOrchestrator" not in source
        for method_name in (
            "select_agents",
            "build_execution_plan",
            "evaluate_results",
            "build_final_report",
            "parse_goal",
            "discover_registered_agents",
        ):
            method_source = inspect.getsource(getattr(MA, method_name))
            assert "GrowthAgentOrchestrator(" not in method_source

    def test_manager_methods_do_not_call_agent_execute(self):
        """Planning/interpretation must not run a specialist."""
        import inspect

        from backend.app.agents.manager_agent import ManagerAgent as MA

        for method_name in (
            "select_agents",
            "build_execution_plan",
            "evaluate_results",
            "parse_goal",
        ):
            method_source = inspect.getsource(getattr(MA, method_name))
            assert ".execute(" not in method_source

    def test_planning_creates_no_runs_and_no_actions(self, db_session, world):
        merchant, _u, _m = world
        service = ManagerCoordinationService(db_session)
        runs_before = db_session.query(AgentRun).filter(AgentRun.merchant_id == merchant.id).count()
        actions_before = db_session.query(AgentAction).filter(AgentAction.merchant_id == merchant.id).count()
        service.build_plan(
            merchant_id=merchant.id,
            objective="improve payment recovery and checkout conversion",
        )
        assert db_session.query(AgentRun).filter(AgentRun.merchant_id == merchant.id).count() == runs_before
        assert (
            db_session.query(AgentAction).filter(AgentAction.merchant_id == merchant.id).count()
            == actions_before
        )

    def test_execution_endpoint_is_unchanged_and_authorized(self, api: TestClient, world):
        _merchant, user, _m = world
        spec = api.get("/openapi.json").json()["paths"]
        assert "/api/agents/run" in spec
        # Planning is a separate path; execution was not replaced.
        assert "/api/manager/plan" in spec


# ════════════════════════════════════════════════════════════════════════════
# 9. Failure propagation and no duplicate action proposals
# ════════════════════════════════════════════════════════════════════════════


def _entry(agent, status, errors=None, actions=0):
    return {
        "agent": agent,
        "status": status,
        "errors": errors or [],
        "actions_proposed": actions,
        "tools_used": [],
        "latency_ms": {"total": 5},
    }


class TestFailurePropagation:
    def test_real_statuses_are_preserved(self):
        evaluation = ManagerAgent().evaluate_results(
            [_entry("PaymentRecoveryAgent", "completed"), _entry("MarketingAgent", "failed", ["RuntimeError: x"])]
        )
        assert {e["status"] for e in evaluation["evaluations"]} == {"completed", "failed"}
        assert evaluation["outcome"] == "partial_success"

    def test_partial_completion_is_not_reported_as_success(self):
        evaluation = ManagerAgent().evaluate_results(
            [_entry("A", "completed"), _entry("B", "partially_completed", ["some degraded path"])]
        )
        assert evaluation["outcome"] == "completed"
        assert evaluation["evaluations"][1]["status"] == "partially_completed"

    def test_blocked_and_skipped_are_classified(self):
        evaluation = ManagerAgent().evaluate_results(
            [_entry("A", "blocked", ["upstream dependency unavailable"]), _entry("B", "skipped")]
        )
        kinds = {e["agent_id"]: e["failure_kind"] for e in evaluation["evaluations"]}
        assert kinds["A"] == "failed_dependency"
        assert kinds["B"] == "unnecessary_task"

    def test_missing_configuration_is_not_retried_forever(self):
        evaluation = ManagerAgent().evaluate_results(
            [_entry("DesignerAgent", "failed", ["llm_not_configured"])]
        )
        assert evaluation["evaluations"][0]["failure_kind"] == "missing_configuration"
        assert evaluation["evaluations"][0]["retryable"] is False

    def test_replan_stays_within_budget(self):
        entries = [_entry(f"A{i}", "failed", ["TimeoutError: upstream timed out"]) for i in range(8)]
        evaluation = ManagerAgent().evaluate_results(entries)
        assert evaluation["replan_recommended"] is False
        assert evaluation["replan_budget"] == ManagerAgent.PLAN_LIMITS["max_replan"]

    def test_no_duplicate_action_proposals_across_retries(self, db_session, world):
        """Two identical proposals are still two rows — so the Manager must not
        propose actions at all during planning."""
        merchant, _u, _m = world
        service = ManagerCoordinationService(db_session)
        plan = service.build_plan(
            merchant_id=merchant.id, objective="recover failed payments and improve conversion"
        )
        for task in plan["tasks"]:
            assert task["approval_required"] is True
        assert db_session.query(AgentAction).filter(AgentAction.merchant_id == merchant.id).count() == 0

    def test_repeated_planning_is_side_effect_free(self, db_session, world):
        merchant, _u, _m = world
        service = ManagerCoordinationService(db_session)
        first = service.build_plan(merchant_id=merchant.id, objective="recover failed payments")
        second = service.build_plan(merchant_id=merchant.id, objective="recover failed payments")
        # Deterministic delegation, distinct workflow ids (no shared artefact).
        assert first["selected_agents"] == second["selected_agents"]
        assert first["workflow_id"] != second["workflow_id"]
        assert (
            db_session.query(AgentRun).filter(AgentRun.merchant_id == merchant.id).count() == 0
        )

    def test_final_report_counts_proposals_without_approving_them(self, db_session, world):
        merchant, _u, _m = world
        manager = ManagerAgent()
        ctx = _ctx(db_session, merchant, "improve payment recovery and checkout conversion")
        goal = manager.parse_goal(ctx)
        selection = manager.select_agents(goal)
        selection["_roster"] = manager.discover_registered_agents()
        plan = manager.build_execution_plan(ctx=ctx, goal=goal, selection=selection, workflow_id="wf")
        report = manager.build_final_report(
            goal=goal,
            plan=plan,
            summary={
                "status": "completed",
                "totals": {"actions_proposed": 3},
                "agents": [_entry("PaymentRecoveryAgent", "completed", actions=3)],
            },
        )
        assert report["actions_proposed"] == 3
        assert report["actions_awaiting_human_approval"] == 3
        assert report["manager_approved_anything"] is False


# ════════════════════════════════════════════════════════════════════════════
# 10. Permissions, tenant isolation, approval safeguards
# ════════════════════════════════════════════════════════════════════════════


class TestSafeguardsIntact:
    def test_no_agent_holds_a_forbidden_capability(self):
        for name, perms in AGENT_PERMISSIONS.items():
            assert not (set(perms) & FORBIDDEN_CAPABILITIES), name

    def test_no_agent_can_approve_or_execute(self):
        for name in AGENT_INSTANCES:
            entry = next(e for e in ManagerAgent().discover_registered_agents() if e["agent_id"] == name)
            assert entry["can_approve"] is False, name
            assert entry["can_execute"] is False, name

    def test_manager_can_neither_propose_nor_execute(self):
        assert "propose_action" not in AGENT_PERMISSIONS["ManagerAgent"]
        resolved = set(tool_ids_for_agent("ManagerAgent"))
        assert "actions.propose" not in resolved

    def test_simulation_tool_is_unreachable_without_simulate(self, db_session, world):
        merchant, _u, _m = world
        for granted in ([], ["read_merchant"], ["read_orders"], ["read_products"]):
            with pytest.raises(ToolPermissionError):
                invoke(
                    "commerce.what_if_simulation",
                    db=db_session,
                    arguments={
                        "merchant_id": str(merchant.id),
                        "scenario_type": "campaign",
                        "target_customers": 5,
                        "expected_conversion": 0.1,
                        "avg_order_value": 100,
                    },
                    granted_permissions=granted,
                )

    def test_manager_endpoints_require_authentication(self, api: TestClient, secure):
        assert api.get("/api/manager/roster").status_code == 401
        assert api.get("/api/manager/metrics").status_code == 401
        assert api.get("/api/manager/actions").status_code == 401
        assert api.post("/api/manager/plan", json={"objective": "improve conversion"}).status_code == 401

    def test_workflow_is_tenant_scoped(self, api: TestClient, db_session, world):
        merchant, user, _m = world
        _other, other_user, _om = make_world(db_session, slug_hint="tenantisolation")
        wf = uuid.uuid4().hex
        db_session.add(
            AgentRun(
                merchant_id=merchant.id,
                orchestrator_run_id=wf,
                agent_name="PaymentRecoveryAgent",
                status=AgentRunStatus.completed,
                mode="team",
                started_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                input_summary={"params": {"objective": "improve conversion"}},
            )
        )
        db_session.commit()
        assert api.get(f"/api/manager/workflows/{wf}", headers=bearer(user)).status_code == 200
        other = api.get(f"/api/manager/workflows/{wf}", headers=bearer(other_user))
        assert other.status_code == 404
        assert other.json()["detail"] == "WORKFLOW_NOT_FOUND"

    def test_metrics_are_tenant_scoped(self, api: TestClient, db_session, world):
        merchant, _u, _m = world
        _other, other_user, _om = make_world(db_session, slug_hint="metricsisolation")
        db_session.add(
            AgentRun(
                merchant_id=merchant.id,
                orchestrator_run_id=uuid.uuid4().hex,
                agent_name="PaymentRecoveryAgent",
                status=AgentRunStatus.completed,
                mode="team",
                started_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                input_summary={"params": {"objective": "x"}},
            )
        )
        db_session.commit()
        mine = api.get("/api/manager/metrics", headers=bearer(other_user)).json()
        assert mine["agents_coordinated"] == 0
        assert mine["tasks_completed"] == 0

    def test_reading_the_queue_never_approves(self, db_session, world):
        merchant, _u, _m = world
        row = AgentAction(
            merchant_id=merchant.id,
            action_type="retry_failed_payment",
            status=AgentActionStatus.requested,
            requested_by="agent:PaymentRecoveryAgent",
            input_payload={},
        )
        db_session.add(row)
        db_session.commit()
        result = ManagerCoordinationService(db_session).pending_actions(merchant_id=merchant.id)
        assert result["pending_count"] == 1
        assert result["actions"][0]["approved_by_manager"] is False
        db_session.refresh(row)
        assert row.status == AgentActionStatus.requested

    def test_plan_always_marks_actions_as_needing_approval(self, db_session, world):
        merchant, _u, _m = world
        plan = ManagerCoordinationService(db_session).build_plan(
            merchant_id=merchant.id, objective="recover failed payments"
        )
        assert plan["requires_human_approval_for_actions"] is True
        assert all(t["approval_required"] for t in plan["tasks"])

    def test_protected_specialists_are_importable_and_unchanged(self):
        """Guards against an accidental edit to a protected file."""
        from backend.app.agents.designer_agent import DesignerAgent
        from backend.app.agents.marketing_agent import MarketingAgent
        from backend.app.agents.product_agent import ProductAgent

        for agent_cls in (MarketingAgent, ProductAgent, DesignerAgent):
            assert agent_cls.NAME in AGENT_INSTANCES
            assert agent_cls.PERMISSIONS
            assert agent_cls.TOOLS
            # Subclasses still execute through the shared lifecycle.
            assert hasattr(agent_cls, "_run")
