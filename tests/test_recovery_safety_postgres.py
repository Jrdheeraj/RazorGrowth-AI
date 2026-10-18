"""
Phase 2 recovery safety against PostgreSQL: lease fencing and sweep races.

WHAT ONLY POSTGRESQL CAN PROVE HERE
-----------------------------------
``_assert_generation`` locks the workflow row with ``SELECT ... FOR UPDATE``
before every protected write. That lock is what makes the fencing check atomic
with the write that follows it: a concurrent takeover blocks on the lock, and by
the time it re-evaluates its own predicate the generation has been consumed.

On SQLite there is no ``FOR UPDATE``. SQLite's single-writer model serialises
the whole database instead, which happens to give the same ordering for THIS
pattern -- but it is a different mechanism and is deliberately NOT described as
equivalent. These tests exist to prove the PostgreSQL behaviour.

THE SCENARIO THAT MATTERS
-------------------------
1. Worker A claims generation N and starts a step.
2. Worker A is descheduled (GC pause, container freeze, node drain).
3. Its lease expires. Worker B legitimately takes over, generation becomes N+1.
4. Worker A wakes up and tries to record its step's outcome.

Step 4 is the danger. Without fencing, A overwrites B's cycle state and marks a
step complete that B is actively re-running.

Run ONLY when ``POSTGRES_DSN`` is set; skipping is deliberate, because a green
SQLite result would be a false claim about row-lock semantics.
"""
from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

DSN = os.environ.get("POSTGRES_DSN")

pytestmark = pytest.mark.skipif(
    not DSN or "postgres" not in (DSN or "").split("://")[0],
    reason="POSTGRES_DSN not set to a PostgreSQL DSN; SQLite has no "
           "SELECT ... FOR UPDATE, so it cannot prove fencing atomicity",
)

if DSN:
    os.environ["DATABASE_URL"] = DSN
    for _k, _v in {
        "EXECUTION_ENABLED": "false", "RAZORPAY_ENABLED": "false",
        "RAZORPAY_TEST_MODE": "false", "REAL_TEST_INTEGRATION_ENABLED": "false",
        "AUTH_MODE": "optional", "APP_ENV": "testing",
        "CLOUDFLARE_API_TOKEN": "", "CLOUDFLARE_ACCOUNT_ID": "",
        "OPENROUTER_API_KEY": "", "LLM_API_KEY": "",
        "IMAGE_GENERATION_ENABLED": "false",
    }.items():
        os.environ[_k] = _v

    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import sessionmaker

    import backend.app.main  # noqa: F401
    from backend.app.models.agent_action import AgentAction
    from backend.app.models.agent_run import AgentRun
    from backend.app.models.agent_workflow import AgentWorkflowRun
    from backend.app.models.enums import (
        AgentActionStatus,
        AgentRunStatus,
        Currency,
        MerchantStatus,
    )
    from backend.app.models.merchant import Merchant

    _sf = sessionmaker(
        bind=create_engine(DSN, future=True), expire_on_commit=False
    )

    def session():
        """A dedicated connection. Each worker must have its own."""
        return _sf()


@pytest.fixture()
def merchant():
    s = session()
    try:
        m = Merchant(name="Fence", slug=f"pgfence-{uuid.uuid4().hex[:10]}",
                     email=f"{uuid.uuid4().hex[:8]}@pg.test",
                     status=MerchantStatus.active, currency=Currency.INR)
        s.add(m)
        s.commit()
        s.expire_all()
        return s.get(Merchant, m.id)
    finally:
        s.close()


def _new_cycle(merchant, run_id, *, mode="fast"):
    from backend.app.agents.orchestrator import FAST_PLAN
    from backend.app.services.workflow_run_service import WorkflowRunService

    s = session()
    try:
        wf = WorkflowRunService(s)
        row, _ = wf.start_workflow(
            merchant_id=merchant.id, run_id=run_id, mode=mode, plan=FAST_PLAN
        )
        s.commit()
        s.expire_all()
        return s.get(AgentWorkflowRun, row.id)
    finally:
        s.close()


def _expire_lease(workflow_id):
    """Age a cycle's lease out, simulating a worker that stopped heartbeating."""
    s = session()
    try:
        s.execute(text(
            "UPDATE agent_workflow_runs SET lease_expires_at = "
            "now() - interval '1 hour' WHERE id = :i"), {"i": workflow_id})
        s.commit()
    finally:
        s.close()


def _load(workflow_id, sess=None):
    own = sess is None
    s = sess or session()
    try:
        return s.get(AgentWorkflowRun, workflow_id)
    finally:
        if own:
            s.close()


# ════════════════════════════════════════════════════════════════════════════
# Generation monotonicity
# ════════════════════════════════════════════════════════════════════════════


class TestGenerationMonotonicity:
    def test_a_fresh_cycle_starts_at_the_never_claimed_sentinel(self, merchant):
        row = _new_cycle(merchant, "gen-zero")
        assert row.lease_generation == 0
        assert row.lease_owner is None, "a cycle is created unowned"

    def test_every_claim_increments_the_generation(self, merchant):
        from backend.app.services.workflow_run_service import WorkflowRunService

        row = _new_cycle(merchant, "gen-mono")
        seen = []
        for i in range(3):
            s = session()
            try:
                wf = WorkflowRunService(s)
                live = s.get(AgentWorkflowRun, row.id)
                # Expire the previous owner's lease so the next claim wins.
                s.execute(
                    text("UPDATE agent_workflow_runs SET lease_expires_at = "
                         "now() - interval '1 hour' WHERE id = :i"),
                    {"i": row.id},
                )
                s.commit()
                s.expire_all()
                live = s.get(AgentWorkflowRun, row.id)
                seen.append(wf.claim(live, owner=f"w{i}"))
                s.commit()
            finally:
                s.close()
        assert seen == [1, 2, 3], "the fencing token must strictly increase"
        assert _load(row.id).lease_generation == 3

    def test_the_sentinel_zero_can_never_authorise_a_write(self, merchant):
        """A worker that never claimed holds generation 0 and must be refused.

        Generation 0 is also the stored value on a brand new cycle, so a naive
        equality check would let an unclaimed worker straight through. The guard
        is what stops that.
        """
        from backend.app.services.workflow_run_service import StaleLeaseError

        row = _new_cycle(merchant, "gen-sentinel")
        assert row.lease_generation == 0
        s = session()
        try:
            with pytest.raises(StaleLeaseError) as exc:
                probe = WorkflowRunServiceRecord(s, row.id, merchant.id)
                probe.start(expected_generation=0)
            assert "sentinel" in str(exc.value)
            s.rollback()
        finally:
            s.close()


class WorkflowRunServiceRecord:
    """Tiny helper that calls the fenced record method with one argument set."""

    def __init__(self, sess, workflow_id, merchant_id=None):
        self.sess = sess
        self.workflow_id = workflow_id
        self.merchant_id = merchant_id
        self.wf = None

    def start(self, expected_generation):
        from backend.app.agents.orchestrator import FAST_PLAN
        from backend.app.services.workflow_run_service import WorkflowRunService

        self.wf = WorkflowRunService(self.sess)
        agent = FAST_PLAN[0][0]
        return self.wf.record_step_start(
            self.sess,
            merchant_id=self.merchant_id or uuid.uuid4(),
            agent_name=agent,
            orchestrator_run_id="sentinel-probe",
            mode="fast",
            input_summary={},
            workflow_id=self.workflow_id,
            step_key=f"fast:000:{agent}:-:sentinel",
            step_index=0,
            attempt=1,
            commit=False,
            expected_generation=expected_generation,
        )


# ════════════════════════════════════════════════════════════════════════════
# THE fencing scenario
# ════════════════════════════════════════════════════════════════════════════


class TestFencingRejectsTheSupersededWorker:
    def _step_args(self, merchant, row, attempt=1):
        from backend.app.agents.orchestrator import FAST_PLAN

        agent = FAST_PLAN[0][0]
        return dict(
            merchant_id=merchant.id, agent_name=agent,
            orchestrator_run_id=row.run_id, mode="fast", input_summary={},
            workflow_id=row.id, step_key=f"fast:000:{agent}:-:{row.id}",
            step_index=0, attempt=attempt,
        )

    def test_a_superseded_worker_cannot_start_a_step(self, merchant):
        """Worker A's generation is stale; its step start must be refused."""
        from backend.app.services.workflow_run_service import (
            StaleLeaseError,
            WorkflowRunService,
        )

        row = _new_cycle(merchant, "fence-start")
        a = session()
        try:
            gen_a = WorkflowRunService(a).claim(
                a.get(AgentWorkflowRun, row.id), owner="worker-a")
            a.commit()
        finally:
            a.close()

        b = session()
        try:
            b.execute(text(
                "UPDATE agent_workflow_runs SET lease_expires_at = "
                "now() - interval '1 hour' WHERE id = :i"), {"i": row.id})
            b.commit()
            gen_b = WorkflowRunService(b).claim(
                b.get(AgentWorkflowRun, row.id), owner="worker-b")
            b.commit()
        finally:
            b.close()
        assert gen_b > gen_a

        # Worker A wakes up and tries to start its step.
        a = session()
        try:
            with pytest.raises(StaleLeaseError) as exc:
                WorkflowRunService(a).record_step_start(
                    a, commit=False, expected_generation=gen_a,
                    **self._step_args(merchant, row))
            assert "obsolete" in str(exc.value) or "generation" in str(exc.value)
        finally:
            a.close()

    def test_a_superseded_worker_cannot_mark_its_step_complete(self, merchant):
        """The exact harm fencing exists to prevent.

        Worker B has taken over and re-started the step. If A could still record
        its own outcome, it would mark a step complete that B is currently
        re-running, and the cycle would report success for work nobody finished.
        """
        from backend.app.services.workflow_run_service import (
            StaleLeaseError,
            WorkflowRunService,
        )

        row = _new_cycle(merchant, "fence-result")
        a = session()
        try:
            gen_a = WorkflowRunService(a).claim(
                a.get(AgentWorkflowRun, row.id), owner="worker-a")
            a.commit()
            pk = WorkflowRunService(a).record_step_start(
                a, expected_generation=gen_a,
                **self._step_args(merchant, row))
        finally:
            a.close()

        b = session()
        try:
            b.execute(text(
                "UPDATE agent_workflow_runs SET lease_expires_at = "
                "now() - interval '1 hour' WHERE id = :i"), {"i": row.id})
            b.commit()
            WorkflowRunService(b).claim(
                b.get(AgentWorkflowRun, row.id), owner="worker-b")
            b.commit()
        finally:
            b.close()

        # A wakes up believing its step succeeded.
        a = session()
        try:
            from backend.app.agents.base import AgentResult

            with pytest.raises(StaleLeaseError):
                WorkflowRunService(a).record_step_result(
                    a, pk, AgentResult(agent_name="x", status="completed"),
                    expected_generation=gen_a, workflow_id=row.id,
                )
            a.rollback()
        finally:
            a.close()

        chk = session()
        try:
            step = chk.get(AgentRun, pk)
            assert step.status == AgentRunStatus.running.value, (
                "the superseded worker must not have completed its step"
            )
        finally:
            chk.close()

    def test_a_superseded_worker_cannot_finalise_the_cycle(self, merchant):
        from backend.app.services.workflow_run_service import (
            StaleLeaseError,
            WorkflowRunService,
        )

        row = _new_cycle(merchant, "fence-finish")
        a = session()
        try:
            gen_a = WorkflowRunService(a).claim(
                a.get(AgentWorkflowRun, row.id), owner="worker-a")
            a.commit()
        finally:
            a.close()

        b = session()
        try:
            b.execute(text(
                "UPDATE agent_workflow_runs SET lease_expires_at = "
                "now() - interval '1 hour' WHERE id = :i"), {"i": row.id})
            b.commit()
            current = b.get(AgentWorkflowRun, row.id)
            gen_b = WorkflowRunService(b).claim(current, owner="worker-b")
            WorkflowRunService(b).finish_workflow(
                current, status="completed", expected_generation=gen_b)
            b.commit()
        finally:
            b.close()

        a = session()
        try:
            with pytest.raises(StaleLeaseError):
                WorkflowRunService(a).finish_workflow(
                    a.get(AgentWorkflowRun, row.id), status="failed",
                    expected_generation=gen_a)
            a.rollback()
        finally:
            a.close()

        assert _load(row.id).status == "completed", (
            "the newer owner's terminal status must survive"
        )

    def test_a_superseded_worker_cannot_extend_the_new_owners_lease(self, merchant):
        """Otherwise a zombie worker could hold a recovered cycle locked forever."""
        from backend.app.services.workflow_run_service import (
            StaleLeaseError,
            WorkflowRunService,
        )

        row = _new_cycle(merchant, "fence-heartbeat")
        a = session()
        try:
            gen_a = WorkflowRunService(a).claim(
                a.get(AgentWorkflowRun, row.id), owner="worker-a")
            a.commit()
        finally:
            a.close()
        b = session()
        try:
            b.execute(text(
                "UPDATE agent_workflow_runs SET lease_expires_at = "
                "now() - interval '1 hour' WHERE id = :i"), {"i": row.id})
            b.commit()
            WorkflowRunService(b).claim(
                b.get(AgentWorkflowRun, row.id), owner="worker-b")
            b.commit()
        finally:
            b.close()

        a = session()
        try:
            with pytest.raises(StaleLeaseError):
                WorkflowRunService(a).heartbeat(
                    a.get(AgentWorkflowRun, row.id), expected_generation=gen_a)
            a.rollback()
        finally:
            a.close()
        assert _load(row.id).lease_owner == "worker-b"

    def test_a_superseded_worker_cannot_clear_the_new_owners_lease(self, merchant):
        from backend.app.services.workflow_run_service import WorkflowRunService

        row = _new_cycle(merchant, "fence-release")
        a = session()
        try:
            gen_a = WorkflowRunService(a).claim(
                a.get(AgentWorkflowRun, row.id), owner="worker-a")
            a.commit()
        finally:
            a.close()
        b = session()
        try:
            b.execute(text(
                "UPDATE agent_workflow_runs SET lease_expires_at = "
                "now() - interval '1 hour' WHERE id = :i"), {"i": row.id})
            b.commit()
            WorkflowRunService(b).claim(
                b.get(AgentWorkflowRun, row.id), owner="worker-b")
            b.commit()
        finally:
            b.close()

        a = session()
        try:
            WorkflowRunService(a).release(
                a.get(AgentWorkflowRun, row.id), expected_generation=gen_a)
            a.commit()
        finally:
            a.close()
        current = _load(row.id)
        assert current.lease_owner == "worker-b", (
            "a superseded worker must not release the current owner's lease"
        )

    def test_the_current_owner_is_unaffected_by_fencing(self, merchant):
        """Fencing must not break the legitimate path."""
        from backend.app.services.workflow_run_service import WorkflowRunService

        row = _new_cycle(merchant, "fence-current")
        s = session()
        try:
            gen = WorkflowRunService(s).claim(
                s.get(AgentWorkflowRun, row.id), owner="worker-a")
            s.commit()
            from backend.app.agents.base import AgentResult

            pk = WorkflowRunService(s).record_step_start(
                s, expected_generation=gen,
                merchant_id=merchant.id, agent_name="GrowthDiscoveryAgent",
                orchestrator_run_id=row.run_id, mode="fast", input_summary={},
                workflow_id=row.id,
                step_key=f"fast:000:GrowthDiscoveryAgent:-:{row.id}",
                step_index=0, attempt=1)
            WorkflowRunService(s).record_step_result(
                s, pk, AgentResult(agent_name="GrowthDiscoveryAgent",
                                   status="completed"),
                expected_generation=gen, workflow_id=row.id)
            WorkflowRunService(s).heartbeat(
                s.get(AgentWorkflowRun, row.id), expected_generation=gen)
            s.commit()
        finally:
            s.close()
        step = session()
        try:
            assert step.get(AgentRun, pk).status == AgentRunStatus.completed.value
        finally:
            step.close()


# ════════════════════════════════════════════════════════════════════════════
# Concurrent claims
# ════════════════════════════════════════════════════════════════════════════


class TestConcurrentClaims:
    def test_concurrent_claims_produce_exactly_one_winner(self, merchant):
        from backend.app.services.workflow_run_service import (
            WorkflowOwnershipError,
            WorkflowRunService,
        )

        row = _new_cycle(merchant, "race-claim")
        # Expire the (never-taken) lease so both racers find it claimable.
        s = session()
        try:
            s.execute(text(
                "UPDATE agent_workflow_runs SET lease_expires_at = NULL "
                "WHERE id = :i"), {"i": row.id})
            s.commit()
        finally:
            s.close()

        def try_claim(i):
            sess = session()
            try:
                g = WorkflowRunService(sess).claim(
                    sess.get(AgentWorkflowRun, row.id), owner=f"racer-{i}")
                sess.commit()
                return ("won", g)
            except WorkflowOwnershipError:
                sess.rollback()
                return ("refused", None)
            finally:
                sess.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(try_claim, range(2)))
        assert [o[0] for o in outcomes].count("won") == 1, outcomes
        assert [o[0] for o in outcomes].count("refused") == 1, outcomes
        assert _load(row.id).lease_generation == 1


# ════════════════════════════════════════════════════════════════════════════
# Sweep races
# ════════════════════════════════════════════════════════════════════════════


class TestSweepRaces:
    def test_concurrent_sweeps_reclaim_each_cycle_exactly_once(self, merchant):
        from backend.app.services.workflow_run_service import sweep_stale_workflows

        ids = [_new_cycle(merchant, f"sweep-race-{i}").id for i in range(4)]
        mine = {str(i) for i in ids}
        for i in ids:
            _expire_lease(i)

        def sweep(_i):
            s = session()
            try:
                return set(sweep_stale_workflows(s).reclaimed)
            finally:
                s.close()

        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(sweep, range(3)))

        # Exactly once across concurrent sweepers, for the cycles created here.
        # Other tests' cycles are legitimately swept too, so the assertion is
        # scoped to `mine` rather than to a global count.
        appearances = [x for r in results for x in r if x in mine]
        assert len(appearances) == len(set(appearances)) == len(ids), (
            f"a cycle was reclaimed more than once across sweepers: {results}"
        )
        assert set(appearances) == mine, (
            f"some cycles were never reclaimed: {mine - set(appearances)}"
        )

    def test_a_live_owner_is_never_reclaimed_by_a_concurrent_sweep(self, merchant):
        from backend.app.services.workflow_run_service import (
            WorkflowRunService,
            sweep_stale_workflows,
        )

        row = _new_cycle(merchant, "sweep-vs-live")
        s = session()
        try:
            WorkflowRunService(s).claim(
                s.get(AgentWorkflowRun, row.id), owner="healthy-worker")
            s.commit()
        finally:
            s.close()

        other = session()
        try:
            sweep_stale_workflows(other)
        finally:
            other.close()
        assert _load(row.id).status == "running"
        assert _load(row.id).lease_owner == "healthy-worker"

    def test_a_cycle_finishing_during_a_sweep_is_not_reclaimed(self, merchant):
        """The race the status guard exists for."""
        from backend.app.services.workflow_run_service import (
            WorkflowRunService,
            sweep_stale_workflows,
        )

        row = _new_cycle(merchant, "sweep-vs-finish")
        _expire_lease(row.id)

        # Simulate the owner finalising first: the CAS predicate requires
        # status='running', so a completed cycle is invisible to the sweep.
        s = session()
        try:
            live = s.get(AgentWorkflowRun, row.id)
            live.status = "completed"
            live.completed_at = None
            s.commit()
        finally:
            s.close()

        other = session()
        try:
            report = sweep_stale_workflows(other)
        finally:
            other.close()
        assert str(row.id) not in report.reclaimed
        assert _load(row.id).status == "completed"

    def test_the_sweep_fences_a_worker_that_survives_its_own_sweep(self, merchant):
        """Sweep -> owner wakes -> its write must be refused."""
        from backend.app.services.workflow_run_service import (
            StaleLeaseError,
            WorkflowRunService,
            sweep_stale_workflows,
        )

        row = _new_cycle(merchant, "sweep-then-wake")
        s = session()
        try:
            gen = WorkflowRunService(s).claim(
                s.get(AgentWorkflowRun, row.id), owner="zombie")
            s.commit()
        finally:
            s.close()
        _expire_lease(row.id)

        other = session()
        try:
            report = sweep_stale_workflows(other)
        finally:
            other.close()
        assert str(row.id) in report.reclaimed

        zombie = session()
        try:
            with pytest.raises(StaleLeaseError):
                WorkflowRunService(zombie).record_step_start(
                    zombie, commit=False, expected_generation=gen,
                    merchant_id=merchant.id, agent_name="GrowthDiscoveryAgent",
                    orchestrator_run_id=row.run_id, mode="fast", input_summary={},
                    workflow_id=row.id,
                    step_key=f"fast:000:GrowthDiscoveryAgent:-:{row.id}",
                    step_index=0, attempt=1)
            zombie.rollback()
        finally:
            zombie.close()


# ════════════════════════════════════════════════════════════════════════════
# Uncertain external outcome and idempotency under the new policy
# ════════════════════════════════════════════════════════════════════════════


class TestUncertainOutcomePolicy:
    def test_an_executing_action_forces_reconciliation_over_a_healthy_looking_result(
        self, merchant
    ):
        from backend.app.agents.orchestrator import FAST_PLAN
        from backend.app.services.agent_run_service import AgentRunService
        from backend.app.services.workflow_run_service import (
            ReuseVerdict,
            WorkflowRunService,
        )

        row = _new_cycle(merchant, "uncertain-partial")
        s = session()
        try:
            wf = WorkflowRunService(s)
            step = wf.attempt_rows(row.id) or {}
            agent = FAST_PLAN[0][0]
            r = AgentRunService(s).start_run(
                merchant_id=merchant.id, agent_name=agent,
                orchestrator_run_id=row.run_id, workflow_id=row.id,
                step_key=f"fast:000:{agent}:-:{row.id}", step_index=0, attempt=1)
            r.status = AgentRunStatus.partially_completed.value
            r.output_summary = {"findings": ["intact"]}
            s.add(AgentAction(
                merchant_id=merchant.id, action_type="retry_payment",
                status=AgentActionStatus.executing,
                input_payload={"payment_id": "p"},
                idempotency_key=uuid.uuid4().hex * 2, workflow_run_id=row.id))
            s.commit()
            s.expire_all()

            r = s.query(AgentRun).filter(AgentRun.workflow_id == row.id).one()
            assert wf.decide(
                step_row=r, merchant_id=merchant.id).verdict is ReuseVerdict.RECONCILE
            assert step == {}
        finally:
            s.close()

    def test_reconciliation_never_re_enqueues_a_duplicate_action(self, merchant):
        """Idempotency still holds even while a step is held for reconciliation."""
        from backend.app.services.action_service import (
            action_idempotency_key,
            create_action,
        )

        payload = {"payment_id": "dupe-check"}
        key = action_idempotency_key(
            merchant_id=merchant.id, action_type="retry_payment",
            input_payload=payload)
        s = session()
        try:
            first = create_action(s, merchant_id=merchant.id,
                                  action_type="retry_payment",
                                  input_payload=payload, idempotency_key=key)
            s.commit()
            second = create_action(s, merchant_id=merchant.id,
                                   action_type="retry_payment",
                                   input_payload=payload, idempotency_key=key)
            s.commit()
            assert first.id == second.id
            assert s.query(AgentAction).filter(
                AgentAction.merchant_id == merchant.id,
                AgentAction.idempotency_key == key).count() == 1
        finally:
            s.close()

    def test_concurrent_duplicate_proposals_still_yield_one_row(self, merchant):
        from backend.app.services.action_service import (
            action_idempotency_key,
            create_action,
        )

        payload = {"payment_id": f"race-{uuid.uuid4().hex[:8]}"}
        key = action_idempotency_key(
            merchant_id=merchant.id, action_type="retry_payment",
            input_payload=payload)

        def propose(_i):
            s = session()
            try:
                a = create_action(s, merchant_id=merchant.id,
                                  action_type="retry_payment",
                                  input_payload=payload, idempotency_key=key)
                s.commit()
                return str(a.id)
            except IntegrityError:
                s.rollback()
                return "rejected"
            finally:
                s.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(propose, range(2)))
        assert "rejected" not in ids, ids
        assert len(set(ids)) == 1, ids


# ════════════════════════════════════════════════════════════════════════════
# Tenant isolation
# ════════════════════════════════════════════════════════════════════════════


class TestTenantIsolation:
    def test_a_sweep_does_not_leak_across_tenants(self, merchant):
        """The sweep is system-wide, but every effect stays inside its cycle."""
        from backend.app.services.workflow_run_service import (
            WorkflowRunService,
            sweep_stale_workflows,
        )

        mine = _new_cycle(merchant, "tenant-mine")
        s = session()
        try:
            m2 = Merchant(name="Other", slug=f"pgother-{uuid.uuid4().hex[:10]}",
                          email=f"{uuid.uuid4().hex[:8]}@pg.test",
                          status=MerchantStatus.active, currency=Currency.INR)
            s.add(m2); s.commit(); s.expire_all()
            m2 = s.get(Merchant, m2.id)
            theirs = WorkflowRunService(s)
            trow, _ = theirs.start_workflow(
                merchant_id=m2.id, run_id="tenant-theirs", mode="fast",
                plan=__import__(
                    "backend.app.agents.orchestrator", fromlist=["FAST_PLAN"]
                ).FAST_PLAN)
            s.commit()
            # Give the other tenant a LIVE lease: it must survive the sweep.
            theirs.claim(s.get(AgentWorkflowRun, trow.id), owner="other-worker")
            s.commit()
            theirs_id = trow.id
        finally:
            s.close()

        _expire_lease(mine.id)
        other = session()
        try:
            sweep_stale_workflows(other)
        finally:
            other.close()

        assert _load(mine.id).status == "interrupted"
        assert _load(theirs_id).status == "running", (
            "another tenant's live cycle must not be touched"
        )

    def test_a_superseded_generation_cannot_be_replayed_across_tenants(self, merchant):
        """Generation is per cycle, so one tenant's token cannot open another's."""
        from backend.app.services.workflow_run_service import (
            StaleLeaseError,
            WorkflowRunService,
        )

        mine = _new_cycle(merchant, "gen-scope-mine")
        s = session()
        try:
            m2 = Merchant(name="Scope", slug=f"pgscope-{uuid.uuid4().hex[:10]}",
                          email=f"{uuid.uuid4().hex[:8]}@pg.test",
                          status=MerchantStatus.active, currency=Currency.INR)
            s.add(m2); s.commit(); s.expire_all()
            m2 = s.get(Merchant, m2.id)
            theirs, _ = WorkflowRunService(s).start_workflow(
                merchant_id=m2.id, run_id="scope-theirs", mode="fast",
                plan=__import__(
                    "backend.app.agents.orchestrator", fromlist=["FAST_PLAN"]
                ).FAST_PLAN)
            s.commit()
            s.expire_all()
            gen_theirs = WorkflowRunService(s).claim(
                s.get(AgentWorkflowRun, theirs.id), owner="other")
            s.commit()
            with pytest.raises(StaleLeaseError):
                WorkflowRunService(s).record_step_start(
                    s, commit=False, expected_generation=gen_theirs,
                    merchant_id=merchant.id, agent_name="GrowthDiscoveryAgent",
                    orchestrator_run_id=mine.run_id, mode="fast", input_summary={},
                    workflow_id=mine.id, step_key="fast:000:x:-:scope",
                    step_index=0, attempt=1)
            s.rollback()
        finally:
            s.close()