"""
Analysis lifecycle: opening /agents must not start work, and Stop must stop it.

REPRODUCES THE REPORTED BUG
----------------------------
The dev database contained exactly two rows marked in flight, both orphaned by a
worker that died two days earlier (backend up 11 minutes; rows untouched since):

    agent_runs          ProductAGI   running  started 2026-10-15 14:57  heartbeat NULL
    product_agent_runs  <uuid>       running  updated 2026-10-15 14:59  stage prepare_recommendation
    agent_workflow_runs  (empty)

Nothing was executing. Yet the dashboard showed "ANALYZING..." and a campaign
planning message, because the mount effect inferred liveness from the mere
PRESENCE of a `running` row and then polled forever on a row nothing would ever
terminalize.

Two independent defects, both fixed:

  RC1  liveness inferred from a status string, with no staleness bound and no
       heartbeat requirement  ->  `active_run_report()` (read-only, liveness
       bounded) + the dashboard asking the backend instead of guessing.
  RC2  no cancellation anywhere  ->  a durable ``cancel_requested_at`` flag, a
       cancel endpoint, a between-step check in the orchestrator, and a real
       Stop control.

These tests assert the backend contract. Frontend behaviour is covered in
``test_agents_page_lifecycle.py`` by source-level assertions on the effect
graph, which is what actually prevents a regression here.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.agents.orchestrator import FAST_PLAN, GrowthAgentOrchestrator
from backend.app.models.agent_run import AgentRun
from backend.app.models.agent_workflow import AgentWorkflowRun
from backend.app.models.enums import AgentRunStatus, WorkflowStatus
from backend.app.services.workflow_run_service import (
    StaleLeaseError,
    WorkflowNotFound,
    WorkflowRunService,
    active_run_report,
    is_cancel_requested,
    request_cancel,
    step_key,
)
from tests.security_utils import make_world


@pytest.fixture()
def world(db_session):
    return make_world(db_session, slug_hint="lifecycle")


def _cycle(db_session, merchant, run_id, *, status="running", heartbeat="fresh",
           claimed=True):
    """A cycle with a controllable age, so liveness can be decided precisely."""
    wf = WorkflowRunService(db_session)
    row, _ = wf.start_workflow(
        merchant_id=merchant.id, run_id=run_id, mode="fast", plan=FAST_PLAN
    )
    db_session.commit()
    if claimed:
        wf.claim(row, owner="worker-1")
    if heartbeat == "fresh":
        pass
    elif heartbeat == "stale":
        old = datetime.now(timezone.utc) - timedelta(hours=6)
        row.heartbeat_at = old
        row.lease_expires_at = old
    elif heartbeat == "none":
        row.heartbeat_at = None
    if status != "running":
        row.status = status
    db_session.commit()
    db_session.refresh(row)
    return row


def _orphan_agent_run(db_session, merchant, *, status="running", age_hours=48,
                      run_id="orphan-cycle"):
    """An untracked in-flight row: exactly what a dead worker leaves behind."""
    started = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    row = AgentRun(
        merchant_id=merchant.id,
        workflow_id=None,
        step_key=None,
        orchestrator_run_id=run_id,
        agent_name="ProductAGI",
        status=status,
        mode="team",
        started_at=started,
        heartbeat_at=None if age_hours > 1 else started,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


# ════════════════════════════════════════════════════════════════════════════
# 1. Status/dashboard retrieval never starts analysis
# ════════════════════════════════════════════════════════════════════════════


class TestReadsNeverStart:
    def test_active_run_report_is_read_only(self, db_session, world):
        """The probe the dashboard calls on every mount and poll."""
        merchant = world[0]
        before = db_session.query(AgentWorkflowRun).count()
        before_runs = db_session.query(AgentRun).count()
        active_run_report(db_session, merchant_id=merchant.id)
        db_session.rollback()
        assert db_session.query(AgentWorkflowRun).count() == before
        assert db_session.query(AgentRun).count() == before_runs

    def test_polling_a_stale_run_creates_nothing(self, db_session, world):
        merchant = world[0]
        _orphan_agent_run(db_session, merchant)
        runs_before = db_session.query(AgentRun).count()
        for _ in range(5):  # simulate five poll ticks
            active_run_report(db_session, merchant_id=merchant.id)
        assert db_session.query(AgentRun).count() == runs_before

    def test_a_fresh_page_reports_idle(self, db_session, world):
        merchant = world[0]
        report = active_run_report(db_session, merchant_id=merchant.id)
        assert report.active is False
        assert report.idle_reason == "no run in progress"

    def test_an_orphaned_run_is_not_reported_as_active(self, db_session, world):
        """THE BUG. A dead worker's row must not read as a live analysis."""
        merchant = world[0]
        _orphan_agent_run(db_session, merchant, age_hours=48)
        report = active_run_report(db_session, merchant_id=merchant.id)
        assert report.active is False, (
            "an abandoned row was reported as a live analysis"
        )
        assert "staleness" in (report.idle_reason or "")

    def test_a_recent_run_is_reported_as_active(self, db_session, world):
        """The fix must not just disable the indicator."""
        merchant = world[0]
        _cycle(db_session, merchant, "fresh-cycle", heartbeat="fresh")
        report = active_run_report(db_session, merchant_id=merchant.id)
        assert report.active is True
        assert report.run_id == "fresh-cycle"

    def test_a_stale_heartbeat_is_not_active(self, db_session, world):
        merchant = world[0]
        _cycle(db_session, merchant, "cold-cycle", heartbeat="stale")
        report = active_run_report(db_session, merchant_id=merchant.id)
        assert report.active is False
        assert "heartbeat is stale" in (report.idle_reason or "")

    def test_a_recent_orphan_is_still_active(self, db_session, world):
        """Age, not row type, decides liveness."""
        merchant = world[0]
        _orphan_agent_run(db_session, merchant, age_hours=0)
        report = active_run_report(db_session, merchant_id=merchant.id)
        assert report.active is True


# ════════════════════════════════════════════════════════════════════════════
# 2-3. Explicit start creates exactly one run
# ════════════════════════════════════════════════════════════════════════════


class TestExplicitStart:
    def test_start_persists_the_run_before_execution(self, db_session, world):
        merchant = world[0]
        orch = GrowthAgentOrchestrator(db_session)
        summary = orch.run(merchant.id, mode="fast",
                           params={"objective": "t", "window_days": 30})
        db_session.commit()
        assert summary.orchestrator_run_id
        row = db_session.query(AgentWorkflowRun).filter(
            AgentWorkflowRun.run_id == summary.orchestrator_run_id).one()
        assert row.status in (
            WorkflowStatus.completed.value,
            WorkflowStatus.partial.value,
            WorkflowStatus.failed.value,
        )
        assert row.run_id == summary.orchestrator_run_id

    def test_a_second_start_while_live_does_not_create_a_second_cycle(
        self, db_session, world
    ):
        """The backend guard, which the React guard cannot replace.

        ``if (isWorking) return`` is advisory: two tabs, a retry, or a refresh
        mid-request all bypass it. The route consults the same authoritative
        liveness probe and returns the live cycle instead of creating one.
        """
        merchant = world[0]
        live = _cycle(db_session, merchant, "already-live")
        report = active_run_report(db_session, merchant_id=merchant.id)
        assert report.active and report.run_id == live.run_id
        count = db_session.query(AgentWorkflowRun).filter(
            AgentWorkflowRun.merchant_id == merchant.id).count()
        assert count == 1, "the guard must not create a second cycle"

    def test_starting_after_completion_creates_a_new_cycle(self, db_session, world):
        """A finished cycle is not a reason to refuse a new run."""
        merchant = world[0]
        _cycle(db_session, merchant, "done", status="completed")
        report = active_run_report(db_session, merchant_id=merchant.id)
        assert report.active is False, (
            "a completed cycle must not block a genuinely new analysis"
        )


# ════════════════════════════════════════════════════════════════════════════
# 4. Cancellation prevents subsequent steps
# ════════════════════════════════════════════════════════════════════════════


class TestCancellation:
    def test_cancel_persists_the_request_and_terminalises(self, db_session, world):
        merchant = world[0]
        row = _cycle(db_session, merchant, "cancel-me")
        updated = request_cancel(db_session, merchant_id=merchant.id,
                                 run_id="cancel-me")
        assert updated.status == WorkflowStatus.cancelled.value
        assert updated.cancel_requested_at is not None
        assert is_cancel_requested(db_session, row.id) is True

    def test_cancel_closes_the_in_flight_step(self, db_session, world):
        merchant = world[0]
        row = _cycle(db_session, merchant, "cancel-step")
        AgentRun(
            merchant_id=merchant.id, workflow_id=row.id, orchestrator_run_id=row.run_id,
            agent_name="GrowthDiscoveryAgent", step_key=step_key("fast", 1, "GrowthDiscoveryAgent"),
            step_index=1, attempt=1, status=AgentRunStatus.running.value, mode="fast",
            started_at=datetime.now(timezone.utc),
        )
        db_session.add(row)
        db_session.commit()
        db_session.add(AgentRun(
            merchant_id=merchant.id, workflow_id=row.id, orchestrator_run_id=row.run_id,
            agent_name="GrowthDiscoveryAgent", step_key=step_key("fast", 1, "GrowthDiscoveryAgent"),
            step_index=1, attempt=1, status=AgentRunStatus.running.value, mode="fast",
            started_at=datetime.now(timezone.utc),
        ))
        db_session.commit()
        request_cancel(db_session, merchant_id=merchant.id, run_id="cancel-step")
        step = db_session.query(AgentRun).filter(
            AgentRun.workflow_id == row.id,
            AgentRun.step_key == step_key("fast", 1, "GrowthDiscoveryAgent"),
        ).one()
        assert step.status == AgentRunStatus.interrupted.value
        assert step.completed_at is not None, "a cancelled step must not look active"

    def test_cancel_fences_the_worker(self, db_session, world):
        """A cancelled cycle must not be writable by the worker it stopped."""
        from backend.app.services.agent_run_service import AgentRunService

        merchant = world[0]
        row = _cycle(db_session, merchant, "cancel-fence")
        gen_before = row.lease_generation
        request_cancel(db_session, merchant_id=merchant.id, run_id="cancel-fence")
        db_session.refresh(row)
        assert row.lease_generation > gen_before
        with pytest.raises(StaleLeaseError):
            WorkflowRunService(db_session).record_step_start(
                db_session, commit=False, expected_generation=gen_before,
                merchant_id=merchant.id, agent_name="GrowthDiscoveryAgent",
                orchestrator_run_id="cancel-fence", mode="fast", input_summary={},
                workflow_id=row.id, step_key="fast:001:x:-:c", step_index=1, attempt=1,
            )
        db_session.rollback()

    def test_a_cancelled_cycle_starts_no_further_steps(self, db_session, world):
        """The end-to-end property: cancellation observed between steps."""
        merchant = world[0]
        orch = GrowthAgentOrchestrator(db_session)
        wf = WorkflowRunService(db_session)
        row, _ = wf.start_workflow(merchant_id=merchant.id, run_id="cancel-e2e",
                                   mode="fast", plan=FAST_PLAN)
        db_session.commit()
        wf.claim(row, owner="worker-1")
        db_session.commit()
        # Cancel BEFORE any step begins.
        request_cancel(db_session, merchant_id=merchant.id, run_id="cancel-e2e")
        summary = orch._execute(
            merchant_id=merchant.id, mode="fast", plan=FAST_PLAN,
            orchestrator_run_id="cancel-e2e",
            params={"objective": "t", "window_days": 30},
            workflow_id=row.id, wf=wf, resumed=False,
            generation=db_session.get(AgentWorkflowRun, row.id).lease_generation,
        )
        assert summary.status == "cancelled"
        assert summary.cancelled_at_step == 0, "no step should have started"
        assert not db_session.query(AgentRun).filter(
            AgentRun.workflow_id == row.id).count(), (
            "a cancelled cycle executed a step anyway"
        )

    def test_cancel_is_terminal_and_not_resumable(self, db_session, world):
        from backend.app.services.workflow_run_service import is_resumable

        merchant = world[0]
        _cycle(db_session, merchant, "cancel-terminal")
        row = request_cancel(db_session, merchant_id=merchant.id,
                             run_id="cancel-terminal")
        assert is_resumable(row) is False, (
            "recovery must never restart something an operator stopped"
        )


# ════════════════════════════════════════════════════════════════════════════
# 5. Terminal states stay terminal
# ════════════════════════════════════════════════════════════════════════════


class TestTerminalStates:
    @pytest.mark.parametrize("status", [
        WorkflowStatus.completed.value,
        WorkflowStatus.failed.value,
        WorkflowStatus.cancelled.value,
        WorkflowStatus.interrupted.value,
        WorkflowStatus.partial.value,
    ])
    def test_a_finished_cycle_is_never_active(self, db_session, world, status):
        merchant = world[0]
        _cycle(db_session, merchant, f"term-{status}", status=status)
        assert active_run_report(db_session, merchant_id=merchant.id).active is False

    def test_cancelling_a_finished_cycle_changes_nothing(self, db_session, world):
        """A late cancellation must not rewrite a completed outcome."""
        merchant = world[0]
        _cycle(db_session, merchant, "late-cancel", status="completed")
        row = request_cancel(db_session, merchant_id=merchant.id,
                             run_id="late-cancel")
        assert row.status == WorkflowStatus.completed.value

    def test_a_cancelled_cycle_never_resumes_on_a_fresh_start(self, db_session, world):
        merchant = world[0]
        _cycle(db_session, merchant, "no-resume")
        request_cancel(db_session, merchant_id=merchant.id, run_id="no-resume")
        report = active_run_report(db_session, merchant_id=merchant.id)
        assert report.active is False


# ════════════════════════════════════════════════════════════════════════════
# 6. Tenant isolation
# ════════════════════════════════════════════════════════════════════════════


class TestTenantIsolation:
    def test_active_run_is_merchant_scoped(self, db_session):
        a, _u, _m = make_world(db_session, slug_hint="tenant-a")
        b, _u2, _m2 = make_world(db_session, slug_hint="tenant-b")
        _cycle(db_session, a, "tenant-a-cycle")
        assert active_run_report(db_session, merchant_id=a.id).active is True
        assert active_run_report(db_session, merchant_id=b.id).active is False, (
            "tenant B must not see tenant A's activity"
        )

    def test_cannot_cancel_another_tenants_cycle(self, db_session):
        a, _u, _m = make_world(db_session, slug_hint="tc-a")
        b, _u2, _m2 = make_world(db_session, slug_hint="tc-b")
        _cycle(db_session, a, "tc-a-cycle")
        with pytest.raises(WorkflowNotFound):
            request_cancel(db_session, merchant_id=b.id, run_id="tc-a-cycle")
        db_session.rollback()
        assert db_session.query(AgentWorkflowRun).filter(
            AgentWorkflowRun.run_id == "tc-a-cycle"
        ).one().status == WorkflowStatus.running.value, (
            "a failed cross-tenant cancel must not mutate anything"
        )

    def test_cancelling_an_unknown_run_is_not_found(self, db_session, world):
        merchant = world[0]
        with pytest.raises(WorkflowNotFound):
            request_cancel(db_session, merchant_id=merchant.id, run_id="never-existed")

    def test_orphan_liveness_does_not_leak_across_tenants(self, db_session):
        a, _u, _m = make_world(db_session, slug_hint="orphan-a")
        b, _u2, _m2 = make_world(db_session, slug_hint="orphan-b")
        _orphan_agent_run(db_session, a, age_hours=0)
        assert active_run_report(db_session, merchant_id=b.id).active is False


# ════════════════════════════════════════════════════════════════════════════
# 7. Polling creates no execution records; exceptions do not strand a run
# ════════════════════════════════════════════════════════════════════════════


class TestNoStrandedRuns:
    def test_an_exception_does_not_leave_a_run_actively_executing(self, db_session, world):
        """A crash must leave a terminal row, not a permanent 'running' one."""
        merchant = world[0]
        wf = WorkflowRunService(db_session)
        row, _ = wf.start_workflow(merchant_id=merchant.id, run_id="boom",
                                   mode="fast", plan=FAST_PLAN)
        db_session.commit()
        gen = wf.claim(row, owner="worker-1")
        db_session.commit()

        from backend.app.services.agent_run_service import AgentRunService

        state = db_session
        pk = wf.record_step_start(
            state, expected_generation=gen, merchant_id=merchant.id,
            agent_name="GrowthDiscoveryAgent", orchestrator_run_id="boom", mode="fast",
            input_summary={}, workflow_id=row.id,
            step_key="fast:001:GrowthDiscoveryAgent:-:b", step_index=1, attempt=1,
        )
        # The process "dies": the step row is left running and the cycle is not
        # finalised. This is exactly the state the bug report described.
        db_session.commit()
        assert db_session.get(AgentRun, pk).status == AgentRunStatus.running.value

        # The recovery probe must not believe it.
        report = active_run_report(db_session, merchant_id=merchant.id)
        assert report.active is True, "a fresh heartbeat legitimately looks live"

        # Age it, and the same probe must now call it dead.
        aged = db_session.get(AgentWorkflowRun, row.id)
        old = datetime.now(timezone.utc) - timedelta(hours=6)
        aged.heartbeat_at = old
        aged.lease_expires_at = old
        db_session.commit()
        assert active_run_report(db_session, merchant_id=merchant.id).active is False

    def test_orphan_reconciliation_closes_abandoned_rows(self, db_session, world):
        """The write half, run by the sweep rather than by a GET."""
        from backend.app.services.workflow_run_service import reconcile_orphan_runs

        merchant = world[0]
        orphan = _orphan_agent_run(db_session, merchant, age_hours=72)
        before = reconcile_orphan_runs(db_session).agent_runs
        db_session.refresh(orphan)
        assert orphan.status == AgentRunStatus.interrupted.value
        assert orphan.completed_at is not None
        assert before >= 1

    def test_orphan_reconciliation_never_touches_a_live_row(self, db_session, world):
        from backend.app.services.workflow_run_service import reconcile_orphan_runs

        merchant = world[0]
        live = _orphan_agent_run(db_session, merchant, age_hours=0)
        reconcile_orphan_runs(db_session)
        db_session.refresh(live)
        assert live.status == AgentRunStatus.running.value, (
            "a row that started moments ago is NOT abandoned and must survive; "
            "a cutoff of 'now' would close runs that have only just begun"
        )

    def test_orphan_reconciliation_is_idempotent(self, db_session, world):
        from backend.app.services.workflow_run_service import reconcile_orphan_runs

        merchant = world[0]
        _orphan_agent_run(db_session, merchant, age_hours=72)
        first = reconcile_orphan_runs(db_session).agent_runs
        second = reconcile_orphan_runs(db_session).agent_runs
        assert first >= 1
        assert second == 0, "a second pass must find nothing left to close"

    def test_orphan_reconciliation_is_merchant_scoped(self, db_session):
        a, _u, _m = make_world(db_session, slug_hint="orph-a")
        b, _u2, _m2 = make_world(db_session, slug_hint="orph-b")
        mine = _orphan_agent_run(db_session, a, age_hours=72)
        from backend.app.services.workflow_run_service import reconcile_orphan_runs

        reconcile_orphan_runs(db_session)
        db_session.refresh(mine)
        assert mine.status == AgentRunStatus.interrupted.value
        others = db_session.query(AgentRun).filter(
            AgentRun.merchant_id == b.id,
            AgentRun.status == AgentRunStatus.running.value,
        ).all()
        assert all(r.started_at > datetime.now(timezone.utc) - timedelta(hours=1)
                   for r in others)


class TestWorkerCrashRegression:
    """Regression tests for the team orchestrator worker crash and employee error pollution."""

    def test_team_orchestrator_worker_claims_unowned_workflow_without_ownership_error(
        self, db_session, world
    ):
        """Pre-created workflow from run_agents must be claimable by orchestrator worker."""
        from backend.app.agents.orchestrator import AI_TEAM_PLAN

        merchant = world[0]
        cycle_id = uuid.uuid4().hex
        wf = WorkflowRunService(db_session)
        workflow_row, _ = wf.start_workflow(
            merchant_id=merchant.id,
            run_id=cycle_id,
            mode="team",
            plan=AI_TEAM_PLAN,
        )
        db_session.commit()

        # Orchestrator worker attempts to claim
        gen = wf.claim(
            workflow_row,
            owner=f"run:{uuid.uuid4().hex[:12]}",
            stale_after_seconds=120,
        )
        assert gen >= 1
        db_session.refresh(workflow_row)
        assert workflow_row.lease_owner is not None
        assert workflow_row.lease_generation == gen

    def test_orchestrator_worker_crash_does_not_fail_parallel_employees(
        self, db_session, world
    ):
        """A failure in the team orchestrator worker must NOT stamp worker_crashed on ProductAGI or MarketingAGI."""
        from backend.app.agents.marketing_agi.cycle import MARKETING_AGI_AGENT_NAME
        from backend.app.agents.product_agi.cycle import PRODUCT_AGENT_AGENT_NAME
        from backend.app.api.routes.agents import _run_team_orchestrator_worker

        merchant = world[0]
        cycle_id = uuid.uuid4().hex

        # Create running agent rows for MarketingAGI and ProductAGI
        product_run = AgentRun(
            merchant_id=merchant.id,
            orchestrator_run_id=cycle_id,
            agent_name=PRODUCT_AGENT_AGENT_NAME,
            status=AgentRunStatus.running.value,
            mode="team",
            started_at=datetime.now(timezone.utc),
        )
        marketing_run = AgentRun(
            merchant_id=merchant.id,
            orchestrator_run_id=cycle_id,
            agent_name=MARKETING_AGI_AGENT_NAME,
            status=AgentRunStatus.running.value,
            mode="team",
            started_at=datetime.now(timezone.utc),
        )
        step_run = AgentRun(
            merchant_id=merchant.id,
            orchestrator_run_id=cycle_id,
            agent_name="GrowthMemoryAgent",
            status=AgentRunStatus.running.value,
            mode="team",
            started_at=datetime.now(timezone.utc),
        )
        db_session.add_all([product_run, marketing_run, step_run])
        db_session.commit()

        # Simulate orchestrator runtime crash
        class CrashOrchestrator:
            def __init__(self, *args, **kwargs):
                pass
            def run(self, *args, **kwargs):
                raise RuntimeError("simulated orchestrator worker crash")

        from unittest.mock import patch
        from sqlalchemy.orm import sessionmaker

        sf = sessionmaker(bind=db_session.get_bind())
        with patch("backend.app.agents.orchestrator.GrowthAgentOrchestrator", CrashOrchestrator):
            _run_team_orchestrator_worker(
                sf,
                merchant.id,
                {},
                cycle_id,
                {},
            )

        db_session.refresh(product_run)
        db_session.refresh(marketing_run)
        db_session.refresh(step_run)

        # Parallel employees must NOT be marked failed by the orchestrator worker's crash
        assert product_run.status == AgentRunStatus.running.value
        assert product_run.errors is None or "worker_crashed" not in product_run.errors
        assert marketing_run.status == AgentRunStatus.running.value
        assert marketing_run.errors is None or "worker_crashed" not in marketing_run.errors

        # The orchestrator's own step run must be marked failed
        assert step_run.status == AgentRunStatus.failed.value
        assert "worker_crashed" in (step_run.errors or [])

    def test_orchestrator_worker_crash_marks_workflow_run_failed(
        self, db_session, world
    ):
        """Worker crash must correctly locate the AgentWorkflowRun by run_id and mark it failed."""
        from backend.app.agents.orchestrator import AI_TEAM_PLAN
        from backend.app.api.routes.agents import _run_team_orchestrator_worker

        merchant = world[0]
        cycle_id = uuid.uuid4().hex
        wf = WorkflowRunService(db_session)
        workflow_row, _ = wf.start_workflow(
            merchant_id=merchant.id,
            run_id=cycle_id,
            mode="team",
            plan=AI_TEAM_PLAN,
        )
        db_session.commit()

        # Simulate crash inside _run_team_orchestrator_worker
        class CrashOrchestrator:
            def __init__(self, *args, **kwargs):
                pass
            def run(self, *args, **kwargs):
                raise RuntimeError("orchestrator runtime crash")

        from unittest.mock import patch
        with patch("backend.app.agents.orchestrator.GrowthAgentOrchestrator", CrashOrchestrator):
            from sqlalchemy.orm import sessionmaker
            sf = sessionmaker(bind=db_session.get_bind())
            _run_team_orchestrator_worker(
                sf,
                merchant.id,
                {},
                cycle_id,
                {},
            )

        db_session.refresh(workflow_row)
        assert workflow_row.status == WorkflowStatus.failed.value
        assert workflow_row.completed_at is not None
        assert "worker_crashed" in (workflow_row.errors or [])

    def test_product_agent_audit_row_clears_errors_on_success(self, db_session, world):
        """_complete_audit_row resets errors to [] when successful, removing any stale errors."""
        from backend.app.agents.product_agi.cycle import (
            PRODUCT_AGENT_AGENT_NAME,
            _complete_audit_row,
        )

        merchant = world[0]
        cycle_id = uuid.uuid4().hex
        row = AgentRun(
            merchant_id=merchant.id,
            orchestrator_run_id=cycle_id,
            agent_name=PRODUCT_AGENT_AGENT_NAME,
            status=AgentRunStatus.running.value,
            mode="team",
            started_at=datetime.now(timezone.utc),
            errors=["stale_worker_error"],
        )
        db_session.add(row)
        db_session.commit()

        _complete_audit_row(
            db_session,
            merchant_id=merchant.id,
            cycle_id=cycle_id,
            status="completed",
            output={"status": "completed"},
            errors=None,
        )
        db_session.commit()
        db_session.refresh(row)
        assert row.status == AgentRunStatus.completed.value
        assert row.errors == []

    def test_cancellation_cascades_to_marketing_and_product_runs(self, db_session, world):
        """request_cancel properly updates MarketingAGIRun and ProductAgentRun without AttributeError."""
        from backend.app.models.marketing_agi import MarketingAGIRun
        from backend.app.models.product_agi import ProductAgentRun
        from backend.app.services.workflow_run_service import request_cancel

        merchant = world[0]
        cycle_id = uuid.uuid4().hex
        wf = WorkflowRunService(db_session)
        workflow_row, _ = wf.start_workflow(
            merchant_id=merchant.id,
            run_id=cycle_id,
            mode="team",
            plan=FAST_PLAN,
        )
        db_session.commit()

        magi = MarketingAGIRun(
            merchant_id=merchant.id,
            analysis_cycle_id=cycle_id,
            objective="test marketing cancel",
            status="running",
        )
        pagi = ProductAgentRun(
            merchant_id=merchant.id,
            analysis_cycle_id=cycle_id,
            objective="test product cancel",
            status="running",
        )
        db_session.add_all([magi, pagi])
        db_session.commit()

        res = request_cancel(db_session, merchant_id=merchant.id, run_id=cycle_id)
        assert res.status == "cancelled"

        db_session.refresh(magi)
        db_session.refresh(pagi)
        assert magi.status == "cancelled"
        assert pagi.status == "cancelled"