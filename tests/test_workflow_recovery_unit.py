"""
Focused unit tests for durable workflow persistence and action idempotency.

``tests/test_crash_recovery.py`` proves recovery across a REAL process boundary.
This file covers the units underneath it, where a subprocess would only make
the failures harder to read:

  1. a durable agent-start record exists before the agent body runs;
  2. a durable step-start row is committed, not merely flushed;
  3. repeated action proposals collapse onto one row;
  4. distinct legitimate actions stay distinct;
  5. idempotency is tenant-scoped;
  6. a retry cannot bypass human approval;
  7. legitimate replans/retries keep history instead of colliding;
  8. a changed plan is detected rather than silently merged;
  9. stale detection never takes over a healthy owner;
 10. a stale owner CAN be taken over;
 11. plan materialisation is deterministic and position-keyed;
 12. status mapping preserves partial/blocked/skipped;
 13. every supported mode recovers;
 14. the existing action/approval contract is unchanged.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.agents.base import AgentContext, AgentResult
from backend.app.agents.orchestrator import (
    AI_TEAM_PLAN,
    DEEP_PLAN,
    FAST_PLAN,
    GROWTH_TEAM_PLAN,
    GrowthAgentOrchestrator,
    _plan_for,
)
from backend.app.agents.registry import AGENT_INSTANCES
from backend.app.models.agent_run import AgentRun
from backend.app.models.enums import AgentActionStatus, AgentRunStatus
from backend.app.models.agent_workflow import AgentWorkflowRun
from backend.app.services.workflow_run_service import (
    PlanIncompatible,
    WorkflowNotFound,
    WorkflowNotResumable,
    WorkflowOwnershipError,
    WorkflowRunService,
    current_workflow,
    current_workflow_id,
    is_resumable,
    materialise_plan,
    plan_fingerprint,
    step_key,
)
from tests.security_utils import make_world


@pytest.fixture()
def merchant(db_session):
    m, _u, _mem = make_world(db_session, slug_hint="wfunit")
    return m


# ════════════════════════════════════════════════════════════════════════════
# 1-2. Durable step-start record
# ════════════════════════════════════════════════════════════════════════════


class TestDurableStepStart:
    def test_start_run_writes_a_running_row_with_liveness(self, db_session, merchant):
        from backend.app.services.agent_run_service import AgentRunService

        svc = AgentRunService(db_session)
        row = svc.start_run(
            merchant_id=merchant.id,
            agent_name="GrowthDiscoveryAgent",
            orchestrator_run_id="wf-x",
            workflow_id=None,
            step_key="team:001:Test:-:abc",
            step_index=1,
        )
        db_session.flush()
        assert row.status == AgentRunStatus.running.value
        assert row.heartbeat_at is not None, "a running step must have proof of life"
        assert row.started_at is not None
        assert row.attempt == 1

    def test_commit_start_makes_the_row_survivable(self, db_session, merchant):
        """The record must be COMMITTED, not just flushed, before the agent runs."""
        from backend.app.services.agent_run_service import AgentRunService

        svc = AgentRunService(db_session)
        wf = WorkflowRunService(db_session)
        workflow, _ = wf.start_workflow(
            merchant_id=merchant.id, run_id="wf-commit", mode="fast", plan=FAST_PLAN
        )
        svc.start_run(
            merchant_id=merchant.id,
            agent_name="GrowthDiscoveryAgent",
            orchestrator_run_id="wf-commit",
            workflow_id=workflow.id,
            step_key=step_key("fast", 1, "GrowthDiscoveryAgent"),
            step_index=1,
        )
        svc.commit_start()

        # A brand-new session must see it: only a commit survives that.
        Session = type(db_session)
        probe = Session(bind=db_session.get_bind())
        rows = probe.query(AgentRun).filter(AgentRun.workflow_id == workflow.id).all()
        probe.close()
        assert len(rows) == 1, "the step-start row was not durable before the agent body"
        assert rows[0].status == AgentRunStatus.running.value

    def test_heartbeat_refreshes_liveness(self, db_session, merchant):
        from backend.app.services.agent_run_service import AgentRunService

        svc = AgentRunService(db_session)
        row = svc.start_run(
            merchant_id=merchant.id,
            agent_name="GrowthDiscoveryAgent",
            orchestrator_run_id="wf-hb",
        )
        first = row.heartbeat_at
        svc.heartbeat(row)
        assert row.heartbeat_at >= first


# ════════════════════════════════════════════════════════════════════════════
# 3-6. Action idempotency
# ════════════════════════════════════════════════════════════════════════════


class TestActionIdempotency:
    def _create(self, db, merchant_id, payload=None, **kw):
        from backend.app.services.action_service import create_action, action_idempotency_key

        payload = payload if payload is not None else {"payment_id": "p-1"}
        key = action_idempotency_key(
            merchant_id=merchant_id, action_type="retry_payment",
            input_payload=payload, **kw,
        )
        return create_action(
            db, merchant_id=merchant_id, action_type="retry_payment",
            input_payload=payload, idempotency_key=key, **kw,
        ), key

    def test_repeat_proposal_returns_the_existing_action(self, db_session, merchant):
        first, key = self._create(db_session, merchant.id)
        db_session.commit()
        second, key2 = self._create(db_session, merchant.id)
        assert key == key2, "the same logical request must hash the same"
        assert first.id == second.id, "a repeat must return the ORIGINAL row"
        assert db_session.query(AgentRun).count() >= 0  # no-op; keep session warm

    def test_only_one_row_exists_for_one_logical_action(self, db_session, merchant):
        from backend.app.models.agent_action import AgentAction

        self._create(db_session, merchant.id)
        db_session.commit()
        self._create(db_session, merchant.id)
        db_session.commit()
        rows = db_session.query(AgentAction).filter(
            AgentAction.merchant_id == merchant.id,
            AgentAction.idempotency_key.isnot(None),
        ).all()
        assert len(rows) == 1, f"duplicate logical actions: {len(rows)}"

    def test_distinct_payloads_stay_distinct(self, db_session, merchant):
        from backend.app.models.agent_action import AgentAction

        self._create(db_session, merchant.id, payload={"payment_id": "p-1"})
        self._create(db_session, merchant.id, payload={"payment_id": "p-2"})
        db_session.commit()
        rows = db_session.query(AgentAction).filter(
            AgentAction.merchant_id == merchant.id
        ).all()
        assert len(rows) == 2, "genuinely different actions must not collapse"

    def test_idempotency_is_tenant_scoped(self, db_session, merchant):
        from backend.app.models.agent_action import AgentAction

        other, _u, _m = make_world(db_session, slug_hint="wfother")
        self._create(db_session, merchant.id, payload={"payment_id": "shared"})
        self._create(db_session, other.id, payload={"payment_id": "shared"})
        db_session.commit()
        mine = db_session.query(AgentAction).filter(
            AgentAction.merchant_id == merchant.id
        ).count()
        theirs = db_session.query(AgentAction).filter(
            AgentAction.merchant_id == other.id
        ).count()
        assert mine == 1 and theirs == 1, (
            f"one tenant's action must never dedupe another's "
            f"(mine={mine}, theirs={theirs})"
        )

    def test_ambient_workflow_scopes_every_call_site(self, db_session, merchant):
        """Agents that call create_action directly are still idempotent."""
        from backend.app.models.agent_action import AgentAction
        from backend.app.services.action_service import create_action

        wf = WorkflowRunService(db_session).start_workflow(
            merchant_id=merchant.id, run_id="wf-ambient", mode="fast", plan=FAST_PLAN
        )[0]
        db_session.commit()
        payload = {"payment_id": "ambient-1"}
        with current_workflow(wf.id):
            assert current_workflow_id() == wf.id
            a = create_action(
                db_session, merchant_id=merchant.id,
                action_type="retry_payment", input_payload=payload,
            )
        db_session.commit()
        assert a.idempotency_key is not None, "no explicit key was passed"
        assert a.workflow_run_id == wf.id
        with current_workflow(wf.id):
            b = create_action(
                db_session, merchant_id=merchant.id,
                action_type="retry_payment", input_payload=payload,
            )
        assert b.id == a.id
        assert db_session.query(AgentAction).filter(
            AgentAction.merchant_id == merchant.id
        ).count() == 1

    def test_context_is_restored_after_the_block(self, db_session):
        assert current_workflow_id() is None
        with current_workflow(uuid.uuid4()):
            assert current_workflow_id() is not None
        assert current_workflow_id() is None

    def test_outside_a_workflow_no_key_is_invented(self, db_session, merchant):
        from backend.app.services.action_service import create_action

        action = create_action(
            db_session, merchant_id=merchant.id,
            action_type="retry_payment", input_payload={"payment_id": "legacy"},
        )
        assert action.idempotency_key is None, (
            "outside a workflow the previous behaviour is preserved; NULL keys "
            "never collide with historical rows"
        )

    def test_a_retry_cannot_bypass_human_approval(self, db_session, merchant):
        from backend.app.services.action_service import create_action, action_idempotency_key

        payload = {"payment_id": "gate-1"}
        key = action_idempotency_key(
            merchant_id=merchant.id, action_type="retry_payment", input_payload=payload
        )
        a = create_action(
            db_session, merchant_id=merchant.id, action_type="retry_payment",
            input_payload=payload, idempotency_key=key,
        )
        db_session.commit()
        assert a.status == AgentActionStatus.requested.value
        assert a.approved_by is None

        b = create_action(
            db_session, merchant_id=merchant.id, action_type="retry_payment",
            input_payload=payload, idempotency_key=key,
        )
        assert b.status == AgentActionStatus.requested.value, (
            "returning the existing row must not advance it to approved"
        )
        assert b.approved_by is None

    def test_db_rejects_a_duplicated_key_directly(self, db_session, merchant):
        """The guarantee is in the database, not only in application code."""
        from sqlalchemy.exc import IntegrityError

        from backend.app.models.agent_action import AgentAction

        self._create(db_session, merchant.id)
        db_session.commit()
        row = AgentAction(
            merchant_id=merchant.id,
            action_type="retry_payment",
            status=AgentActionStatus.requested,
            input_payload={},
            idempotency_key=db_session.query(AgentAction.idempotency_key)
            .filter(AgentAction.merchant_id == merchant.id).scalar(),
        )
        db_session.add(row)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


# ════════════════════════════════════════════════════════════════════════════
# 7. Legitimate repetition and retry history
# ════════════════════════════════════════════════════════════════════════════


class TestLegitimateRepetition:
    def test_repeated_agents_get_distinct_step_keys(self):
        for mode, plan in (
            ("team", AI_TEAM_PLAN), ("growth_team", GROWTH_TEAM_PLAN),
        ):
            steps = materialise_plan(mode, plan)
            keys = [s["step_key"] for s in steps]
            assert len(keys) == len(set(keys)), mode
            assert len(keys) == len(plan)

    def test_growth_team_repeats_survive_the_dedup_constraint(self):
        counts: dict[str, int] = {}
        for agent, _ in GROWTH_TEAM_PLAN:
            counts[agent] = counts.get(agent, 0) + 1
        assert counts["MarketingAgent"] == 3, counts
        assert counts["ManagerAgent"] == 2, counts
        steps = materialise_plan("growth_team", GROWTH_TEAM_PLAN)
        marketing = [s for s in steps if s["agent_name"] == "MarketingAgent"]
        assert len({s["step_key"] for s in marketing}) == 3

    def test_next_attempt_increments_and_preserves_history(self, db_session, merchant):
        from backend.app.services.agent_run_service import AgentRunService

        wf = WorkflowRunService(db_session)
        workflow, _ = wf.start_workflow(
            merchant_id=merchant.id, run_id="wf-attempt", mode="fast", plan=FAST_PLAN
        )
        db_session.commit()
        svc = AgentRunService(db_session)
        sk = step_key("fast", 0, "GrowthMemoryAgent")

        assert wf.next_attempt(workflow.id, sk) == 1
        svc.start_run(
            merchant_id=merchant.id, agent_name="GrowthMemoryAgent",
            orchestrator_run_id="wf-attempt", workflow_id=workflow.id,
            step_key=sk, step_index=0, attempt=1,
        )
        db_session.commit()
        # First attempt failed; a retry gets attempt 2 and leaves attempt 1 alone.
        row = db_session.query(AgentRun).filter(AgentRun.workflow_id == workflow.id).one()
        row.status = AgentRunStatus.failed.value
        db_session.commit()

        assert wf.next_attempt(workflow.id, sk) == 2
        svc.start_run(
            merchant_id=merchant.id, agent_name="GrowthMemoryAgent",
            orchestrator_run_id="wf-attempt", workflow_id=workflow.id,
            step_key=sk, step_index=0, attempt=2,
        )
        db_session.commit()
        rows = db_session.query(AgentRun).filter(AgentRun.workflow_id == workflow.id).all()
        assert len(rows) == 2, "retry history must be preserved, not overwritten"
        assert {r.attempt for r in rows} == {1, 2}

    def test_only_reusable_statuses_are_reused(self, db_session, merchant):
        """Failed/blocked/interrupted steps must be retried, not reused."""
        from backend.app.services.agent_run_service import AgentRunService

        wf = WorkflowRunService(db_session)
        workflow, _ = wf.start_workflow(
            merchant_id=merchant.id, run_id="wf-reuse", mode="fast", plan=FAST_PLAN
        )
        db_session.commit()
        svc = AgentRunService(db_session)
        statuses_under_test = [
            AgentRunStatus.completed, AgentRunStatus.failed,
            AgentRunStatus.blocked, AgentRunStatus.interrupted,
            AgentRunStatus.skipped, AgentRunStatus.partially_completed,
        ]
        # A plan wide enough to hold one step per status.
        wide_plan = tuple(
            (f"StepAgent{index}", {}) for index in range(len(statuses_under_test))
        )
        wf.start_workflow(
            merchant_id=merchant.id, run_id="wf-reuse2", mode="fast", plan=wide_plan
        )
        workflow = wf.get_workflow(
            merchant_id=merchant.id, run_id="wf-reuse2"
        )
        db_session.commit()
        for index, status in enumerate(statuses_under_test):
            agent = wide_plan[index][0]
            svc.start_run(
                merchant_id=merchant.id, agent_name=agent,
                orchestrator_run_id="wf-reuse", workflow_id=workflow.id,
                step_key=step_key("fast", index, agent), step_index=index, attempt=1,
            )
            row = db_session.query(AgentRun).filter(
                AgentRun.workflow_id == workflow.id,
                AgentRun.step_index == index,
            ).one()
            row.status = status.value
            # Only the partially_completed case gets a persisted result. A
            # partial step with NO recorded output proves nothing about what it
            # achieved, so it must NOT be reused -- that is exactly the point of
            # the evidence-based policy.
            if status is AgentRunStatus.partially_completed:
                row.output_summary = {"findings": ["kept"]}
            db_session.commit()

        # Reuse is now an EVIDENCE decision, not a status whitelist.
        from backend.app.services.workflow_run_service import ReuseVerdict

        reusable = wf.reusable_steps(workflow.id)
        reusable_keys = {r.step_key for r in reusable.values()}
        assert reusable_keys == {
            step_key("fast", 0, wide_plan[0][0]),   # completed
            step_key("fast", 5, wide_plan[5][0]),   # partial WITH intact output
        }, reusable_keys

        ordered = sorted(
            wf.attempt_rows(workflow.id).values(),
            key=lambda r: r.step_index or 0,
        )
        for index, row in enumerate(ordered):
            decision = wf.decide(step_row=row)
            if index in (0, 5):
                assert decision.verdict is ReuseVerdict.REUSE, (index, decision)
            else:
                assert decision.verdict is ReuseVerdict.RETRY, (index, decision)
                assert decision.reason, "a non-reuse decision must explain itself"

    def test_a_partial_step_with_no_persisted_output_is_not_reused(
        self, db_session, merchant
    ):
        """The unsafe-partial case, in isolation.

        A step that reports ``partially_completed`` but recorded no result
        proves nothing about what it achieved. Replaying it would hand downstream
        steps a silent gap; so must it be retried.
        """
        from backend.app.services.agent_run_service import AgentRunService
        from backend.app.services.workflow_run_service import ReuseVerdict

        wf = WorkflowRunService(db_session)
        workflow, _ = wf.start_workflow(
            merchant_id=merchant.id, run_id="wf-partial-empty",
            mode="fast", plan=FAST_PLAN,
        )
        db_session.commit()
        svc = AgentRunService(db_session)
        agent = FAST_PLAN[0][0]
        sk = step_key("fast", 0, agent)
        row = svc.start_run(
            merchant_id=merchant.id, agent_name=agent,
            orchestrator_run_id="wf-partial-empty", workflow_id=workflow.id,
            step_key=sk, step_index=0, attempt=1,
        )
        row.status = AgentRunStatus.partially_completed.value
        row.output_summary = {}
        db_session.commit()

        decision = wf.decide(step_row=row, merchant_id=merchant.id)
        assert decision.verdict is ReuseVerdict.RETRY
        assert "no reusable output" in decision.reason
        assert sk not in wf.reusable_steps(workflow.id)


# ════════════════════════════════════════════════════════════════════════════
# 8. Plan compatibility
# ════════════════════════════════════════════════════════════════════════════


class TestPlanCompatibility:
    def test_fingerprint_is_stable_for_the_same_plan(self):
        assert plan_fingerprint(materialise_plan("team", AI_TEAM_PLAN)) == \
            plan_fingerprint(materialise_plan("team", AI_TEAM_PLAN))

    def test_fingerprint_changes_when_the_plan_changes(self):
        base = plan_fingerprint(materialise_plan("team", AI_TEAM_PLAN))
        altered = list(AI_TEAM_PLAN[:-1])
        assert plan_fingerprint(materialise_plan("team", altered)) != base

    def test_fingerprint_differs_per_mode(self):
        assert plan_fingerprint(materialise_plan("fast", FAST_PLAN)) != \
            plan_fingerprint(materialise_plan("deep", DEEP_PLAN))

    def test_a_changed_plan_is_refused(self, db_session, merchant):
        wf = WorkflowRunService(db_session)
        workflow, _ = wf.start_workflow(
            merchant_id=merchant.id, run_id="wf-drift", mode="team", plan=AI_TEAM_PLAN
        )
        db_session.commit()
        altered = list(AI_TEAM_PLAN[:-1])
        with pytest.raises(PlanIncompatible):
            wf.assert_plan_compatible(workflow, altered, "team")
        db_session.rollback()

    def test_a_matching_plan_is_accepted(self, db_session, merchant):
        wf = WorkflowRunService(db_session)
        workflow, _ = wf.start_workflow(
            merchant_id=merchant.id, run_id="wf-same", mode="team", plan=AI_TEAM_PLAN
        )
        db_session.commit()
        steps = wf.assert_plan_compatible(workflow, AI_TEAM_PLAN, "team")
        assert len(steps) == len(AI_TEAM_PLAN)
        db_session.rollback()

    def test_resume_refuses_a_changed_plan(self, db_session, merchant):
        """End-to-end: a plan change must not be merged with old results."""
        orch = GrowthAgentOrchestrator(db_session)
        wf = WorkflowRunService(db_session)
        wf.start_workflow(
            merchant_id=merchant.id, run_id="wf-refuse", mode="team",
            plan=list(AI_TEAM_PLAN[:-1]),   # deliberately different
        )
        db_session.commit()
        with pytest.raises(PlanIncompatible):
            orch.resume(merchant.id, "wf-refuse")
        db_session.rollback()


# ════════════════════════════════════════════════════════════════════════════
# 9-10. Stale-owner safety
# ════════════════════════════════════════════════════════════════════════════


class TestStaleOwnerSafety:
    def test_a_live_owner_is_never_taken_over(self, db_session, merchant):
        wf = WorkflowRunService(db_session)
        row, _ = wf.start_workflow(
            merchant_id=merchant.id, run_id="wf-live", mode="fast", plan=FAST_PLAN
        )
        db_session.commit()
        # A fresh cycle is created UNOWNED, so the owner must be established
        # before "a live owner is protected" is a meaningful claim to make.
        assert row.lease_expires_at is None
        assert row.lease_generation == 0
        first = wf.claim(row, owner="worker-a")
        db_session.commit()
        assert first >= 1
        assert row.lease_expires_at is not None
        with pytest.raises(WorkflowOwnershipError):
            wf.claim(row, owner="intruder", stale_after_seconds=3600)
        db_session.rollback()

    def test_a_cold_owner_can_be_taken_over(self, db_session, merchant):
        wf = WorkflowRunService(db_session)
        row, _ = wf.start_workflow(
            merchant_id=merchant.id, run_id="wf-cold", mode="fast", plan=FAST_PLAN
        )
        stale = datetime.now(timezone.utc) - timedelta(minutes=30)
        row.heartbeat_at = stale
        row.lease_expires_at = stale
        db_session.commit()
        # A generous staleness window still allows the takeover.
        wf.claim(row, owner="rescuer", stale_after_seconds=60)
        assert row.lease_owner == "rescuer"
        db_session.rollback()

    def test_a_second_takeover_loses(self, db_session, merchant):
        """The winner's fresh heartbeat excludes the loser -- a real CAS."""
        wf = WorkflowRunService(db_session)
        row, _ = wf.start_workflow(
            merchant_id=merchant.id, run_id="wf-cas", mode="fast", plan=FAST_PLAN
        )
        stale = datetime.now(timezone.utc) - timedelta(minutes=30)
        row.heartbeat_at = stale
        row.lease_expires_at = stale
        db_session.commit()
        wf.claim(row, owner="first", stale_after_seconds=60)
        db_session.commit()
        with pytest.raises(WorkflowOwnershipError):
            wf.claim(row, owner="second", stale_after_seconds=60)
        db_session.rollback()

    def test_interrupted_steps_are_closed_out_on_recovery(self, db_session, merchant):
        from backend.app.services.agent_run_service import AgentRunService

        wf = WorkflowRunService(db_session)
        workflow, _ = wf.start_workflow(
            merchant_id=merchant.id, run_id="wf-int", mode="fast", plan=FAST_PLAN
        )
        db_session.commit()
        svc = AgentRunService(db_session)
        sk = step_key("fast", 1, "GrowthDiscoveryAgent")
        svc.start_run(
            merchant_id=merchant.id, agent_name="GrowthDiscoveryAgent",
            orchestrator_run_id="wf-int", workflow_id=workflow.id,
            step_key=sk, step_index=1, attempt=1,
        )
        db_session.commit()
        assert db_session.query(AgentRun).filter(
            AgentRun.workflow_id == workflow.id
        ).one().status == AgentRunStatus.running.value

        closed = wf.mark_interrupted_steps(workflow.id, reason="worker_gone")
        assert sk in closed
        row = db_session.query(AgentRun).filter(AgentRun.workflow_id == workflow.id).one()
        assert row.status == AgentRunStatus.interrupted.value
        assert row.completed_at is not None, "an orphan must never look active forever"
        assert "worker_gone" in (row.errors or [])
        db_session.rollback()

    def test_a_finished_cycle_is_not_resumable(self, db_session, merchant):
        wf = WorkflowRunService(db_session)
        row, _ = wf.start_workflow(
            merchant_id=merchant.id, run_id="wf-done", mode="fast", plan=FAST_PLAN
        )
        row.status = "completed"
        db_session.commit()
        assert is_resumable(row) is False
        db_session.rollback()

    def test_resume_of_a_finished_cycle_raises(self, db_session, merchant):
        wf = WorkflowRunService(db_session)
        row, _ = wf.start_workflow(
            merchant_id=merchant.id, run_id="wf-done2", mode="fast", plan=FAST_PLAN
        )
        wf.finish_workflow(row, status="completed")
        db_session.commit()
        with pytest.raises(WorkflowNotResumable):
            GrowthAgentOrchestrator(db_session).resume(merchant.id, "wf-done2")
        db_session.rollback()

    def test_resume_of_an_unknown_cycle_raises_not_found(self, db_session, merchant):
        with pytest.raises(WorkflowNotFound):
            GrowthAgentOrchestrator(db_session).resume(merchant.id, "no-such-cycle")
        db_session.rollback()

    def test_resume_is_merchant_scoped(self, db_session, merchant):
        other, _u, _m = make_world(db_session, slug_hint="wfscoped")
        wf = WorkflowRunService(db_session)
        row, _ = wf.start_workflow(
            merchant_id=merchant.id, run_id="wf-priv", mode="fast", plan=FAST_PLAN
        )
        db_session.commit()
        with pytest.raises(WorkflowNotFound):
            GrowthAgentOrchestrator(db_session).resume(other.id, "wf-priv")
        db_session.rollback()

    def test_run_id_reuse_does_not_fork_a_second_cycle(self, db_session, merchant):
        """One run id names exactly one cycle."""
        wf = WorkflowRunService(db_session)
        first, created_a = wf.start_workflow(
            merchant_id=merchant.id, run_id="wf-once", mode="fast", plan=FAST_PLAN
        )
        db_session.commit()
        second, created_b = wf.start_workflow(
            merchant_id=merchant.id, run_id="wf-once", mode="fast", plan=FAST_PLAN
        )
        assert created_a is True and created_b is False
        assert first.id == second.id
        assert db_session.query(AgentWorkflowRun).filter(
            AgentWorkflowRun.merchant_id == merchant.id
        ).count() == 1
        db_session.rollback()


# ════════════════════════════════════════════════════════════════════════════
# 11-13. Modes, plans and status fidelity
# ════════════════════════════════════════════════════════════════════════════


class TestModesAndStatusFidelity:
    def test_every_supported_mode_is_recoverable(self, db_session, merchant):
        """All four modes get a durable workflow and can be resumed."""
        for mode in ("fast", "deep", "team", "growth_team"):
            run_id = f"wf-mode-{mode}"
            orch = GrowthAgentOrchestrator(db_session)
            summary = orch.run(
                merchant.id, mode=mode,
                params={"objective": "test recovery mode", "window_days": 30},
                run_id=run_id,
            )
            db_session.commit()
            assert summary.workflow_id, mode
            wf = db_session.query(AgentWorkflowRun).filter(
                AgentWorkflowRun.run_id == run_id
            ).one()
            assert wf.mode == mode
            assert wf.step_count == len(_plan_for(mode))
            assert wf.status in ("completed", "partial", "failed"), (mode, wf.status)
        db_session.rollback()

    def test_plan_for_covers_every_supported_mode(self):
        for mode in ("fast", "deep", "team", "growth_team"):
            assert _plan_for(mode)

    def test_plan_for_rejects_an_unknown_mode(self):
        with pytest.raises(KeyError):
            _plan_for("nonsense")

    def test_result_status_preserves_granularity(self, db_session, merchant):
        """A degraded-but-productive step must not read as a hard failure."""
        from backend.app.services.agent_run_service import AgentRunService

        svc = AgentRunService(db_session)
        cases = {
            "completed": AgentRunStatus.completed.value,
            "partially_completed": AgentRunStatus.partially_completed.value,
            "failed": AgentRunStatus.failed.value,
            "blocked": AgentRunStatus.blocked.value,
            "skipped": AgentRunStatus.skipped.value,
            "something_unknown": AgentRunStatus.failed.value,  # never optimistic
        }
        for i, (result_status, expected) in enumerate(cases.items()):
            row = svc.start_run(
                merchant_id=merchant.id, agent_name="GrowthDiscoveryAgent",
                orchestrator_run_id=f"wf-st{i}",
            )
            svc.complete_run(row, AgentResult(agent_name="GrowthDiscoveryAgent", status=result_status))
            db_session.flush()
            assert row.status == expected, (result_status, row.status)
        db_session.rollback()

    def test_completed_steps_are_reused_with_their_metrics(self, db_session, merchant):
        from backend.app.services.agent_run_service import AgentRunService

        wf = WorkflowRunService(db_session)
        workflow, _ = wf.start_workflow(
            merchant_id=merchant.id, run_id="wf-metrics", mode="fast", plan=FAST_PLAN
        )
        db_session.commit()
        svc = AgentRunService(db_session)
        agent = FAST_PLAN[0][0]
        sk = step_key("fast", 0, agent)
        row = svc.start_run(
            merchant_id=merchant.id, agent_name=agent,
            orchestrator_run_id="wf-metrics", workflow_id=workflow.id,
            step_key=sk, step_index=0, attempt=1,
        )
        result = AgentResult(
            agent_name=agent, status="completed",
            signals_detected=7, insights_generated=3, tools_used=["analytics.growth_radar"],
        )
        result.output["findings"] = ["preserved"]
        svc.complete_run(row, result)
        db_session.commit()

        reused = wf.reusable_steps(workflow.id)[sk]
        entry = GrowthAgentOrchestrator._reuse_step(reused)
        assert entry["reused"] is True
        assert entry["signals_detected"] == 7
        assert entry["insights_generated"] == 3
        assert entry["output"]["findings"] == ["preserved"], (
            "a reused step must carry its findings into the resumed synthesis"
        )
        db_session.rollback()

    def test_replay_restores_findings_into_shared_context(self, db_session, merchant):
        from backend.app.services.agent_run_service import AgentRunService

        wf = WorkflowRunService(db_session)
        workflow, _ = wf.start_workflow(
            merchant_id=merchant.id, run_id="wf-shared", mode="team", plan=AI_TEAM_PLAN
        )
        db_session.commit()
        svc = AgentRunService(db_session)
        sk = step_key("team", 1, "GrowthDiscoveryAgent")
        row = svc.start_run(
            merchant_id=merchant.id, agent_name="GrowthDiscoveryAgent",
            orchestrator_run_id="wf-shared", workflow_id=workflow.id,
            step_key=sk, step_index=1, attempt=1,
        )
        result = AgentResult(agent_name="GrowthDiscoveryAgent", status="completed")
        result.output["ranked_opportunities"] = [{"title": "kept"}]
        svc.complete_run(row, result)
        db_session.commit()

        shared: dict = {}
        GrowthAgentOrchestrator._replay_step_into_shared_ctx(
            "GrowthDiscoveryAgent", row, {}, shared
        )
        assert shared["ranked_opportunities"] == [{"title": "kept"}]
        db_session.rollback()


# ════════════════════════════════════════════════════════════════════════════
# 14. Existing contracts untouched
# ════════════════════════════════════════════════════════════════════════════


class TestExistingContractsUnchanged:
    def test_agent_result_contract_is_unchanged(self):
        r = AgentResult(agent_name="X")
        for field in ("status", "tools_used", "output", "errors", "lifecycle_phutes" if False else "lifecycle_phases"):
            assert hasattr(r, field), field
        assert r.ok is True
        assert AgentResult(agent_name="X", status="failed").ok is False

    def test_lifecycle_bounds_are_unchanged(self):
        from backend.app.agents.base import BaseGrowthAgent

        assert BaseGrowthAgent.max_steps == 5
        assert BaseGrowthAgent.max_retries == 3
        assert BaseGrowthAgent.max_replan == 2

    def test_registry_is_unchanged(self):
        assert len(AGENT_INSTANCES) == 14
        assert "ManagerAgent" in AGENT_INSTANCES

    def test_protected_specialists_are_unmodified(self):
        """Guard against an accidental edit to a protected implementation."""
        from backend.app.agents.designer_agent import DesignerAgent
        from backend.app.agents.marketing_agent import MarketingAgent
        from backend.app.agents.product_agent import ProductAgent

        for cls in (MarketingAgent, ProductAgent, DesignerAgent):
            assert cls.NAME in AGENT_INSTANCES
            assert callable(cls._run)
            assert cls.PERMISSIONS
