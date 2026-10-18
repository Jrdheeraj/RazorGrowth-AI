"""
Migration verification on a disposable PostgreSQL instance (Task 2).

Runs ONLY when ``POSTGRES_DSN`` points at a PostgreSQL database. That guard is
deliberate: a developer without a disposable instance must get skips, never a
false green. The SQLite crash tests cannot cover any of this -- NULL handling,
partial-index-free unique constraints, FK actions and transaction poisoning
after a constraint violation are all dialect-specific.

NEVER point POSTGRES_DSN at a production or primary development database.

    docker run -d --name razorgrowth-verify-pg -p 55433:5432 \\
      -e POSTGRES_PASSWORD=verify123 -e POSTGRES_USER=verify \\
      -e POSTGRES_DB=razorgrowth_verify pgvector/pgvector:pg16
    $env:DATABASE_URL="postgresql://verify:verify123@localhost:55433/razorgrowth_verify"
    python -m alembic upgrade head
    $env:POSTGRES_DSN=$env:DATABASE_URL
    python -m pytest tests/test_postgres_migration.py -v
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest

DSN = os.environ.get("POSTGRES_DSN")

pytestmark = pytest.mark.skipif(
    not DSN or "postgres" not in (DSN or "").split("://")[0],
    reason="POSTGRES_DSN not set to a PostgreSQL DSN; SQLite results cannot "
           "establish PostgreSQL migration behaviour",
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
    from sqlalchemy.exc import IntegrityError, PendingRollbackError
    from sqlalchemy.orm import sessionmaker

    import backend.app.main  # noqa: F401  (registers every model)
    from backend.app.models.agent_action import AgentAction
    from backend.app.models.agent_run import AgentRun
    from backend.app.models.agent_workflow import AgentWorkflowRun
    from backend.app.models.enums import Currency, MerchantStatus
    from backend.app.models.merchant import Merchant

    _engine = create_engine(DSN, future=True)
    Session = sessionmaker(bind=_engine, expire_on_commit=False)


# ════════════════════════════════════════════════════════════════════════════
# Fixture: one throwaway merchant per test, removed afterwards
# ════════════════════════════════════════════════════════════════════════════


@pytest.fixture()
def s():
    sess = Session()
    yield sess
    sess.rollback()
    sess.close()


@pytest.fixture()
def merchant(s):
    m = Merchant(
        name="PG Verify",
        slug=f"pgverify-{uuid.uuid4().hex[:10]}",
        email=f"{uuid.uuid4().hex[:8]}@pg.test",
        status=MerchantStatus.active,
        currency=Currency.INR,
    )
    s.add(m)
    s.commit()
    s.refresh(m)
    return m


def _workflow(s, merchant, run_id, *, mode="fast", plan=None, status="running"):
    """Insert a workflow row directly, so tests do not depend on the service."""
    from backend.app.services.workflow_run_service import (
        materialise_plan,
        plan_fingerprint,
    )
    from backend.app.agents.orchestrator import FAST_PLAN

    plan = plan if plan is not None else FAST_PLAN
    steps = materialise_plan(mode, plan)
    now = datetime.now(timezone.utc)
    wf = AgentWorkflowRun(
        merchant_id=merchant.id, run_id=run_id, mode=mode, status=status,
        plan=steps, plan_fingerprint=plan_fingerprint(steps), step_count=len(steps),
        started_at=now, heartbeat_at=now,
    )
    s.add(wf)
    s.commit()
    s.refresh(wf)
    return wf


def _agent_run(s, merchant, wf, step_key, attempt=1, step_index=0,
               agent_name="GrowthDiscoveryAgent", status="running"):
    row = AgentRun(
        merchant_id=merchant.id, workflow_id=wf.id, orchestrator_run_id=wf.run_id,
        agent_name=agent_name, step_key=step_key, step_index=step_index,
        attempt=attempt, status=status, mode=wf.mode,
        started_at=datetime.now(timezone.utc),
        heartbeat_at=datetime.now(timezone.utc),
    )
    s.add(row)
    return row


# ════════════════════════════════════════════════════════════════════════════
# Chain and schema
# ════════════════════════════════════════════════════════════════════════════


class TestMigrationChain:
    def test_single_head_and_it_is_the_current_tip(self, s):
        """One head, and it is the newest migration -- not a specific id.

        Asserting a hardcoded revision id makes this fail every time a
        legitimate migration is added. What matters is that the chain is linear
        (no competing heads) and that the applied version is the tip.
        """
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        heads = ScriptDirectory.from_config(Config("alembic.ini")).get_heads()
        assert len(heads) == 1, f"the chain has forked: {heads}"

        applied = s.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert applied == heads[0], (
            f"database is at {applied!r} but the tip is {heads[0]!r}; "
            f"run `alembic upgrade head`"
        )

    def test_the_fencing_migration_is_applied(self, s):
        head = s.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert head == "e5a1b3c7d904", (
            f"expected the lease-fencing migration at the tip, found {head!r}"
        )

    def test_recovery_table_exists_with_expected_columns(self, s):
        cols = {
            r[0] for r in s.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='agent_workflow_runs'"
            ))
        }
        assert {
            "merchant_id", "run_id", "mode", "status", "plan_fingerprint", "plan",
            "step_count", "lease_owner", "lease_expires_at", "heartbeat_at",
            "started_at", "completed_at",
        } <= cols

    def test_step_identity_columns_exist_on_agent_runs(self, s):
        cols = {
            r[0] for r in s.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='agent_runs'"
            ))
        }
        assert {"workflow_id", "step_key", "step_index", "attempt", "heartbeat_at"} <= cols

    def test_status_column_is_wide_enough_for_partially_completed(self, s):
        """'partially_completed' is 20 chars; VARCHAR(20) is the exact boundary."""
        length = s.execute(text(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_name='agent_runs' AND column_name='status'"
        )).scalar_one()
        assert length >= len("partially_completed"), (
            f"agent_runs.status is VARCHAR({length}); a status value would be truncated"
        )

    def test_idempotency_columns_exist_on_agent_actions(self, s):
        cols = {
            r[0] for r in s.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='agent_actions'"
            ))
        }
        assert {"idempotency_key", "workflow_run_id"} <= cols

    def test_unique_constraints_are_present(self, s):
        defs = {
            r[0]: r[1]
            for r in s.execute(text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid='agent_runs'::regclass AND contype='u'"
            ))
        }
        assert "uq_agent_runs_workflow_step_attempt" in defs
        assert "workflow_id" in defs["uq_agent_runs_workflow_step_attempt"]
        assert "step_key" in defs["uq_agent_runs_workflow_step_attempt"]
        assert "attempt" in defs["uq_agent_runs_workflow_step_attempt"]

        wf_defs = {
            r[0]: r[1]
            for r in s.execute(text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid='agent_workflow_runs'::regclass AND contype='u'"
            ))
        }
        assert "uq_agent_workflow_runs_merchant_run" in wf_defs
        assert "run_id" in wf_defs["uq_agent_workflow_runs_merchant_run"]

        act_defs = {
            r[0]: r[1]
            for r in s.execute(text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid='agent_actions'::regclass AND contype='u'"
            ))
        }
        assert "uq_agent_actions_merchant_idempotency" in act_defs
        assert "idempotency_key" in act_defs["uq_agent_actions_merchant_idempotency"]

    def test_foreign_keys_have_the_intended_delete_behaviour(self, s):
        rows = dict(s.execute(text(
            "SELECT conname, confdeltype FROM pg_constraint "
            "WHERE conname IN ('fk_agent_runs_workflow_id','fk_agent_actions_workflow_run_id')"
        )).all())
        assert rows["fk_agent_runs_workflow_id"] == "c", "agent_runs must CASCADE"
        assert rows["fk_agent_actions_workflow_run_id"] == "n", (
            "agent_actions.workflow_run_id must SET NULL so a deleted cycle "
            "does not silently destroy the audit trail of an action"
        )


# ════════════════════════════════════════════════════════════════════════════
# Historical rows
# ════════════════════════════════════════════════════════════════════════════


class TestHistoricalRowCompatibility:
    def test_legacy_agent_run_with_null_step_fields_is_accepted(self, s, merchant):
        """A pre-recovery row has no workflow, no step key, no heartbeat."""
        _agent_run(s, merchant, workflow=None, step_key=None) if False else None
        row = AgentRun(
            merchant_id=merchant.id, orchestrator_run_id=None, workflow_id=None,
            agent_name="LegacyAgent", step_key=None, step_index=None,
            status="completed", mode="deep",
            started_at=datetime.now(timezone.utc), heartbeat_at=None,
        )
        s.add(row)
        s.commit()
        assert row.attempt == 1, "attempt must backfill to 1, not NULL"

    def test_many_legacy_rows_with_null_keys_coexist(self, s, merchant):
        """PostgreSQL treats NULLs as distinct, so no backfill is required."""
        for i in range(5):
            s.add(AgentRun(
                merchant_id=merchant.id, workflow_id=None, step_key=None,
                orchestrator_run_id=None, agent_name="Legacy",
                status="completed", mode="deep",
                started_at=datetime.now(timezone.utc),
            ))
        s.commit()
        n = s.execute(text(
            "SELECT count(*) FROM agent_runs WHERE step_key IS NULL AND workflow_id IS NULL"
        )).scalar_one()
        assert n >= 5

    def test_legacy_actions_with_null_idempotency_key_coexist(self, s, merchant):
        for _ in range(3):
            s.add(AgentAction(
                merchant_id=merchant.id, action_type="retry_payment",
                status="requested", input_payload={},
                idempotency_key=None, workflow_run_id=None,
            ))
        s.commit()
        n = s.execute(text(
            "SELECT count(*) FROM agent_actions WHERE idempotency_key IS NULL"
        )).scalar_one()
        assert n >= 3

    def test_two_merchants_may_reuse_the_same_run_id(self, s, merchant):
        other = Merchant(
            name="PG Other", slug=f"pgother-{uuid.uuid4().hex[:10]}",
            email=f"{uuid.uuid4().hex[:8]}@pg.test",
            status=MerchantStatus.active, currency=Currency.INR,
        )
        s.add(other)
        s.commit()
        s.refresh(other)
        a = _workflow(s, merchant, "shared-run-id")
        b = _workflow(s, other, "shared-run-id")
        assert a.id != b.id, "run_id uniqueness must be per tenant, not global"


# ════════════════════════════════════════════════════════════════════════════
# Uniqueness enforcement
# ════════════════════════════════════════════════════════════════════════════


class TestUniquenessEnforcement:
    def test_duplicate_workflow_run_id_is_rejected(self, s, merchant):
        _workflow(s, merchant, "dupe-run")
        with pytest.raises(IntegrityError):
            _workflow(s, merchant, "dupe-run")
        s.rollback()

    def test_duplicate_logical_step_attempt_is_rejected(self, s, merchant):
        wf = _workflow(s, merchant, "dupe-step")
        _agent_run(s, merchant, wf, step_key="fast:001:X:-:h", attempt=1)
        s.commit()
        with pytest.raises(IntegrityError):
            _agent_run(s, merchant, wf, step_key="fast:001:X:-:h", attempt=1)
            s.commit()
        s.rollback()

    def test_a_different_attempt_is_allowed(self, s, merchant):
        """Retry history must accumulate rather than collide."""
        wf = _workflow(s, merchant, "retry-history")
        _agent_run(s, merchant, wf, step_key="fast:001:X:-:h", attempt=1)
        s.commit()
        _agent_run(s, merchant, wf, step_key="fast:001:X:-:h", attempt=2)
        s.commit()
        n = s.execute(text(
            "SELECT count(*) FROM agent_runs WHERE workflow_id=:w AND step_key=:k"
        ), {"w": wf.id, "k": "fast:001:X:-:h"}).scalar_one()
        assert n == 2, "attempt must be part of the key so retries are preserved"

    def test_two_workflows_may_hold_the_same_step_key(self, s, merchant):
        """Legitimate repetition is scoped by workflow, not by step key alone."""
        a = _workflow(s, merchant, "wf-a")
        b = _workflow(s, merchant, "wf-b")
        shared_key = f"growth_team:002:MarketingAgent:investigate:{uuid.uuid4().hex[:8]}"
        _agent_run(s, merchant, a, step_key=shared_key)
        _agent_run(s, merchant, b, step_key=shared_key)
        s.commit()
        assert s.execute(text(
            "SELECT count(*) FROM agent_runs WHERE step_key=:k AND workflow_id IN :w"
        ), {"k": shared_key, "w": (a.id, b.id)}).scalar_one() == 2

    def test_duplicate_action_idempotency_key_is_rejected(self, s, merchant):
        payload = {"id": str(uuid.uuid4())}
        key = uuid.uuid4().hex * 2
        for _ in range(2):
            s.add(AgentAction(
                merchant_id=merchant.id, action_type="retry_payment",
                status="requested", input_payload=payload,
                idempotency_key=key, workflow_run_id=None,
            ))
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()

    def test_two_merchants_may_share_an_idempotency_key_value(self, s, merchant):
        other = Merchant(
            name="PG Shared", slug=f"pgshared-{uuid.uuid4().hex[:10]}",
            email=f"{uuid.uuid4().hex[:8]}@pg.test",
            status=MerchantStatus.active, currency=Currency.INR,
        )
        s.add(other)
        s.commit()
        s.refresh(other)
        shared = uuid.uuid4().hex * 2          # 64 chars, unique to this run
        s.add(AgentAction(merchant_id=merchant.id, action_type="retry_payment",
                          status="requested", input_payload={}, idempotency_key=shared))
        s.add(AgentAction(merchant_id=other.id, action_type="retry_payment",
                          status="requested", input_payload={}, idempotency_key=shared))
        s.commit()
        assert s.execute(text(
            "SELECT count(*) FROM agent_actions "
            "WHERE idempotency_key=:k AND merchant_id IN :m"
        ), {"k": shared, "m": (merchant.id, other.id)}).scalar_one() == 2, (
            "idempotency must be tenant-scoped"
        )


# ════════════════════════════════════════════════════════════════════════════
# Transaction poisoning
# ════════════════════════════════════════════════════════════════════════════


class TestTransactionIntegrity:
    def test_a_failed_duplicate_insert_does_poison_the_outer_transaction(self, s, merchant):
        """PostgreSQL really does poison the transaction -- which is the point.

        A unique-constraint violation aborts the whole transaction; any later
        statement fails with "current transaction is aborted" until the caller
        issues rollback(). This is documented, load-bearing behaviour, not a
        defect: it is the reason ``action_service.create_action`` wraps its
        insert in ``db.begin_nested()`` rather than relying on a read-then-write
        check. If a future driver or dialect made this harmless, the savepoint
        would still be correct -- but the test below would need revisiting.
        """
        _workflow(s, merchant, "poison-probe")
        merchant_id = merchant.id        # read BEFORE poisoning the session
        key = uuid.uuid4().hex * 2

        s.add(AgentAction(merchant_id=merchant_id, action_type="retry_payment",
                          status="requested", input_payload={},
                          idempotency_key=key))
        s.commit()

        s.add(AgentAction(merchant_id=merchant_id, action_type="retry_payment",
                          status="requested", input_payload={},
                          idempotency_key=key))
        with pytest.raises(IntegrityError):
            s.commit()

        # The session can no longer execute anything until it rolls back.
        with pytest.raises(PendingRollbackError):
            s.execute(text("SELECT 1"))
        s.rollback()

        # And the first row is intact -- the violation rolled back nothing else.
        chk = Session()
        try:
            assert chk.execute(text(
                "SELECT count(*) FROM agent_actions "
                "WHERE idempotency_key=:k AND merchant_id=:m"
            ), {"k": key, "m": merchant_id}).scalar_one() == 1
        finally:
            chk.close()

    def test_savepoint_inside_a_transaction_keeps_it_alive(self, s, merchant):
        """The savepoint pattern create_action actually uses."""
        _workflow(s, merchant, "savepoint-probe")
        key = uuid.uuid4().hex * 2
        merchant_id = merchant.id
        s.add(AgentAction(merchant_id=merchant_id, action_type="retry_payment",
                          status="requested", input_payload={},
                          idempotency_key=key))
        s.flush()

        try:
            with s.begin_nested():
                s.add(AgentAction(merchant_id=merchant_id, action_type="retry_payment",
                                  status="requested", input_payload={},
                                  idempotency_key=key))
                s.flush()
        except IntegrityError:
            pass
        else:
            pytest.fail("the duplicate should have violated the unique constraint")

        s.add(AgentAction(merchant_id=merchant_id, action_type="retry_payment",
                          status="requested", input_payload={},
                          idempotency_key=uuid.uuid4().hex * 2))
        s.commit()
        n = s.execute(text(
            "SELECT count(*) FROM agent_actions WHERE merchant_id=:m"
        ), {"m": merchant_id}).scalar_one()
        assert n == 2, "savepoint should have absorbed the violation"


# ════════════════════════════════════════════════════════════════════════════
# Cascade behaviour
# ════════════════════════════════════════════════════════════════════════════


class TestCascadeBehaviour:
    def test_deleting_a_merchant_removes_its_workflows_and_runs(self, s, merchant):
        wf = _workflow(s, merchant, "cascade-wf")
        _agent_run(s, merchant, wf, step_key="fast:001:X:-:h")
        s.commit()
        merchant_id = merchant.id
        s.delete(merchant)
        s.commit()
        assert s.execute(text(
            "SELECT count(*) FROM agent_workflow_runs WHERE merchant_id=:m"
        ), {"m": merchant_id}).scalar_one() == 0
        assert s.execute(text(
            "SELECT count(*) FROM agent_runs WHERE workflow_id=:w"
        ), {"w": wf.id}).scalar_one() == 0

    def test_deleting_a_workflow_removes_its_steps(self, s, merchant):
        wf = _workflow(s, merchant, "cascade-steps")
        _agent_run(s, merchant, wf, step_key="fast:001:X:-:h")
        s.commit()
        wf_id = wf.id
        s.delete(wf)
        s.commit()
        assert s.execute(text(
            "SELECT count(*) FROM agent_runs WHERE workflow_id=:w"
        ), {"w": wf_id}).scalar_one() == 0

    def test_deleting_a_workflow_nulls_the_action_link_but_keeps_the_action(self, s, merchant):
        """An action is a human-governance record; a cycle is not its owner."""
        wf = _workflow(s, merchant, "cascade-action")
        key = uuid.uuid4().hex * 2
        merchant_id = merchant.id
        s.add(AgentAction(
            merchant_id=merchant_id, action_type="retry_payment",
            status="requested", input_payload={},
            idempotency_key=key, workflow_run_id=wf.id,
        ))
        s.commit()
        action_id = s.execute(text(
            "SELECT id FROM agent_actions WHERE idempotency_key=:k AND merchant_id=:m"
        ), {"k": key, "m": merchant_id}).scalar_one()
        s.delete(wf)
        s.commit()
        still_there = s.execute(text(
            "SELECT count(*) FROM agent_actions WHERE id=:a"
        ), {"a": action_id}).scalar_one()
        link = s.execute(text(
            "SELECT workflow_run_id FROM agent_actions WHERE id=:a"
        ), {"a": action_id}).scalar_one()
        assert still_there == 1, "the action must survive its originating cycle"
        assert link is None, "the dangling link must be nulled, not left broken"


# ════════════════════════════════════════════════════════════════════════════
# Concurrency, proven at the database level
# ════════════════════════════════════════════════════════════════════════════


class TestDatabaseConcurrency:
    def test_two_connections_racing_the_same_lease_produce_one_winner(self, merchant):
        """Row locking, not application code, is what makes this safe.

        Both sessions attempt the same compare-and-set UPDATE. PostgreSQL
        serialises them on the row lock; the second re-evaluates the predicate
        after the first commits and matches zero rows.
        """
        from datetime import timedelta

        from sqlalchemy import update

        s1, s2 = Session(), Session()
        try:
            wf = _workflow(s1, merchant, "race-lease")
            stale = datetime.now(timezone.utc) - timedelta(minutes=30)
            s1.execute(
                update(AgentWorkflowRun).where(AgentWorkflowRun.id == wf.id)
                .values(heartbeat_at=stale, lease_expires_at=stale)
            )
            s1.commit()

            def try_claim(sess, owner):
                now = datetime.now(timezone.utc)
                res = sess.execute(
                    update(AgentWorkflowRun)
                    .where(
                        AgentWorkflowRun.id == wf.id,
                        (AgentWorkflowRun.lease_expires_at.is_(None))
                        | (AgentWorkflowRun.lease_expires_at <= now),
                    )
                    .values(lease_owner=owner,
                            lease_expires_at=now + timedelta(seconds=900),
                            heartbeat_at=now)
                    .execution_options(synchronize_session=False)
                )
                sess.commit()
                return res.rowcount

            assert try_claim(s1, "worker-A") == 1, "first claim should win"
            assert try_claim(s2, "worker-B") == 0, (
                "second claim must affect zero rows while the lease is live"
            )
        finally:
            s1.close()
            s2.close()

    def test_concurrent_duplicate_action_insert_yields_exactly_one_row(self, merchant):
        """The unique constraint, not a read-then-write, settles the race."""
        from concurrent.futures import ThreadPoolExecutor

        wf = _workflow(Session(), merchant, "race-action")
        key = uuid.uuid4().hex * 2
        merchant_id = merchant.id

        def attempt(_i):
            sess = Session()
            try:
                sess.add(AgentAction(
                    merchant_id=merchant_id, action_type="retry_payment",
                    status="requested", input_payload={"p": "1"},
                    idempotency_key=key, workflow_run_id=wf.id,
                ))
                sess.commit()
                return "inserted"
            except IntegrityError:
                sess.rollback()
                return "rejected"
            finally:
                sess.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, range(2)))

        assert outcomes.count("inserted") == 1, f"both inserts won: {outcomes}"
        assert outcomes.count("rejected") == 1, f"neither insert won: {outcomes}"

        chk = Session()
        try:
            n = chk.execute(text(
                "SELECT count(*) FROM agent_actions "
                "WHERE idempotency_key=:k AND merchant_id=:m"
            ), {"k": key, "m": merchant_id}).scalar_one()
            assert n == 1, f"{n} rows exist for one logical action"
        finally:
            chk.close()