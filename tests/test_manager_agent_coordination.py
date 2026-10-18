"""
Manager Agent coordination: planning, delegation, evaluation, API contracts.

Every test here asserts something the Manager Agent actually guarantees:

  * agents are discovered from the live registry (never a hardcoded count),
  * only agents with genuinely registered tools can be selected,
  * the Manager never selects itself and never selects the whole roster,
  * model-shaped input is treated as untrusted and rejected deterministically,
  * real statuses are preserved and classified rather than laundered into
    "success",
  * the Manager never approves or executes anything,
  * workflow state comes from real audit rows and is tenant-scoped,
  * durability is reported honestly rather than implied.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app.agents.base import AgentContext
from backend.app.agents.manager_agent import ManagerAgent
from backend.app.agents.registry import AGENT_INSTANCES
from backend.app.models.agent_action import AgentAction
from backend.app.models.agent_run import AgentRun
from backend.app.models.enums import AgentActionStatus, AgentRunStatus
from backend.app.services.manager_plan_service import (
    ManagerCoordinationService,
    ManagerWorkflowNotFound,
)
from tests.security_utils import bearer, make_world


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def api(client: TestClient) -> TestClient:
    return client


@pytest.fixture()
def world(db_session):
    return make_world(db_session, slug_hint="mgr")


@pytest.fixture()
def ctx(db_session, world):
    merchant, _user, _mem = world
    return AgentContext(
        db=db_session,
        merchant_id=merchant.id,
        mode="plan",
        params={"objective": "improve payment recovery and checkout conversion", "window_days": 30},
        llm=None,
        embedding_provider=None,
        shared={},
    )


@pytest.fixture()
def secure(monkeypatch):
    """Force AUTH_MODE=required for one test, exactly like test_auth_login.py.

    The shared suite runs AUTH_MODE=optional to preserve pre-Phase-6 behaviour
    for the legacy suites; production runs AUTH_MODE=required.
    """
    from backend.app.core.config import get_settings

    monkeypatch.setenv("AUTH_MODE", "required")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


# ── 1. registry discovery ───────────────────────────────────────────────────


class TestRegistryDiscovery:
    def test_discovers_every_unique_registered_agent(self):
        entries = ManagerAgent().discover_registered_agents()
        ids = [e["agent_id"] for e in entries]
        assert ids == sorted(ids), "roster must be deterministically ordered"
        assert len(ids) == len(set(ids)), "no duplicate agent entries"
        # Matches the live registry exactly, with no hardcoded number.
        assert set(ids) == set(AGENT_INSTANCES.keys())

    def test_includes_the_manager_itself(self):
        ids = {e["agent_id"] for e in ManagerAgent().discover_registered_agents()}
        assert "ManagerAgent" in ids

    def test_surfaces_unimplemented_tools_instead_of_hiding_them(self):
        for entry in ManagerAgent().discover_registered_agents():
            assert set(entry["tools"]).isdisjoint(entry["unimplemented_tools"])
            # "fully implemented" only ever means "every declared tool resolves"
            assert entry["fully_implemented"] == (
                bool(entry["tools"]) and not entry["unimplemented_tools"]
            )

    def test_manager_can_never_approve_or_execute(self):
        for entry in ManagerAgent().discover_registered_agents():
            assert entry["can_approve"] is False
            assert entry["can_execute"] is False


# ── 2. goal understanding ───────────────────────────────────────────────────


class TestGoalUnderstanding:
    def test_extracts_goal_and_themes(self, ctx):
        goal = ManagerAgent().parse_goal(ctx)
        assert goal["goal"].startswith("improve payment recovery")
        assert "conversion" in goal["themes"]
        assert "checkout" in goal["themes"]

    def test_requires_human_approval_is_not_negotiable(self, ctx):
        assert ManagerAgent().parse_goal(ctx)["requires_human_approval"] is True

    def test_records_real_evidence_status(self, ctx):
        ctx.shared["rag_context"] = {"status": "insufficient_data"}
        goal = ManagerAgent().parse_goal(ctx)
        assert goal["evidence_status"] == "insufficient_data"
        assert "insufficient_merchant_evidence" in goal["blocked_reasons"]

    def test_unmatched_goal_is_blocked_not_fabricated(self, db_session, world):
        merchant, _u, _m = world
        blank = AgentContext(
            db=db_session,
            merchant_id=merchant.id,
            mode="plan",
            params={"objective": "zzz qqq unmatched gibberish"},
        )
        goal = ManagerAgent().parse_goal(blank)
        assert goal["themes"] == []
        assert "objective_matched_no_registered_capability_theme" in goal["blocked_reasons"]
        assert goal["selection_rationale"] is None, "no LLM must mean no rationale is invented"

    def test_constraints_are_recorded_verbatim(self, db_session, world):
        merchant, _u, _m = world
        budgeted = AgentContext(
            db=db_session,
            merchant_id=merchant.id,
            mode="plan",
            params={"objective": "improve conversion", "budget": 5000, "deadline": "2026-12-31"},
        )
        constraints = ManagerAgent().parse_goal(budgeted)["constraints"]
        assert "budget:5000" in constraints
        assert "deadline:2026-12-31" in constraints


# ── 3. dynamic selection ────────────────────────────────────────────────────


class TestDynamicSelection:
    def test_selects_relevant_specialists_not_everything(self, ctx):
        manager = ManagerAgent()
        selection = manager.select_agents(manager.parse_goal(ctx))
        assert selection["selected"], "a real goal must select at least one agent"
        selectable = [e for e in manager.discover_registered_agents() if e["selectable"]]
        assert len(selection["selected"]) < len(selectable), "must not call every agent"

    def test_never_selects_itself(self, ctx):
        manager = ManagerAgent()
        selection = manager.select_agents(manager.parse_goal(ctx))
        assert "ManagerAgent" not in [s["agent_id"] for s in selection["selected"]]

    def test_respects_the_agent_cap(self, ctx):
        manager = ManagerAgent()
        selection = manager.select_agents(manager.parse_goal(ctx))
        assert len(selection["selected"]) <= ManagerAgent.PLAN_LIMITS["max_agents"]

    def test_selection_is_deterministic(self, ctx):
        manager = ManagerAgent()
        first = [s["agent_id"] for s in manager.select_agents(manager.parse_goal(ctx))["selected"]]
        second = [s["agent_id"] for s in manager.select_agents(manager.parse_goal(ctx))["selected"]]
        assert first == second

    def test_only_agents_with_registered_tools_are_selectable(self, ctx):
        manager = ManagerAgent()
        roster = {e["agent_id"]: e for e in manager.discover_registered_agents()}
        for entry in manager.select_agents(manager.parse_goal(ctx))["selected"]:
            assert roster[entry["agent_id"]]["selectable"]
            for tool in entry["matched_tools"]:
                assert tool in roster[entry["agent_id"]]["tools"]

    def test_blocked_goal_selects_nothing(self, db_session, world):
        merchant, _u, _m = world
        blank = AgentContext(db=db_session, merchant_id=merchant.id, mode="plan",
                             params={"objective": "zzz qqq unmatched gibberish"})
        manager = ManagerAgent()
        assert manager.select_agents(manager.parse_goal(blank))["selected"] == []

    def test_reports_which_theme_tools_no_agent_covers(self, ctx):
        manager = ManagerAgent()
        selection = manager.select_agents(manager.parse_goal(ctx))
        covered = {t for s in selection["selected"] for t in s["matched_tools"]}
        unmatched = set(selection["unmatched_theme_tools"])
        assert unmatched == set(selection["wanted_tools"]) - covered


# ── 4. plan validation (untrusted model output) ────────────────────────────


class TestPlanValidation:
    def _selection(self, ctx):
        manager = ManagerAgent()
        selection = manager.select_agents(manager.parse_goal(ctx))
        selection["_roster"] = manager.discover_registered_agents()
        return selection

    def test_default_plan_is_valid_and_serializable(self, ctx):
        import json

        manager = ManagerAgent()
        plan = manager.build_execution_plan(
            ctx=ctx, goal=manager.parse_goal(ctx), selection=self._selection(ctx),
            workflow_id="wf-1",
        )
        assert plan["status"] == "ready_for_execution"
        assert plan["validation"]["valid"] is True
        assert plan["executed"] is False
        json.dumps(plan, default=str)  # must stay wire-serialisable

    def test_rejects_unknown_agent_id(self, ctx):
        manager = ManagerAgent()
        plan = manager.build_execution_plan(
            ctx=ctx, goal=manager.parse_goal(ctx), selection=self._selection(ctx),
            workflow_id="wf-2",
            proposed_tasks=[{"task_id": "T1", "agent_id": "TotallyFakeAgent", "task": "x"}],
        )
        assert plan["status"] == "invalid"
        assert any("unknown_agent_id:TotallyFakeAgent" in r for r in plan["validation"]["rejections"])

    def test_rejects_duplicate_task_ids(self, ctx):
        manager = ManagerAgent()
        agent_id = self._selection(ctx)["selected"][0]["agent_id"]
        plan = manager.build_execution_plan(
            ctx=ctx, goal=manager.parse_goal(ctx), selection=self._selection(ctx),
            workflow_id="wf-3",
            proposed_tasks=[
                {"task_id": "T1", "agent_id": agent_id, "task": "first"},
                {"task_id": "T1", "agent_id": agent_id, "task": "second"},
            ],
        )
        assert any("duplicate_task_id:T1" in r for r in plan["validation"]["rejections"])

    def test_rejects_invalid_dependency_reference(self, ctx):
        manager = ManagerAgent()
        agent_id = self._selection(ctx)["selected"][0]["agent_id"]
        plan = manager.build_execution_plan(
            ctx=ctx, goal=manager.parse_goal(ctx), selection=self._selection(ctx),
            workflow_id="wf-4",
            proposed_tasks=[{"task_id": "T1", "agent_id": agent_id, "task": "x", "depends_on": ["ghost"]}],
        )
        # The task survives but the cycle check rejects the dangling edge.
        assert plan["status"] == "invalid"

    def test_rejects_circular_dependencies(self, ctx):
        manager = ManagerAgent()
        agent_id = self._selection(ctx)["selected"][0]["agent_id"]
        plan = manager.build_execution_plan(
            ctx=ctx, goal=manager.parse_goal(ctx), selection=self._selection(ctx),
            workflow_id="wf-5",
            proposed_tasks=[
                {"task_id": "A", "agent_id": agent_id, "task": "a", "depends_on": ["B"]},
                {"task_id": "B", "agent_id": agent_id, "task": "b", "depends_on": ["A"]},
            ],
        )
        assert any(r.startswith("circular_dependency:") for r in plan["validation"]["rejections"])

    def test_rejects_agent_delegating_to_the_manager(self, ctx):
        manager = ManagerAgent()
        agent_id = self._selection(ctx)["selected"][0]["agent_id"]
        plan = manager.build_execution_plan(
            ctx=ctx, goal=manager.parse_goal(ctx), selection=self._selection(ctx),
            workflow_id="wf-6",
            proposed_tasks=[{"task_id": "T1", "agent_id": "ManagerAgent", "task": "recurse"}],
        )
        assert any("agent_not_selected:ManagerAgent" in r for r in plan["validation"]["rejections"])

    def test_rejects_unregistered_tool_and_permission_grant(self, ctx):
        manager = ManagerAgent()
        agent_id = self._selection(ctx)["selected"][0]["agent_id"]
        plan = manager.build_execution_plan(
            ctx=ctx, goal=manager.parse_goal(ctx), selection=self._selection(ctx),
            workflow_id="wf-7",
            proposed_tasks=[{
                "task_id": "T1", "agent_id": agent_id, "task": "x",
                "tools": ["analytics.business_overview"],
                "permissions": ["approve_anything"],
            }],
        )
        rejections = plan["validation"]["rejections"]
        assert any("unregistered_tool_for_agent" in r for r in rejections)
        assert any("model_generated_permission_rejected" in r for r in rejections)
        assert plan["tasks"] == [], "a rejected task is dropped, not sanitised into place"

    def test_every_task_requires_approval(self, ctx):
        manager = ManagerAgent()
        plan = manager.build_execution_plan(
            ctx=ctx, goal=manager.parse_goal(ctx), selection=self._selection(ctx),
            workflow_id="wf-8",
        )
        assert all(t["approval_required"] is True for t in plan["tasks"])

    def test_limits_are_bounded_and_not_model_controlled(self, ctx):
        manager = ManagerAgent()
        plan = manager.build_execution_plan(
            ctx=ctx, goal=manager.parse_goal(ctx), selection=self._selection(ctx),
            workflow_id="wf-9",
            proposed_tasks=[{"task_id": "T1", "agent_id": self._selection(ctx)["selected"][0]["agent_id"],
                             "task": "x", "limits": {"max_steps": 9999}}],
        )
        assert plan["limits"] == ManagerAgent.PLAN_LIMITS
        assert plan["limits"]["max_steps"] <= 5

    def test_cycle_helper_distinguishes_cyclic_from_acyclic(self):
        manager = ManagerAgent()
        assert manager._find_dependency_cycle(["a", "b"], {"a": ["b"], "b": ["a"]}) is not None
        assert manager._find_dependency_cycle(["a", "b"], {"a": ["b"], "b": []}) is None


# ── 5. result evaluation ────────────────────────────────────────────────────


class TestResultEvaluation:
    def _entry(self, agent, status, errors=None, actions=0):
        return {
            "agent": agent, "status": status, "errors": errors or [],
            "actions_proposed": actions, "tools_used": [], "latency_ms": {"total": 5},
        }

    def test_preserves_real_statuses(self):
        entries = [
            self._entry("PaymentRecoveryAgent", "completed"),
            self._entry("MarketingAgent", "failed", ["RuntimeError: boom"]),
        ]
        evaluation = ManagerAgent().evaluate_results(entries)
        assert [e["status"] for e in evaluation["evaluations"]] == ["completed", "failed"]
        assert evaluation["outcome"] == "partial_success"

    def test_classifies_missing_configuration(self):
        ev = ManagerAgent().evaluate_results(
            [self._entry("DesignerAgent", "failed", ["llm_not_configured"])]
        )
        assert ev["evaluations"][0]["failure_kind"] == "missing_configuration"

    def test_classifies_insufficient_evidence(self):
        ev = ManagerAgent().evaluate_results(
            [self._entry("DesignerAgent", "blocked", ["insufficient_data: no evidence"])]
        )
        assert ev["evaluations"][0]["failure_kind"] == "insufficient_evidence"

    def test_classifies_transient_and_marks_retryable(self):
        ev = ManagerAgent().evaluate_results(
            [self._entry("SoftwareAgent", "failed", ["TimeoutError: upstream timed out"])]
        )
        assert ev["evaluations"][0]["failure_kind"] == "transient"
        assert ev["evaluations"][0]["retryable"] is True

    def test_flags_approval_required_when_actions_proposed(self):
        ev = ManagerAgent().evaluate_results(
            [self._entry("PaymentRecoveryAgent", "completed", actions=3)]
        )
        assert ev["evaluations"][0]["failure_kind"] == "approval_required"

    def test_empty_run_is_not_success(self):
        assert ManagerAgent().evaluate_results([])["outcome"] == "no_agents_executed"

    def test_all_failed_is_failure_not_success(self):
        ev = ManagerAgent().evaluate_results(
            [self._entry("A", "failed", ["x"]), self._entry("B", "failed", ["y"])]
        )
        assert ev["outcome"] == "failed"

    def test_replan_stays_within_budget(self):
        entries = [self._entry(f"A{i}", "failed", ["TimeoutError"]) for i in range(6)]
        ev = ManagerAgent().evaluate_results(entries)
        assert ev["replan_recommended"] is False, "must not replan past the bound"


# ── 6. final synthesis ──────────────────────────────────────────────────────


class TestFinalSynthesis:
    def _report(self, actions=2):
        manager = ManagerAgent()
        goal = {"goal": "improve conversion", "blocked_reasons": []}
        plan = {"workflow_id": "wf", "status": "ready_for_execution",
                "selected_agents": [], "tasks": [], "validation": {"valid": True, "rejections": []}}
        summary = {
            "status": "completed",
            "totals": {"actions_proposed": actions, "opportunities_created": 1},
            "agents": [{"agent": "PaymentRecoveryAgent", "status": "completed",
                        "errors": [], "actions_proposed": actions, "tools_used": [],
                        "latency_ms": {"total": 10}}],
        }
        return manager.build_final_report(goal=goal, plan=plan, summary=summary)

    def test_separates_observed_facts_from_model_output(self):
        report = self._report()
        assert any("PaymentRecoveryAgent" in f for f in report["observed_facts"])
        assert report["recommendations_source"] == "model_derived"

    def test_never_claims_to_have_approved_anything(self):
        assert self._report()["manager_approved_anything"] is False

    def test_surfaces_pending_approval_count(self):
        assert self._report(actions=5)["actions_awaiting_human_approval"] == 5

    def test_includes_next_steps(self):
        assert self._report()["recommended_next_steps"]


# ── 7. service: real rows, tenant scoping, honesty ──────────────────────────


class _SeedRun:
    def __init__(self, db, merchant_id, *, agent, status, workflow_id, errors=None,
                 objective=None, actions=0, tools=None):
        from datetime import datetime, timezone

        self.row = AgentRun(
            merchant_id=merchant_id,
            orchestrator_run_id=workflow_id,
            agent_name=agent,
            status=status,
            mode="team",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            input_summary={"params": {"objective": objective or "improve conversion",
                                      "window_days": 30}},
            output_summary={},
            tools_used=list(tools or []),
            actions_proposed=actions,
            errors=list(errors or []),
            total_latency_ms=12,
            llm_latency_ms=0,
            db_latency_ms=12,
            tool_latency_ms=0,
        )
        db.add(self.row)


class TestCoordinationService:
    def test_roster_count_comes_from_the_registry(self, db_session):
        roster = ManagerCoordinationService(db_session).roster()
        assert roster["agent_count"] == len(AGENT_INSTANCES)
        assert len(roster["agents"]) == roster["agent_count"]

    def test_build_plan_executes_nothing(self, db_session, world):
        merchant, _u, _m = world
        before = db_session.query(AgentRun).filter(AgentRun.merchant_id == merchant.id).count()
        plan = ManagerCoordinationService(db_session).build_plan(
            merchant_id=merchant.id, objective="improve payment recovery and conversion"
        )
        after = db_session.query(AgentRun).filter(AgentRun.merchant_id == merchant.id).count()
        assert before == after, "planning must not create agent runs"
        assert plan["executed"] is False
        assert plan["workflow_id"]

    def test_build_plan_does_not_create_actions(self, db_session, world):
        merchant, _u, _m = world
        before = db_session.query(AgentAction).filter(AgentAction.merchant_id == merchant.id).count()
        ManagerCoordinationService(db_session).build_plan(
            merchant_id=merchant.id, objective="improve payment recovery and conversion"
        )
        after = db_session.query(AgentAction).filter(AgentAction.merchant_id == merchant.id).count()
        assert before == after, "planning must not propose or approve actions"

    def test_workflow_reports_real_rows(self, db_session, world):
        merchant, _u, _m = world
        wf = uuid.uuid4().hex
        _SeedRun(db_session, merchant.id, agent="PaymentRecoveryAgent",
                 status=AgentRunStatus.completed, workflow_id=wf)
        _SeedRun(db_session, merchant.id, agent="MarketingAgent",
                 status=AgentRunStatus.failed, workflow_id=wf, errors=["RuntimeError: boom"])
        db_session.commit()

        report = ManagerCoordinationService(db_session).get_workflow(
            merchant_id=merchant.id, workflow_id=wf
        )
        assert report["status"] == "partial_success"
        assert {a["agent"] for a in report["agents_run"]} == {"PaymentRecoveryAgent", "MarketingAgent"}
        assert report["totals"]["agents_executed"] == 2
        assert report["objective"] == "improve conversion"

    def test_workflow_is_honest_about_durability(self, db_session, world):
        merchant, _u, _m = world
        wf = uuid.uuid4().hex
        _SeedRun(db_session, merchant.id, agent="PaymentRecoveryAgent",
                 status=AgentRunStatus.completed, workflow_id=wf)
        db_session.commit()
        report = ManagerCoordinationService(db_session).get_workflow(
            merchant_id=merchant.id, workflow_id=wf
        )
        assert report["durable_checkpoint"] is False
        assert report["recoverable_after_restart"] is False
        assert "not a resumable checkpoint" in report["recovery_note"]

    def test_workflow_scoped_to_merchant(self, db_session, world):
        merchant, _u, _m = world
        other, _u2, _m2 = make_world(db_session, slug_hint="other")
        wf = uuid.uuid4().hex
        _SeedRun(db_session, merchant.id, agent="PaymentRecoveryAgent",
                 status=AgentRunStatus.completed, workflow_id=wf)
        db_session.commit()
        with pytest.raises(ManagerWorkflowNotFound):
            ManagerCoordinationService(db_session).get_workflow(
                merchant_id=other.id, workflow_id=wf
            )

    def test_unknown_workflow_raises_not_found(self, db_session, world):
        merchant, _u, _m = world
        with pytest.raises(ManagerWorkflowNotFound):
            ManagerCoordinationService(db_session).get_workflow(
                merchant_id=merchant.id, workflow_id="does-not-exist"
            )

    def test_metrics_are_counted_from_rows(self, db_session, world):
        merchant, _u, _m = world
        wf = uuid.uuid4().hex
        _SeedRun(db_session, merchant.id, agent="PaymentRecoveryAgent",
                 status=AgentRunStatus.completed, workflow_id=wf)
        _SeedRun(db_session, merchant.id, agent="MarketingAgent",
                 status=AgentRunStatus.completed, workflow_id=wf)
        _SeedRun(db_session, merchant.id, agent="ProductAgent",
                 status=AgentRunStatus.completed, workflow_id=wf)
        db_session.add(AgentAction(
            merchant_id=merchant.id,
            action_type="retry_failed_payment",
            status=AgentActionStatus.requested,
            requested_by="agent:PaymentRecoveryAgent",
            input_payload={"orchestrator_run_id": wf},
        ))
        db_session.commit()

        metrics = ManagerCoordinationService(db_session).metrics(merchant_id=merchant.id)
        assert metrics["agents_coordinated"] == 3
        assert metrics["tasks_completed"] == 3
        assert metrics["awaiting_approval"] == 1
        assert metrics["total_workflows"] == 1
        assert metrics["metrics_available"] is True

    def test_metrics_are_zero_not_invented_when_empty(self, db_session, world):
        merchant, _u, _m = world
        metrics = ManagerCoordinationService(db_session).metrics(merchant_id=merchant.id)
        assert metrics["agents_coordinated"] == 0
        assert metrics["tasks_completed"] == 0
        assert metrics["active_workflows"] == 0

    def test_pending_actions_expose_origin_agent_and_workflow(self, db_session, world):
        merchant, _u, _m = world
        wf = uuid.uuid4().hex
        _SeedRun(db_session, merchant.id, agent="PaymentRecoveryAgent",
                 status=AgentRunStatus.completed, workflow_id=wf)
        db_session.add(AgentAction(
            merchant_id=merchant.id,
            action_type="retry_failed_payment",
            status=AgentActionStatus.requested,
            requested_by="agent:PaymentRecoveryAgent",
            input_payload={"orchestrator_run_id": wf},
        ))
        db_session.commit()

        result = ManagerCoordinationService(db_session).pending_actions(
            merchant_id=merchant.id, workflow_id=wf
        )
        assert result["pending_count"] == 1
        action = result["actions"][0]
        assert action["origin_agent"] == "PaymentRecoveryAgent"
        assert action["workflow_id"] == wf
        assert action["approved_by_manager"] is False

    def test_pending_actions_do_not_change_state(self, db_session, world):
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
        ManagerCoordinationService(db_session).pending_actions(merchant_id=merchant.id)
        db_session.refresh(row)
        assert row.status == AgentActionStatus.requested, "reading must never approve"


# ── 8. API contracts ────────────────────────────────────────────────────────


class TestManagerApi:
    def test_routes_registered_without_double_prefix(self, api: TestClient):
        spec = api.get("/openapi.json").json()["paths"]
        for path in (
            "/api/manager/roster",
            "/api/manager/plan",
            "/api/manager/workflows/{workflow_id}",
            "/api/manager/metrics",
            "/api/manager/actions",
        ):
            assert path in spec, f"missing {path}"
        assert not any("/api/api/" in p for p in spec)

    def test_roster_is_tenant_readable(self, api: TestClient, world):
        _merchant, user, _m = world
        res = api.get("/api/manager/roster", headers=bearer(user))
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["agent_count"] == len(AGENT_INSTANCES)
        assert len({a["agent_id"] for a in body["agents"]}) == body["agent_count"]

    def test_plan_endpoint_returns_validated_plan(self, api: TestClient, world):
        _merchant, user, _m = world
        res = api.post(
            "/api/manager/plan",
            headers=bearer(user),
            json={"objective": "improve payment recovery and checkout conversion", "window_days": 30},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["workflow_id"]
        assert body["executed"] is False
        assert body["requires_human_approval_for_actions"] is True
        assert "ManagerAgent" not in body["selected_agents"]

    def test_plan_rejects_hostile_proposed_tasks(self, api: TestClient, world):
        _merchant, user, _m = world
        res = api.post(
            "/api/manager/plan",
            headers=bearer(user),
            json={
                "objective": "improve payment recovery and checkout conversion",
                "proposed_tasks": [
                    {"task_id": "T1", "agent_id": "GhostAgent", "task": "x"},
                    {"task_id": "T2", "agent_id": "ManagerAgent", "task": "recurse"},
                ],
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "invalid"
        assert body["validation"]["valid"] is False
        assert body["validation"]["rejections"]

    def test_plan_requires_authentication_when_auth_is_required(self, api: TestClient, secure):
        """Mirrors test_auth_login.py: the suite runs AUTH_MODE=optional, so the
        production posture is exercised by forcing the mode for one test."""
        assert api.post("/api/manager/plan", json={"objective": "improve conversion"}).status_code == 401

    def test_metrics_endpoint(self, api: TestClient, world):
        _merchant, user, _m = world
        res = api.get("/api/manager/metrics", headers=bearer(user))
        assert res.status_code == 200, res.text
        assert res.json()["metrics_available"] is True

    def test_workflow_endpoint_404s_for_unknown_id(self, api: TestClient, world):
        _merchant, user, _m = world
        res = api.get("/api/manager/workflows/nope", headers=bearer(user))
        assert res.status_code == 404

    def test_workflow_is_not_cross_tenant_readable(self, api: TestClient, db_session, world):
        """A workflow owned by one merchant is a 404 for another, not a leak."""
        merchant, user, _m = world
        _other, other_user, _om = make_world(db_session, slug_hint="xtenant")

        wf = uuid.uuid4().hex
        _SeedRun(db_session, merchant.id, agent="PaymentRecoveryAgent",
                 status=AgentRunStatus.completed, workflow_id=wf)
        db_session.commit()

        # The owner sees it...
        assert api.get(f"/api/manager/workflows/{wf}", headers=bearer(user)).status_code == 200
        # ...a different tenant cannot, and learns nothing about its existence.
        other = api.get(f"/api/manager/workflows/{wf}", headers=bearer(other_user))
        assert other.status_code == 404
        assert other.json()["detail"] == "WORKFLOW_NOT_FOUND"

    def test_actions_endpoint_returns_pending_queue(self, api: TestClient, world):
        _merchant, user, _m = world
        res = api.get("/api/manager/actions", headers=bearer(user))
        assert res.status_code == 200, res.text
        assert "actions" in res.json()
