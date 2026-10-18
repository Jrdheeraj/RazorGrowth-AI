"""
Phase 2 recovery safety: the partial-result reuse policy.

WHY THIS FILE EXISTS SEPARATELY
-------------------------------
The previous implementation reused any step whose status was ``completed`` or
``partially_completed``. That is a status whitelist, not a safety decision: a
degraded run says nothing about whether an external operation completed, and
replaying such a result hands downstream steps a silent gap.

The policy here is decided from PERSISTED EVIDENCE and is deliberately
conservative in three directions:

* reuse only when the evidence establishes safety;
* retry only when nothing suggests an external effect happened;
* otherwise hold for RECONCILIATION and do neither.

The three outcomes are distinguishable on purpose. "Retry" is safe only because
no action left the approval queue; "reconcile" exists because when one did, the
platform genuinely does not know whether the provider was called.
"""
from __future__ import annotations

import uuid

import pytest

from backend.app.agents.orchestrator import AI_TEAM_PLAN, FAST_PLAN, GROWTH_TEAM_PLAN
from backend.app.models.agent_action import AgentAction
from backend.app.models.agent_run import AgentRun
from backend.app.models.enums import AgentActionStatus, AgentRunStatus
from backend.app.services.agent_run_service import AgentRunService
from backend.app.services.workflow_run_service import (
    ReuseVerdict,
    WorkflowRunService,
    decide_reuse,
    step_key,
)
from tests.security_utils import make_world

RUN_ID = "wf-policy"


@pytest.fixture()
def merchant(db_session):
    m, _u, _mem = make_world(db_session, slug_hint="policysafe")
    return m


@pytest.fixture()
def cycle(db_session, merchant):
    wf = WorkflowRunService(db_session)
    workflow, _ = wf.start_workflow(
        merchant_id=merchant.id, run_id=RUN_ID, mode="fast", plan=FAST_PLAN
    )
    db_session.commit()
    return workflow


def _attempt(db_session, workflow, merchant, index, status, output, attempt=1):
    agent = FAST_PLAN[index][0]
    svc = AgentRunService(db_session)
    row = svc.start_run(
        merchant_id=merchant.id, agent_name=agent,
        orchestrator_run_id=workflow.run_id, workflow_id=workflow.id,
        step_key=step_key("fast", index, agent), step_index=index, attempt=attempt,
    )
    row.status = status
    row.output_summary = output
    db_session.commit()
    return row


def _action(db_session, merchant, workflow, status):
    a = AgentAction(
        merchant_id=merchant.id, action_type="retry_payment",
        status=status, input_payload={"payment_id": "p1"},
        idempotency_key=uuid.uuid4().hex * 2, workflow_run_id=workflow.id,
    )
    db_session.add(a)
    db_session.commit()
    return a


# ════════════════════════════════════════════════════════════════════════════
# Fully completed
# ════════════════════════════════════════════════════════════════════════════


class TestCompletedReuse:
    def test_a_completed_step_is_reused(self, db_session, merchant, cycle):
        row = _attempt(db_session, cycle, merchant, 0,
                       AgentRunStatus.completed.value, {"x": 1})
        d = decide_reuse(db_session, row, merchant_id=merchant.id)
        assert d.verdict is ReuseVerdict.REUSE
        assert d.reusable

    def test_completion_is_reused_even_with_an_action_already_queued(
        self, db_session, merchant, cycle
    ):
        """A finished step is finished, whatever its proposals did afterwards.

        A ``requested`` action is still human-gated, so it caused no external
        effect and must not block reuse of work that genuinely completed.
        """
        row = _attempt(db_session, cycle, merchant, 0,
                       AgentRunStatus.completed.value, {"x": 1})
        _action(db_session, merchant, cycle, AgentActionStatus.requested)
        assert decide_reuse(db_session, row, merchant_id=merchant.id).verdict \
            is ReuseVerdict.REUSE


# ════════════════════════════════════════════════════════════════════════════
# Partial results: safe reuse
# ════════════════════════════════════════════════════════════════════════════


class TestSafePartialReuse:
    def test_a_partial_step_with_intact_output_is_reused(
        self, db_session, merchant, cycle
    ):
        row = _attempt(db_session, cycle, merchant, 1,
                       AgentRunStatus.partially_completed.value,
                       {"findings": ["kept"], "ranked_opportunities": []})
        d = decide_reuse(db_session, row, merchant_id=merchant.id)
        assert d.verdict is ReuseVerdict.REUSE
        assert "intact" in d.reason
        assert d.evidence, "a reuse decision must carry its evidence"

    def test_safe_partial_reuse_survives_a_requested_action(
        self, db_session, merchant, cycle
    ):
        """Proposals are idempotent, so a queued one is not an external effect."""
        row = _attempt(db_session, cycle, merchant, 1,
                       AgentRunStatus.partially_completed.value, {"findings": ["k"]})
        _action(db_session, merchant, cycle, AgentActionStatus.requested)
        assert decide_reuse(db_session, row, merchant_id=merchant.id).verdict \
            is ReuseVerdict.REUSE


# ════════════════════════════════════════════════════════════════════════════
# Partial results: unsafe reuse
# ════════════════════════════════════════════════════════════════════════════


class TestUnsafePartialReuse:
    @pytest.mark.parametrize("state", ["approved", "executing"])
    def test_a_partial_step_with_an_action_past_the_queue_needs_reconciliation(
        self, db_session, merchant, cycle, state
    ):
        """The decisive case: an external effect may already have happened.

        The step's own output looks perfectly intact, so a naive check would
        happily replay it. But an action reached ``approved``/``executing``,
        which means the provider may already have been called. Neither replaying
        nor retrying is safe, so the step is held for reconciliation.
        """
        row = _attempt(db_session, cycle, merchant, 1,
                       AgentRunStatus.partially_completed.value,
                       {"findings": ["looks fine"]})
        _action(db_session, merchant, cycle, AgentActionStatus[state])
        d = decide_reuse(db_session, row, merchant_id=merchant.id)
        assert d.verdict is ReuseVerdict.RECONCILE
        assert not d.reusable
        assert "external effect" in d.reason

    def test_a_completed_action_does_not_trigger_reconciliation(
        self, db_session, merchant, cycle
    ):
        """A finished external effect is a known outcome, not an unknown one."""
        row = _attempt(db_session, cycle, merchant, 1,
                       AgentRunStatus.partially_completed.value, {"f": 1})
        _action(db_session, merchant, cycle, AgentActionStatus.completed)
        assert decide_reuse(db_session, row, merchant_id=merchant.id).verdict \
            is ReuseVerdict.REUSE

    def test_a_rejected_action_does_not_trigger_reconciliation(
        self, db_session, merchant, cycle
    ):
        row = _attempt(db_session, cycle, merchant, 1,
                       AgentRunStatus.partially_completed.value, {"f": 1})
        _action(db_session, merchant, cycle, AgentActionStatus.rejected)
        assert decide_reuse(db_session, row, merchant_id=merchant.id).verdict \
            is ReuseVerdict.REUSE

    def test_another_tenants_action_cannot_force_reconciliation(
        self, db_session, merchant, cycle
    ):
        """The evidence query is tenant-scoped; a shared key must not leak."""
        other, _u, _m = make_world(db_session, slug_hint="policyother")
        row = _attempt(db_session, cycle, merchant, 1,
                       AgentRunStatus.partially_completed.value, {"f": 1})
        _action(db_session, other, cycle, AgentActionStatus.executing)
        assert decide_reuse(db_session, row, merchant_id=merchant.id).verdict \
            is ReuseVerdict.REUSE


# ════════════════════════════════════════════════════════════════════════════
# Missing or malformed persisted results
# ════════════════════════════════════════════════════════════════════════════


class TestMissingOrMalformedResults:
    @pytest.mark.parametrize("bad", ["not-a-dict", ["a", "list"], 42, None])
    def test_a_malformed_result_is_never_reused(
        self, db_session, merchant, cycle, bad
    ):
        row = _attempt(db_session, cycle, merchant, 1,
                       AgentRunStatus.partially_completed.value, bad)
        d = decide_reuse(db_session, row, merchant_id=merchant.id)
        assert d.verdict is ReuseVerdict.RETRY
        assert not d.reusable

    def test_an_empty_result_is_retried_not_reused(self, db_session, merchant, cycle):
        row = _attempt(db_session, cycle, merchant, 1,
                       AgentRunStatus.partially_completed.value, {})
        assert decide_reuse(db_session, row, merchant_id=merchant.id).verdict \
            is ReuseVerdict.RETRY

    def test_reusable_steps_never_returns_a_malformed_row(
        self, db_session, merchant, cycle
    ):
        _attempt(db_session, cycle, merchant, 0,
                 AgentRunStatus.completed.value, {"ok": 1})
        _attempt(db_session, cycle, merchant, 1,
                 AgentRunStatus.partially_completed.value, "broken")
        wf = WorkflowRunService(db_session)
        keys = {r.step_key for r in wf.reusable_steps(cycle.id).values()}
        assert keys == {step_key("fast", 0, FAST_PLAN[0][0])}


# ════════════════════════════════════════════════════════════════════════════
# Every other status
# ════════════════════════════════════════════════════════════════════════════


class TestOtherStatuses:
    @pytest.mark.parametrize(
        "status", ["failed", "blocked", "skipped", "interrupted"]
    )
    def test_non_productive_statuses_are_retried(self, db_session, merchant, cycle, status):
        row = _attempt(db_session, cycle, merchant, 2, status, {"stale": 1})
        d = decide_reuse(db_session, row, merchant_id=merchant.id)
        assert d.verdict is ReuseVerdict.RETRY
        assert status in d.reason

    def test_a_step_still_recorded_as_running_needs_reconciliation(
        self, db_session, merchant, cycle
    ):
        """Its outcome is genuinely unknown, so neither reuse nor retry is safe."""
        row = _attempt(db_session, cycle, merchant, 2, "running", {"partial": 1})
        d = decide_reuse(db_session, row, merchant_id=merchant.id)
        assert d.verdict is ReuseVerdict.RECONCILE

    def test_an_already_flagged_step_stays_flagged(self, db_session, merchant, cycle):
        """A prior reconciliation finding must not be downgraded to a retry."""
        row = _attempt(db_session, cycle, merchant, 1,
                       AgentRunStatus.needs_reconciliation.value, {"f": 1})
        d = decide_reuse(db_session, row, merchant_id=merchant.id)
        assert d.verdict is ReuseVerdict.RECONCILE
        assert "already flagged" in d.reason


# ════════════════════════════════════════════════════════════════════════════
# Persisting the decision
# ════════════════════════════════════════════════════════════════════════════


class TestReconciliationIsPersisted:
    def test_marking_reconciliation_survives_into_the_next_decision(
        self, db_session, merchant, cycle
    ):
        """Without this, the next recovery would retry the uncertain operation."""
        key = step_key("fast", 1, FAST_PLAN[1][0])
        row = _attempt(db_session, cycle, merchant, 1,
                       AgentRunStatus.partially_completed.value, {"f": 1})
        wf = WorkflowRunService(db_session)
        assert wf.decide(step_row=row, merchant_id=merchant.id).verdict \
            is ReuseVerdict.REUSE

        wf.mark_needs_reconciliation(cycle.id, key)
        db_session.commit()
        db_session.refresh(row)
        assert row.status == AgentRunStatus.needs_reconciliation.value
        assert any("reconciliation" in e for e in row.errors)
        assert wf.decide(step_row=row, merchant_id=merchant.id).verdict \
            is ReuseVerdict.RECONCILE
        assert key not in wf.reusable_steps(cycle.id)

    def test_status_vocabulary_is_preserved_and_distinct(self):
        """The policy must not collapse the existing distinctions."""
        values = [m.value for m in AgentRunStatus]
        for expected in ("completed", "partially_completed", "failed",
                         "interrupted", "blocked", "skipped"):
            assert expected in values
        assert len(values) == len(set(values)), "duplicate status values"


# ════════════════════════════════════════════════════════════════════════════
# Plan identity still governs reuse
# ════════════════════════════════════════════════════════════════════════════


class TestPlanIdentityUnaffected:
    def test_a_changed_plan_is_still_refused(self, db_session, merchant):
        wf = WorkflowRunService(db_session)
        wf.start_workflow(
            merchant_id=merchant.id, run_id="wf-drift2", mode="team",
            plan=AI_TEAM_PLAN,
        )
        db_session.commit()
        from backend.app.services.workflow_run_service import PlanIncompatible

        with pytest.raises(PlanIncompatible):
            wf.assert_plan_compatible(wf.get_workflow(
                merchant_id=merchant.id, run_id="wf-drift2"),
                list(AI_TEAM_PLAN[:-1]), "team")
        db_session.rollback()

    def test_repeated_agents_still_get_distinct_step_keys(self):
        from backend.app.services.workflow_run_service import materialise_plan

        steps = materialise_plan("growth_team", GROWTH_TEAM_PLAN)
        keys = [s["step_key"] for s in steps]
        assert len(keys) == len(set(keys)) == len(GROWTH_TEAM_PLAN)


# ════════════════════════════════════════════════════════════════════════════
# Stale sweep
# ════════════════════════════════════════════════════════════════════════════


class TestStaleSweep:
    def _cycle(self, db_session, merchant, run_id, *, lease, owner="w1"):
        wf = WorkflowRunService(db_session)
        row, _ = wf.start_workflow(
            merchant_id=merchant.id, run_id=run_id, mode="fast", plan=FAST_PLAN
        )
        if lease:
            row.lease_owner = owner
            row.lease_expires_at = lease
        db_session.commit()
        return row

    def test_an_expired_lease_is_reclaimed(self, db_session, merchant):
        from datetime import datetime, timedelta, timezone

        from backend.app.services.workflow_run_service import sweep_stale_workflows

        stale = datetime.now(timezone.utc) - timedelta(minutes=30)
        row = self._cycle(db_session, merchant, "sweep-expired", lease=stale)
        report = sweep_stale_workflows(db_session)
        # System-wide sweep: assert about MY cycle, not a global count.
        assert str(row.id) in report.reclaimed
        wf = WorkflowRunService(db_session).get_workflow(
            merchant_id=merchant.id, run_id="sweep-expired")
        assert wf.status == "interrupted"
        assert wf.lease_owner is None
        assert wf.completed_at is not None, "an abandoned cycle needs an end time"
        assert any("sweep" in (e or "") for e in (wf.errors or [])), (
            "the reason for abandonment must be recorded"
        )

    def test_a_live_lease_is_never_touched(self, db_session, merchant):
        from datetime import datetime, timedelta, timezone

        from backend.app.services.workflow_run_service import sweep_stale_workflows

        live = datetime.now(timezone.utc) + timedelta(minutes=10)
        row = self._cycle(db_session, merchant, "sweep-live", lease=live)
        report = sweep_stale_workflows(db_session)
        assert str(row.id) not in report.reclaimed
        wf = WorkflowRunService(db_session).get_workflow(
            merchant_id=merchant.id, run_id="sweep-live")
        assert wf.status == "running", "a healthy worker must not be reclaimed"

    def test_an_unclaimed_cycle_is_reclaimed(self, db_session, merchant):
        """A cycle created but never claimed has no owner at all."""
        from backend.app.services.workflow_run_service import sweep_stale_workflows

        row = self._cycle(db_session, merchant, "sweep-unclaimed", lease=None)
        report = sweep_stale_workflows(db_session)
        assert str(row.id) in report.reclaimed

    def test_the_sweep_is_idempotent(self, db_session, merchant):
        from datetime import datetime, timedelta, timezone

        from backend.app.services.workflow_run_service import sweep_stale_workflows

        stale = datetime.now(timezone.utc) - timedelta(minutes=30)
        row = self._cycle(db_session, merchant, "sweep-idem", lease=stale)
        first = sweep_stale_workflows(db_session)
        second = sweep_stale_workflows(db_session)
        assert str(row.id) in first.reclaimed
        assert str(row.id) not in second.reclaimed, (
            "a second pass must find the cycle already terminal"
        )
        assert second.reclaimed_count == 0, (
            "nothing else should be stale by now either"
        )

    def test_the_sweep_fences_the_dead_owner_by_bumping_the_generation(
        self, db_session, merchant
    ):
        """Without this the abandoned worker could still write on wake-up."""
        from datetime import datetime, timedelta, timezone

        from backend.app.services.workflow_run_service import sweep_stale_workflows

        stale = datetime.now(timezone.utc) - timedelta(minutes=30)
        row = self._cycle(db_session, merchant, "sweep-fence", lease=stale)
        before = row.lease_generation
        sweep_stale_workflows(db_session)
        db_session.refresh(row)
        assert row.lease_generation > before

    def test_in_flight_steps_are_closed_out(self, db_session, merchant):
        from datetime import datetime, timedelta, timezone

        from backend.app.services.workflow_run_service import sweep_stale_workflows

        stale = datetime.now(timezone.utc) - timedelta(minutes=30)
        row = self._cycle(db_session, merchant, "sweep-steps", lease=stale)
        svc = AgentRunService(db_session)
        svc.start_run(
            merchant_id=merchant.id, agent_name=FAST_PLAN[1][0],
            orchestrator_run_id=row.run_id, workflow_id=row.id,
            step_key=step_key("fast", 1, FAST_PLAN[1][0]), step_index=1, attempt=1,
        )
        db_session.commit()

        report = sweep_stale_workflows(db_session)
        assert report.steps_interrupted
        step = db_session.query(AgentRun).filter(
            AgentRun.workflow_id == row.id).one()
        assert step.status == AgentRunStatus.interrupted.value
        assert step.completed_at is not None

    def test_a_finished_cycle_is_never_swept(self, db_session, merchant):
        from datetime import datetime, timedelta, timezone

        from backend.app.services.workflow_run_service import sweep_stale_workflows

        stale = datetime.now(timezone.utc) - timedelta(minutes=30)
        row = self._cycle(db_session, merchant, "sweep-done", lease=stale)
        row.status = "completed"
        db_session.commit()
        report = sweep_stale_workflows(db_session)
        assert "sweep-done" not in report.reclaimed
        db_session.refresh(row)
        assert row.status == "completed"

    def test_grace_period_delays_reclamation(self, db_session, merchant):
        from datetime import datetime, timedelta, timezone

        from backend.app.services.workflow_run_service import sweep_stale_workflows

        recently = datetime.now(timezone.utc) - timedelta(seconds=30)
        row = self._cycle(db_session, merchant, "sweep-grace", lease=recently)
        assert str(row.id) in sweep_stale_workflows(
            db_session, grace_seconds=0).reclaimed

        fresh = datetime.now(timezone.utc) - timedelta(seconds=30)
        held = self._cycle(db_session, merchant, "sweep-grace2", lease=fresh)
        report = sweep_stale_workflows(db_session, grace_seconds=3600)
        assert str(held.id) not in report.reclaimed, (
            "a generous grace period must hold back a recently-expired lease"
        )
        db_session.refresh(held)
        assert held.status == "running"

    def test_max_batch_bounds_the_pass(self, db_session, merchant):
        from datetime import datetime, timedelta, timezone

        from backend.app.services.workflow_run_service import sweep_stale_workflows

        stale = datetime.now(timezone.utc) - timedelta(minutes=30)
        for i in range(3):
            self._cycle(db_session, merchant, f"sweep-batch-{i}", lease=stale)
        report = sweep_stale_workflows(db_session, max_batch=2)
        assert report.scanned <= 2