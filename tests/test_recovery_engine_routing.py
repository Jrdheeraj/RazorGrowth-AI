"""
Focused regression tests for recovery engine selection.

THE DEFECT
----------
``GrowthAgentOrchestrator.resume()`` always continued a cycle through the
legacy step loop, even when the cycle had been created and executed by the
LangGraph executor. The two engines do not lay out every mode identically, so
recovery could skip or duplicate work (and returned the wrong summary shape).

WHAT IS PROVEN HERE
-------------------
1. Engine provenance is recorded at creation and is immutable.
2. Both ``run()`` paths record the engine they actually use.
3. ``resume()`` routes ``langgraph`` cycles to the LangGraph executor and
   ``legacy``/historical-NULL cycles to the legacy loop.
4. An unknown recorded value is refused BEFORE ownership is taken.
5. A caller cannot switch an existing cycle to the other engine.

The executors are replaced with recording doubles: these tests prove ROUTING,
so no real agent body, provider call, or workflow side effect is executed.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import update

from backend.app.agents.orchestrator import (
    FAST_PLAN,
    GrowthAgentOrchestrator,
    OrchestrationSummary,
)
from backend.app.models.agent_workflow import AgentWorkflowRun
from backend.app.services.workflow_run_service import (
    EXECUTION_ENGINE_LANGGRAPH,
    EXECUTION_ENGINE_LEGACY,
    WorkflowNotResumable,
    WorkflowRunService,
)
from tests.security_utils import make_world


@pytest.fixture()
def merchant(db_session):
    m, _u, _m = make_world(db_session, slug_hint="enginerouting")
    return m


def _start(db_session, merchant, *, engine):
    wf = WorkflowRunService(db_session)
    row, created = wf.start_workflow(
        merchant_id=merchant.id,
        run_id=uuid.uuid4().hex,
        mode="fast",
        plan=FAST_PLAN,
        execution_engine=engine,
    )
    db_session.commit()
    return row, created


def _summary(run_id: str, merchant_id) -> OrchestrationSummary:
    return OrchestrationSummary(
        orchestrator_run_id=run_id,
        merchant_id=str(merchant_id),
        mode="fast",
        status="completed",
        resumed=True,
    )


# ════════════════════════════════════════════════════════════════════════════
# 1. Engine provenance
# ════════════════════════════════════════════════════════════════════════════


class TestEngineProvenance:
    def test_langgraph_creation_records_langgraph(self, db_session, merchant):
        row, created = _start(
            db_session, merchant, engine=EXECUTION_ENGINE_LANGGRAPH
        )
        assert created is True
        assert row.execution_engine == EXECUTION_ENGINE_LANGGRAPH
        db_session.rollback()

    def test_legacy_creation_records_legacy(self, db_session, merchant):
        row, created = _start(db_session, merchant, engine=EXECUTION_ENGINE_LEGACY)
        assert created is True
        assert row.execution_engine == EXECUTION_ENGINE_LEGACY
        db_session.rollback()

    def test_engine_is_immutable_and_a_switch_is_refused(self, db_session, merchant):
        row, _ = _start(db_session, merchant, engine=EXECUTION_ENGINE_LEGACY)
        assert row.execution_engine == EXECUTION_ENGINE_LEGACY

        with pytest.raises(WorkflowNotResumable):
            WorkflowRunService(db_session).start_workflow(
                merchant_id=merchant.id,
                run_id=row.run_id,
                mode="fast",
                plan=FAST_PLAN,
                execution_engine=EXECUTION_ENGINE_LANGGRAPH,
            )
        db_session.rollback()

        db_session.expire_all()
        fresh = db_session.get(AgentWorkflowRun, row.id)
        assert fresh.execution_engine == EXECUTION_ENGINE_LEGACY, (
            "a refused switch must not rewrite provenance"
        )
        db_session.rollback()

    def test_unknown_engine_is_refused_at_creation(self, db_session, merchant):
        with pytest.raises(ValueError):
            WorkflowRunService(db_session).start_workflow(
                merchant_id=merchant.id,
                run_id=uuid.uuid4().hex,
                mode="fast",
                plan=FAST_PLAN,
                execution_engine="quantum",
            )
        db_session.rollback()

    def test_historical_null_row_is_not_rewritten(self, db_session, merchant):
        """Rows predating provenance keep NULL and their legacy behaviour."""
        row, _ = _start(db_session, merchant, engine=None)
        assert row.execution_engine is None

        same, created = WorkflowRunService(db_session).start_workflow(
            merchant_id=merchant.id,
            run_id=row.run_id,
            mode="fast",
            plan=FAST_PLAN,
            execution_engine=EXECUTION_ENGINE_LANGGRAPH,
        )
        assert created is False
        assert same.id == row.id
        db_session.expire_all()
        assert db_session.get(AgentWorkflowRun, row.id).execution_engine is None, (
            "historical rows are never retroactively assigned an engine"
        )
        db_session.rollback()


# ════════════════════════════════════════════════════════════════════════════
# 2. Each run path records its own engine
# ════════════════════════════════════════════════════════════════════════════


class TestRunRecordsItsEngine:
    def test_default_run_records_langgraph(self, db_session, merchant, monkeypatch):
        orch = GrowthAgentOrchestrator(db_session)
        run_id = uuid.uuid4().hex
        routed: dict = {}

        def fake_langgraph(**kwargs):
            routed.update(kwargs)
            return _summary(run_id, merchant.id)

        def fail_legacy(**kwargs):  # pragma: no cover - reached only on a bug
            pytest.fail("the default run must use the LangGraph executor")

        monkeypatch.setattr(orch, "_execute_langgraph", fake_langgraph)
        monkeypatch.setattr(orch, "_execute", fail_legacy)

        orch.run(merchant.id, mode="fast", run_id=run_id)

        assert routed["workflow_id"] is not None
        row = (
            db_session.query(AgentWorkflowRun)
            .filter(AgentWorkflowRun.run_id == run_id)
            .one()
        )
        assert row.execution_engine == EXECUTION_ENGINE_LANGGRAPH
        db_session.rollback()

    def test_explicit_legacy_run_records_legacy(self, db_session, merchant, monkeypatch):
        orch = GrowthAgentOrchestrator(db_session)
        run_id = uuid.uuid4().hex
        routed: dict = {}

        def fake_legacy(**kwargs):
            routed.update(kwargs)
            return _summary(run_id, merchant.id)

        def fail_langgraph(**kwargs):  # pragma: no cover - reached only on a bug
            pytest.fail("use_langgraph=False must use the legacy executor")

        monkeypatch.setattr(orch, "_execute", fake_legacy)
        monkeypatch.setattr(orch, "_execute_langgraph", fail_langgraph)

        orch.run(merchant.id, mode="fast", run_id=run_id, use_langgraph=False)

        assert routed["workflow_id"] is not None
        row = (
            db_session.query(AgentWorkflowRun)
            .filter(AgentWorkflowRun.run_id == run_id)
            .one()
        )
        assert row.execution_engine == EXECUTION_ENGINE_LEGACY
        db_session.rollback()


# ════════════════════════════════════════════════════════════════════════════
# 3. Resume routes to the recorded engine
# ════════════════════════════════════════════════════════════════════════════


class TestResumeRouting:
    def test_langgraph_cycle_resumes_through_langgraph(
        self, db_session, merchant, monkeypatch
    ):
        row, _ = _start(db_session, merchant, engine=EXECUTION_ENGINE_LANGGRAPH)
        orch = GrowthAgentOrchestrator(db_session)
        routed: dict = {}

        def fake_langgraph(**kwargs):
            routed.update(kwargs)
            return _summary(row.run_id, merchant.id)

        def fail_legacy(**kwargs):  # pragma: no cover - reached only on a bug
            pytest.fail("a langgraph cycle must not resume through the legacy loop")

        monkeypatch.setattr(orch, "_execute_langgraph", fake_langgraph)
        monkeypatch.setattr(orch, "_execute", fail_legacy)

        summary = orch.resume(merchant.id, row.run_id)

        assert summary.resumed is True
        assert routed["workflow_id"] == row.id
        assert routed["resumed"] is True
        assert routed["generation"] >= 1, "the claim's fencing token must be carried"
        db_session.expire_all()
        fresh = db_session.get(AgentWorkflowRun, row.id)
        assert fresh.lease_owner is not None
        assert fresh.lease_owner.startswith("resume:")
        db_session.rollback()

    def test_legacy_cycle_resumes_through_legacy(
        self, db_session, merchant, monkeypatch
    ):
        row, _ = _start(db_session, merchant, engine=EXECUTION_ENGINE_LEGACY)
        orch = GrowthAgentOrchestrator(db_session)
        routed: dict = {}

        def fake_legacy(**kwargs):
            routed.update(kwargs)
            return _summary(row.run_id, merchant.id)

        def fail_langgraph(**kwargs):  # pragma: no cover - reached only on a bug
            pytest.fail("a legacy cycle must not resume through LangGraph")

        monkeypatch.setattr(orch, "_execute", fake_legacy)
        monkeypatch.setattr(orch, "_execute_langgraph", fail_langgraph)

        summary = orch.resume(merchant.id, row.run_id)

        assert summary.resumed is True
        assert routed["workflow_id"] == row.id
        assert routed["plan"] == FAST_PLAN
        assert routed["generation"] >= 1
        db_session.rollback()

    def test_historical_null_cycle_resumes_through_legacy(
        self, db_session, merchant, monkeypatch
    ):
        """NULL means the row predates the column: keep the old behaviour."""
        row, _ = _start(db_session, merchant, engine=None)
        orch = GrowthAgentOrchestrator(db_session)
        routed: dict = {}

        def fake_legacy(**kwargs):
            routed.update(kwargs)
            return _summary(row.run_id, merchant.id)

        def fail_langgraph(**kwargs):  # pragma: no cover - reached only on a bug
            pytest.fail("a historical NULL cycle must resume through the legacy loop")

        monkeypatch.setattr(orch, "_execute", fake_legacy)
        monkeypatch.setattr(orch, "_execute_langgraph", fail_langgraph)

        orch.resume(merchant.id, row.run_id)
        assert routed["workflow_id"] == row.id
        db_session.rollback()

    def test_unknown_engine_is_refused_before_ownership(
        self, db_session, merchant, monkeypatch
    ):
        row, _ = _start(db_session, merchant, engine=EXECUTION_ENGINE_LEGACY)
        # Only an out-of-band/corrupt write can produce this: the service
        # refuses to create it. Recovery must refuse to guess, not fall back.
        db_session.execute(
            update(AgentWorkflowRun)
            .where(AgentWorkflowRun.id == row.id)
            .values(execution_engine="quantum")
        )
        db_session.commit()

        orch = GrowthAgentOrchestrator(db_session)

        def fail(**kwargs):  # pragma: no cover - reached only on a bug
            pytest.fail("no executor may run for an unknown recorded engine")

        monkeypatch.setattr(orch, "_execute", fail)
        monkeypatch.setattr(orch, "_execute_langgraph", fail)

        with pytest.raises(WorkflowNotResumable):
            orch.resume(merchant.id, row.run_id)

        db_session.expire_all()
        fresh = db_session.get(AgentWorkflowRun, row.id)
        assert fresh.lease_owner is None, "refusal must happen before claiming"
        assert fresh.lease_generation == 0, "refusal must not mint a fencing token"
        db_session.rollback()

    @pytest.mark.parametrize(
        "recorded,trespasser",
        [
            (EXECUTION_ENGINE_LEGACY, EXECUTION_ENGINE_LANGGRAPH),
            (EXECUTION_ENGINE_LANGGRAPH, EXECUTION_ENGINE_LEGACY),
        ],
    )
    def test_a_run_cannot_take_over_a_cycle_on_the_other_engine(
        self, db_session, merchant, recorded, trespasser
    ):
        row, _ = _start(db_session, merchant, engine=recorded)
        orch = GrowthAgentOrchestrator(db_session)

        with pytest.raises(WorkflowNotResumable):
            if trespasser == EXECUTION_ENGINE_LANGGRAPH:
                orch.run_with_langgraph(merchant.id, mode="fast", run_id=row.run_id)
            else:
                orch.run(
                    merchant.id,
                    mode="fast",
                    run_id=row.run_id,
                    use_langgraph=False,
                )

        db_session.expire_all()
        fresh = db_session.get(AgentWorkflowRun, row.id)
        assert fresh.execution_engine == recorded
        assert fresh.lease_generation == 0, "the refusal precedes any claim"
        assert fresh.lease_owner is None
        db_session.rollback()
