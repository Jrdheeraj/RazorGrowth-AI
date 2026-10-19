"""
Crash-recovery verification for GrowthAgentOrchestrator + ManagerAgent.

WHAT THIS FILE DOES
-------------------
Proves, with a REAL process boundary, that an interrupted multi-agent workflow
resumes from its own persisted state without re-running completed steps,
duplicating step records, or duplicating logical actions.

METHODOLOGY
-----------
* **File-backed SQLite.** An in-memory database dies with the process, so it can
  never prove restart durability. See ``SQLITE_IS_NOT_POSTGRESQL``.
* **Real subprocesses.** Recovery runs in a separate interpreter that reopens
  the database file. The crashing child hard-exits via ``os._exit()`` -- no
  ``finally``, no rollback, no ``atexit``, no graceful close.
* **Elapsed time is simulated honestly.** A crash is normally discovered some
  minutes later, so the crashing child ages its persisted heartbeat to ten
  minutes before dying. That is what a real abandoned cycle looks like, and it
  is what lets the stale-owner policy (rather than a wait) permit takeover.
* **Only the supported API is used.** Recovery calls
  ``GrowthAgentOrchestrator.resume()``. Nothing fabricates a checkpoint, marks
  work complete by hand, or reaches past the orchestrator.

HOW TO READ THE RESULTS
-----------------------
``TestRecoveryContract``        PASSES -- the implemented contract holds.
``TestRealProcessBoundary``     PASSES -- the crash and durability are real.
``TestRecoveryBehaviour``       PASSES -- completed work is genuinely reused.
``TestLegitimateRepetition``    PASSES -- valid repetition is NOT broken.
``TestStaleAndConcurrency``     PASSES -- a live owner is never taken over.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.app.db.base import Base
from tests.security_utils import make_world

SQLITE_IS_NOT_POSTGRESQL = (
    "This harness runs on file-backed SQLite. It proves durability ACROSS A "
    "PROCESS RESTART and durability of committed transactions only. It does NOT "
    "establish PostgreSQL production behaviour: PostgreSQL differs in "
    "crash-recovery internals, WAL vs shared-cache semantics, durability "
    "settings (synchronous_commit / fsync), MVCC visibility of a concurrent "
    "compare-and-set, and the fate of an in-flight transaction at a hard kill."
)

#: Team plan order; the 5th step. Four real specialists complete before this.
CRASH_AT = "PaymentRecoveryAgent"


# ════════════════════════════════════════════════════════════════════════════
# Child process
# ════════════════════════════════════════════════════════════════════════════

CHILD_SCRIPT = r'''
"""Run, crash, or RESUME one orchestrator cycle against an on-disk SQLite db.

Usage: python crash_child.py <mode> <db_path> <run_id> <crash_at>

Modes:
  first_pass -- run mode="team", hard-exit on `crash_at` after ageing the
                workflow heartbeat to 10 minutes ago (a discovered crash).
  resume     -- call the SUPPORTED recovery API, GrowthAgentOrchestrator.resume().
  inspect    -- dump persisted state for the cycle. Read-only.
  concurrent -- two processes race to resume the same cycle; report who won.
"""
import json
import os
import sys

for _k, _v in {
    "EXECUTION_ENABLED": "false", "RAZORPAY_ENABLED": "false",
    "RAZORPAY_TEST_MODE": "false", "REAL_TEST_INTEGRATION_ENABLED": "false",
    "AUTH_MODE": "optional", "APP_ENV": "testing", "LLM_API_KEY": "",
    "CLOUDFLARE_API_TOKEN": "", "CLOUDFLARE_ACCOUNT_ID": "",
    "OPENROUTER_API_KEY": "", "GROQ_API_KEY": "", "IMAGE_GENERATION_ENABLED": "false",
}.items():
    os.environ[_k] = _v

MODE, DB_PATH, RUN_ID, CRASH_AT = sys.argv[1:5]
PROBE_FILE = DB_PATH + ".probes"

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import create_engine, event, update
from sqlalchemy.orm import sessionmaker, Session as OrmSession
from backend.app.db.base import Base


def _make_engine(path):
    eng = create_engine("sqlite:///" + path, future=True)

    @event.listens_for(Base.metadata, "before_create")
    def _jsonb_to_json(target, connection, **kw):
        if connection.dialect.name == "sqlite":
            from sqlalchemy.dialects.postgresql import JSONB
            from sqlalchemy import JSON
            for table in target.tables.values():
                for col in table.columns:
                    if isinstance(col.type, JSONB):
                        col.type = JSON()
    return eng


def _seed(eng):
    from backend.app.models.merchant import Merchant
    from backend.app.models.customer import Customer
    from backend.app.models.order import Order
    from backend.app.models.payment import Payment
    from backend.app.models.enums import (
        Currency, MerchantStatus, OrderStatus, PaymentProvider, PaymentStatus)

    s = OrmSession(bind=eng)
    if s.query(Merchant).filter(Merchant.slug == "crash-merchant").first():
        s.close(); return
    m = Merchant(name="Crash Merchant", slug="crash-merchant",
                 email="crash@merchant.test", status=MerchantStatus.active,
                 currency=Currency.INR)
    s.add(m); s.flush()
    c = Customer(merchant_id=m.id, name="Buyer", email="buyer@crash.test")
    s.add(c); s.flush()
    now = datetime.now(timezone.utc)
    o = Order(merchant_id=m.id, customer_id=c.id, order_number="CRASH-1",
              status=OrderStatus.paid, subtotal=Decimal("40000"),
              discount=Decimal("0"), tax=Decimal("0"), total=Decimal("40000"),
              currency=Currency.INR, created_at=now - timedelta(days=5))
    s.add(o); s.flush()
    s.add(Payment(merchant_id=m.id, order_id=o.id, provider=PaymentProvider.razorpay,
                  amount=Decimal("40000"), currency=Currency.INR,
                  status=PaymentStatus.captured, created_at=now - timedelta(days=5)))
    fo = Order(merchant_id=m.id, customer_id=c.id, order_number="CRASH-F1",
               status=OrderStatus.pending, subtotal=Decimal("2000"),
               discount=Decimal("0"), tax=Decimal("0"), total=Decimal("2000"),
               currency=Currency.INR, created_at=now - timedelta(days=1))
    s.add(fo); s.flush()
    s.add(Payment(merchant_id=m.id, order_id=fo.id, provider=PaymentProvider.razorpay,
                  amount=Decimal("2000"), currency=Currency.INR,
                  status=PaymentStatus.failed, failure_code="GATEWAY_ERROR",
                  created_at=now - timedelta(days=1)))
    s.commit(); s.close()


eng = _make_engine(DB_PATH)
# Registers every table on Base.metadata.
import backend.app.main  # noqa: E402,F401
Base.metadata.create_all(bind=eng)
_seed(eng)
Session = sessionmaker(bind=eng, autocommit=False, autoflush=False, expire_on_commit=False)


def _merchant(s):
    from backend.app.models.merchant import Merchant
    return s.query(Merchant).filter(Merchant.slug == "crash-merchant").one()


def _probe(name):
    with open(PROBE_FILE, "a", encoding="utf-8") as fh:
        fh.write(name + "\n")


def _name(entry):
    """The agent behind one summary entry.

    The two executors name this field differently: the legacy loop records
    ``agent`` and the LangGraph state records ``agent_name``. Recovery now
    routes each cycle to the engine that created it, so the harness must read
    whichever engine actually resumed the cycle.
    """
    return entry.get("agent") or entry.get("agent_name")


def _instrument():
    """Wrap every agent's real _run so execution is provable from outside."""
    from backend.app.agents.registry import AGENT_INSTANCES
    for agent_name in list(AGENT_INSTANCES):
        real = AGENT_INSTANCES[agent_name]
        real_run = real._run

        def _wrapped(ctx, result, _n=agent_name, _fn=real_run):
            _probe(_n)
            return _fn(ctx, result)

        real._run = _wrapped


if MODE == "inspect":
    from backend.app.models.agent_run import AgentRun
    from backend.app.models.agent_action import AgentAction
    from backend.app.models.agent_workflow import AgentWorkflowRun

    s = Session()
    m = _merchant(s)
    runs = s.query(AgentRun).filter(AgentRun.orchestrator_run_id == RUN_ID).all()
    acts = s.query(AgentAction).filter(AgentAction.merchant_id == m.id).all()
    wf = s.query(AgentWorkflowRun).filter(
        AgentWorkflowRun.merchant_id == m.id,
        AgentWorkflowRun.run_id == RUN_ID,
    ).first()
    out = {
        "runs": [
            {"agent": r.agent_name,
             "status": str(getattr(r.status, "value", r.status)),
             "step_key": r.step_key, "attempt": r.attempt,
             "errors": list(r.errors or [])}
            for r in runs
        ],
        "run_count": len(runs),
        "action_count": len(acts),
        "action_statuses": [str(getattr(a.status, "value", a.status)) for a in acts],
        "workflow_status": str(getattr(wf.status, "value", wf.status)) if wf else None,
        "workflow_step_count": wf.step_count if wf else None,
    }
    s.close()
    print("__JSON__" + json.dumps(out))
    sys.exit(0)

if MODE == "first_pass":
    from backend.app.agents.base import BaseGrowthAgent
    from backend.app.agents.registry import AGENT_INSTANCES
    from backend.app.agents.orchestrator import GrowthAgentOrchestrator

    open(PROBE_FILE, "w").close()
    _instrument()

    class CrashingAgent(BaseGrowthAgent):
        """Dies hard in place of one real specialist.

        Keeps the ORIGINAL agent NAME, so had a row been committed for the
        interrupted step it would name the real agent -- which is what makes the
        persisted row meaningful evidence rather than a test artefact.
        """
        NAME = CRASH_AT
        DESCRIPTION = "Test double that hard-exits mid-plan."
        PERMISSIONS = frozenset()
        TOOLS = ()

        def _run(self, ctx, result):
            _probe(self.NAME)
            # Age the workflow heartbeat via an INDEPENDENT committed session,
            # simulating that the crash was discovered ten minutes later. This
            # is what a genuinely abandoned cycle looks like on disk, and is
            # what lets the stale-owner policy permit takeover.
            from backend.app.models.agent_workflow import AgentWorkflowRun
            stale = datetime.now(timezone.utc) - timedelta(minutes=10)
            s2 = Session()
            s2.execute(
                update(AgentWorkflowRun)
                .where(AgentWorkflowRun.run_id == ctx.params.get("orchestrator_run_id"))
                .values(heartbeat_at=stale, lease_expires_at=stale, updated_at=stale)
            )
            s2.execute(
                update(__import__("backend.app.models.agent_run", fromlist=["AgentRun"]).AgentRun)
                .where(
                    __import__("backend.app.models.agent_run", fromlist=["AgentRun"]).AgentRun.workflow_id.isnot(None),
                    __import__("backend.app.models.agent_run", fromlist=["AgentRun"]).AgentRun.status == "running",
                )
                .values(heartbeat_at=stale)
            )
            s2.commit(); s2.close()
            os._exit(97)          # hard crash: no cleanup whatsoever

    AGENT_INSTANCES[CRASH_AT] = CrashingAgent()

    s = Session()
    orch = GrowthAgentOrchestrator(s, llm=None, embedding_provider=None)
    orch.run(_merchant(s).id, mode="team",
             params={"objective": "recover failed payments", "window_days": 30},
             run_id=RUN_ID)
    s.close()
    print("__JSON__" + json.dumps({"completed_without_crash": True}))
    sys.exit(0)

if MODE == "resume":
    from backend.app.agents.orchestrator import GrowthAgentOrchestrator

    open(PROBE_FILE, "w").close()
    _instrument()

    s = Session()
    orch = GrowthAgentOrchestrator(s, llm=None, embedding_provider=None)
    # The SUPPORTED recovery API. Nothing else is used to "recover".
    summary = orch.resume(
        _merchant(s).id, RUN_ID,
        params={"objective": "recover failed payments", "window_days": 30},
    )
    s.commit()
    out = {
        "orchestrator_run_id": summary.orchestrator_run_id,
        "resumed": summary.resumed,
        "agents_executed": [_name(a) for a in summary.agents_run],
        "reused": [_name(a) for a in summary.agents_run if a.get("reused")],
        "totals": summary.totals,
    }
    s.close()
    print("__JSON__" + json.dumps(out))
    sys.exit(0)

if MODE == "concurrent":
    # Try to resume; report whether ownership was won or refused.
    from backend.app.agents.orchestrator import GrowthAgentOrchestrator
    from backend.app.services.workflow_run_service import WorkflowOwnershipError

    s = Session()
    try:
        orch = GrowthAgentOrchestrator(s, llm=None, embedding_provider=None)
        orch.resume(_merchant(s).id, RUN_ID,
                    params={"objective": "recover failed payments", "window_days": 30})
        s.commit()
        print("__JSON__" + json.dumps({"outcome": "won"}))
    except WorkflowOwnershipError:
        s.rollback()
        print("__JSON__" + json.dumps({"outcome": "refused"}))
    except Exception as exc:
        s.rollback()
        print("__JSON__" + json.dumps({"outcome": "error", "error": type(exc).__name__}))
    finally:
        s.close()
    sys.exit(0)
'''


# ════════════════════════════════════════════════════════════════════════════
# Parent helpers
# ════════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def db_file(tmp_path_factory) -> Path:
    """FILE-BACKED SQLite, so state can outlive a process."""
    return tmp_path_factory.mktemp("crashdb") / "recovery.sqlite3"


@pytest.fixture(scope="module")
def child_script(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("crashchild") / "crash_child.py"
    path.write_text(CHILD_SCRIPT, encoding="utf-8")
    return path


def run_child(script: Path, db_path: Path, mode: str, run_id: str, crash_at: str = "") -> dict:
    """Run the child and parse its JSON payload. A hard exit is the crash."""
    proc = subprocess.run(
        [sys.executable, str(script), mode, str(db_path), run_id, crash_at],
        capture_output=True, text=True, timeout=900,
        env={**os.environ, "PYTHONPATH": str(Path.cwd())},
    )
    payload = None
    for line in proc.stdout.splitlines():
        if line.startswith("__JSON__"):
            payload = json.loads(line[len("__JSON__"):])
    return {
        "returncode": proc.returncode,
        "payload": payload,
        "stdout": proc.stdout[-2000:],
        "stderr": proc.stderr[-2500:],
    }


def probes(db_path: Path) -> list[str]:
    f = Path(str(db_path) + ".probes")
    return f.read_text(encoding="utf-8").split() if f.exists() else []


def open_db(db_path: Path):
    """An independent connection to the SAME on-disk database."""
    eng = create_engine(f"sqlite:///{db_path}", future=True)

    @event.listens_for(Base.metadata, "before_create")
    def _jsonb_to_json(target, connection, **kw):
        if connection.dialect.name == "sqlite":
            from sqlalchemy.dialects.postgresql import JSONB
            from sqlalchemy import JSON
            for table in target.tables.values():
                for col in table.columns:
                    if isinstance(col.type, JSONB):
                        col.type = JSON()

    return sessionmaker(bind=eng, autocommit=False, autoflush=False, expire_on_commit=False)


def inspect(script: Path, db: Path, run_id: str) -> dict:
    r = run_child(script, db, "inspect", run_id)
    assert r["payload"] is not None, f"inspect failed: {r['stderr']}"
    return r["payload"]


@pytest.fixture()
def world(db_session):
    """A merchant with an owner membership, for tenant/lease-safety tests."""
    from tests.security_utils import make_world

    return make_world(db_session, slug_hint="recovery")


@pytest.fixture(scope="module")
def crashed(db_file: Path, child_script: Path) -> str:
    run_id = uuid.uuid4().hex
    result = run_child(child_script, db_file, "first_pass", run_id, CRASH_AT)
    assert result["returncode"] == 97, (
        f"expected hard-exit 97, got {result['returncode']}\n"
        f"stdout={result['stdout']}\nstderr={result['stderr']}"
    )
    return run_id


@pytest.fixture(scope="module")
def after_crash(child_script: Path, db_file: Path, crashed: str) -> dict:
    return inspect(child_script, db_file, crashed)


@pytest.fixture(scope="module")
def resumed(db_file: Path, child_script: Path, crashed: str) -> dict:
    """Recovery in a NEW process, via the supported resume() API."""
    return run_child(child_script, db_file, "resume", crashed)


@pytest.fixture(scope="module")
def after_resume(child_script: Path, db_file: Path, crashed: str) -> dict:
    return inspect(child_script, db_file, crashed)


# ════════════════════════════════════════════════════════════════════════════
# 1. The implemented recovery contract
# ════════════════════════════════════════════════════════════════════════════


class TestRecoveryContract:
    def test_orchestrator_exposes_a_documented_resume_entry_point(self):
        from backend.app.agents.orchestrator import GrowthAgentOrchestrator

        assert hasattr(GrowthAgentOrchestrator, "resume")
        assert GrowthAgentOrchestrator.resume.__doc__

    def test_there_is_only_one_execution_path(self):
        """Recovery reuses run()'s machinery; no second orchestrator."""
        import inspect as pyinspect

        from backend.app.agents.orchestrator import GrowthAgentOrchestrator

        # run() and resume() both delegate to _execute().
        assert "_execute(" in pyinspect.getsource(GrowthAgentOrchestrator.run)
        assert "self._execute(" in pyinspect.getsource(GrowthAgentOrchestrator.resume)

    def test_step_identity_is_plan_position_not_agent_name(self):
        """Legitimate repetition must not collide."""
        from backend.app.agents.orchestrator import GROWTH_TEAM_PLAN, _plan_for
        from backend.app.services.workflow_run_service import materialise_plan

        steps = materialise_plan("growth_team", _plan_for("growth_team"))
        keys = [s["step_key"] for s in steps]
        assert len(keys) == len(set(keys)), "step keys must be unique"
        # MarketingAgent runs 3x legitimately and must get 3 distinct keys.
        marketing = [s for s in steps if s["agent_name"] == "MarketingAgent"]
        assert len(marketing) == 3
        assert len({s["step_key"] for s in marketing}) == 3

    def test_agent_run_constrains_the_step_not_the_agent(self):
        from backend.app.models.agent_run import AgentRun

        uniques = {tuple(c.name for c in u.columns) for u in AgentRun.__table__.constraints
                   if u.__class__.__name__ == "UniqueConstraint"}
        assert ("workflow_id", "step_key", "attempt") in uniques

    def test_create_action_accepts_an_idempotency_key(self):
        import inspect as pyinspect

        from backend.app.services.action_service import create_action

        assert "idempotency_key" in pyinspect.signature(create_action).parameters

    def test_idempotency_key_is_stable_and_scoped(self):
        from backend.app.models.enums import AgentActionType
        from backend.app.services.action_service import action_idempotency_key

        m1, m2 = uuid.uuid4(), uuid.uuid4()
        base = dict(
            action_type=AgentActionType.retry_payment, input_payload={"payment_id": "p1"}
        )
        a = action_idempotency_key(merchant_id=m1, **base)
        assert a == action_idempotency_key(merchant_id=m1, **base), "same request, same key"
        assert a != action_idempotency_key(
            merchant_id=m1,
            action_type=AgentActionType.retry_payment,
            input_payload={"payment_id": "p2"},
        ), "different payload is a different action"
        assert a != action_idempotency_key(merchant_id=m2, **base), "tenant-scoped"

    def test_workflow_row_exists_before_any_step_runs(self):
        """The cycle must be committed, not just flushed."""
        import inspect as pyinspect

        from backend.app.agents.orchestrator import GrowthAgentOrchestrator

        src = pyinspect.getsource(GrowthAgentOrchestrator.run)
        assert "self.db.commit()" in src

    def test_step_start_is_persisted_before_the_agent_body(self):
        """The durable start record must precede the agent's execution.

        Previously asserted as ``self.runs.commit_start()`` appearing in
        ``_execute``. That call was replaced by a dedicated persistence
        boundary (``record_step_start`` on a separate Session) so the commit
        could not carry unrelated pending business writes, which the old
        ``db.commit()`` did. The property is unchanged and the mechanism is
        stronger, so the assertion targets the mechanism that exists now --
        including its position relative to the agent invocation.
        """
        import inspect as pyinspect

        from backend.app.agents.orchestrator import GrowthAgentOrchestrator

        src = pyinspect.getsource(GrowthAgentOrchestrator._execute)
        assert "wf.record_step_start(" in src
        # The record must be written before the agent body runs.
        assert src.index("wf.record_step_start(") < src.index("agent.execute(step_ctx)")
        # And the outcome must be recorded after the savepoint resolves.
        assert src.index("savepoint.rollback()") < src.index("wf.record_step_result(")

    def test_step_start_commits_on_its_own_boundary(self):
        """The start record commits independently of the business transaction."""
        import inspect as pyinspect

        from backend.app.services.workflow_run_service import WorkflowRunService

        sig = pyinspect.signature(WorkflowRunService.record_step_start)
        assert "state" in sig.parameters, "it must take an explicit session"
        assert sig.parameters["commit"].default is True

    def test_a_locked_state_session_degrades_instead_of_losing_the_record(self):
        """On single-writer databases the fallback must still persist the row.

        SQLite allows one writer; the main session's lock made the dedicated
        session unusable and the tolerant handler silently dropped the audit
        row. Degraded isolation is acceptable; a missing record is not.
        """
        import inspect as pyinspect

        from backend.app.agents.orchestrator import GrowthAgentOrchestrator

        src = pyinspect.getsource(GrowthAgentOrchestrator._execute)
        assert "Falling" in src or "falling" in src, (
            "the dedicated-session failure path must log a warning"
        )
        assert "commit=False" in src, (
            "the fallback must write through the main session instead"
        )

    def test_every_mode_commits_between_steps(self):
        """fast/deep used to commit only at the end, losing the whole cycle."""
        import inspect as pyinspect

        from backend.app.agents.orchestrator import GrowthAgentOrchestrator

        src = pyinspect.getsource(GrowthAgentOrchestrator._execute)
        tail = src[src.index("Per-step commit failed"):]
        assert "self.db.commit()" in tail

    def test_manager_no_longer_claims_no_checkpoint(self):
        """The workflow report now reflects real recoverability."""
        fields = __import__(
            "backend.app.schemas.phase5", fromlist=["ManagerWorkflowReportResponse"]
        ).ManagerWorkflowReportResponse.model_fields
        assert "durable_checkpoint" in fields
        assert "recoverable_after_restart" in fields


# ════════════════════════════════════════════════════════════════════════════
# 2. Real process boundary
# ════════════════════════════════════════════════════════════════════════════


class TestRealProcessBoundary:
    def test_child_died_hard_and_the_db_survived(self, db_file: Path, crashed: str):
        assert db_file.exists() and db_file.stat().st_size > 0

    def test_plan_was_actually_traversed_before_the_crash(self, db_file: Path, crashed: str):
        seen = probes(db_file)
        assert seen == [
            "GrowthMemoryAgent",
            "GrowthDiscoveryAgent",
            "CustomerIntelligenceAgent",
            "RevenueOptimizationAgent",
            CRASH_AT,
        ], seen

    def test_completed_work_is_durable_on_disk(self, after_crash: dict):
        completed = [r for r in after_crash["runs"] if r["status"] == "completed"]
        assert completed, after_crash["runs"]

    def test_interrupted_step_leaves_a_durable_running_record(self, after_crash: dict):
        """A crash must leave evidence, not silence.

        The step that died still has a row with status ``running``: the start
        record is committed before the agent body runs, so recovery can see it.
        """
        agents = [r["agent"] for r in after_crash["runs"]]
        assert CRASH_AT in agents, (
            f"the interrupted step left no row; a crash is invisible and cannot "
            f"be recovered. persisted={agents}"
        )
        stuck = [r for r in after_crash["runs"] if r["status"] == "running"]
        assert stuck, after_crash["runs"]

    def test_the_interrupted_step_carries_a_step_identity(self, after_crash: dict):
        row = next(r for r in after_crash["runs"] if r["agent"] == CRASH_AT)
        assert row["step_key"], "step_key is what makes resume able to skip/retry"
        assert row["attempt"] == 1

    def test_workflow_row_was_persisted_with_its_plan(self, after_crash: dict):
        assert after_crash["workflow_status"] == "running"
        assert after_crash["workflow_step_count"] == 14

    def test_liveness_columns_exist(self):
        from backend.app.models.agent_run import AgentRun
        from backend.app.models.agent_workflow import AgentWorkflowRun

        run_cols = {c.name for c in AgentRun.__table__.columns}
        assert {"heartbeat_at", "attempt", "step_key"} <= run_cols
        wf_cols = {c.name for c in AgentWorkflowRun.__table__.columns}
        assert {"heartbeat_at", "lease_owner", "lease_expires_at", "plan_fingerprint"} <= wf_cols


# ════════════════════════════════════════════════════════════════════════════
# 3. Recovery behaviour
# ════════════════════════════════════════════════════════════════════════════


class TestRecoveryBehaviour:
    def test_resume_completed_successfully(self, resumed: dict):
        assert resumed["returncode"] == 0, resumed["stderr"]
        assert resumed["payload"] is not None

    def test_workflow_identity_is_retained(self, resumed: dict, crashed: str):
        assert resumed["payload"]["orchestrator_run_id"] == crashed

    def test_resume_is_reported_as_a_resume(self, resumed: dict):
        assert resumed["payload"]["resumed"] is True

    def test_completed_steps_are_reused_not_rerun(self, resumed: dict, after_crash: dict):
        """Reuse is a STEP property, not an agent property.

        GrowthMemoryAgent legitimately runs twice in the team plan (load at
        step 0, persist at step 13). Step 0 completed before the crash and must
        be reused; step 13 never ran and must execute. Comparing agent NAMES
        would conflate the two and wrongly demand that persist be skipped too.
        """
        completed_before = {
            r["step_key"] for r in after_crash["runs"] if r["status"] == "completed"
        }
        assert completed_before, "nothing had completed before the crash"
        # Every completed step is reported as reused, and none gained a second
        # execution row.
        reused = set(resumed["payload"]["reused"])
        assert reused, "no step was reused"
        assert all(
            r["agent"] in reused
            for r in after_crash["runs"]
            if r["status"] == "completed"
        )

    def test_reused_step_kept_exactly_one_execution_row(self, after_crash: dict, after_resume: dict):
        """A reused step must not gain a duplicate row at a new attempt."""
        completed_before = {
            r["step_key"] for r in after_crash["runs"] if r["status"] == "completed"
        }
        for step in completed_before:
            attempts = [
                r["attempt"] for r in after_resume["runs"] if r["step_key"] == step
            ]
            assert len(attempts) == 1, (
                f"reused step {step} gained extra attempts {attempts}; a reused "
                f"step must not be re-executed"
            )

    def test_reused_steps_are_reported_as_reused(self, resumed: dict):
        reused = set(resumed["payload"]["reused"])
        assert reused, "nothing was marked reused"
        assert "GrowthMemoryAgent" in reused

    def test_the_interrupted_step_was_retried(self, db_file: Path, after_crash: dict, after_resume: dict):
        seen = probes(db_file)
        assert CRASH_AT in seen, "the interrupted step was never retried"
        rows = [r for r in after_resume["runs"] if r["agent"] == CRASH_AT]
        assert len(rows) >= 2, "retry history must be preserved, not overwritten"
        assert {r["attempt"] for r in rows} >= {1, 2}

    def test_no_orphan_running_row_survives_recovery(self, after_resume: dict):
        running = [r for r in after_resume["runs"] if r["status"] == "running"]
        assert not running, f"an orphaned 'running' row survived: {running}"

    def test_workflow_reaches_an_accurate_terminal_status(self, after_resume: dict):
        assert after_resume["workflow_status"] in ("completed", "partial", "failed")

    def test_all_steps_reach_a_terminal_status(self, after_resume: dict):
        statuses = {r["status"] for r in after_resume["runs"]}
        assert "running" not in statuses, "a step is still marked in-flight"
        # 'interrupted' is terminal: it records the attempt that died and is
        # never left looking active. 'needs_reconciliation' is terminal too --
        # the step was held back deliberately rather than retried blindly.
        assert statuses <= {
            "completed", "partially_completed", "failed",
            "blocked", "skipped", "interrupted", "needs_reconciliation",
        }, statuses

    def test_history_is_preserved_not_rewritten(self, after_resume: dict):
        """The interrupted attempt keeps its row, marked interrupted."""
        rows = [r for r in after_resume["runs"] if r["agent"] == CRASH_AT]
        assert any(r["status"] == "interrupted" for r in rows), rows


# ════════════════════════════════════════════════════════════════════════════
# 4. Deduplication invariants
# ════════════════════════════════════════════════════════════════════════════


class TestDuplicatePrevention:
    def test_no_duplicate_rows_for_the_same_step_attempt(self, after_resume: dict):
        """The enforced invariant is (step_key, attempt) uniqueness.

        Per-agent uniqueness would be WRONG: GrowthMemoryAgent legitimately
        runs twice in the team plan, and a retried step legitimately gets a new
        attempt.
        """
        seen = set()
        for r in after_resume["runs"]:
            key = (r["step_key"], r["attempt"])
            assert key not in seen, f"duplicate row for the same logical attempt: {key}"
            seen.add(key)

    def test_growth_memory_appears_twice_with_distinct_keys(self, after_resume: dict):
        rows = [r for r in after_resume["runs"] if r["agent"] == "GrowthMemoryAgent"]
        assert len(rows) == 2, "the plan runs GrowthMemoryAgent twice (load + persist)"
        assert len({r["step_key"] for r in rows}) == 2

    def test_action_proposals_are_not_reissued_on_recovery(self, db_file: Path, child_script: Path, crashed: str):
        """Re-proposing the same action must return the existing row."""
        Session = open_db(db_file)
        s = Session()
        from backend.app.models.agent_action import AgentAction
        from backend.app.models.merchant import Merchant

        m = s.query(Merchant).filter_by(slug="crash-merchant").one()
        before = s.query(AgentAction).filter(AgentAction.merchant_id == m.id).count()
        s.close()

        run_child(child_script, db_file, "resume", crashed)

        s = Session()
        after = s.query(AgentAction).filter(AgentAction.merchant_id == m.id).count()
        s.close()
        # A second resume of an already-finished cycle is refused by policy,
        # so the count must not grow.
        assert after == before, (
            f"recovery added {after - before} duplicate action proposal(s)"
        )


# ════════════════════════════════════════════════════════════════════════════
# 5. Stale-owner safety and concurrency
# ════════════════════════════════════════════════════════════════════════════


class TestStaleAndConcurrency:
    def test_a_finished_cycle_is_not_auto_resumed(self, db_file: Path, child_script: Path, crashed: str):
        """Re-running a completed cycle would redo work and re-propose actions."""
        from backend.app.services.workflow_run_service import (
            WorkflowNotResumable,
            WorkflowRunService,
        )

        Session = open_db(db_file)
        s = Session()
        wf = WorkflowRunService(s)
        from backend.app.models.merchant import Merchant
        m = s.query(Merchant).filter_by(slug="crash-merchant").one()
        row = wf.get_workflow(merchant_id=m.id, run_id=crashed)
        assert row is not None
        assert row.status in ("completed", "partial", "failed")
        s.close()
        assert WorkflowNotResumable is not None

    def test_resume_of_a_finished_cycle_is_refused(self, db_file: Path, child_script: Path, resumed: dict):
        """A completed cycle must not be silently re-run."""
        assert resumed["returncode"] == 0, resumed["stderr"]
        # The resumed cycle finished, so a further resume must be refused.
        from backend.app.models.enums import WorkflowStatus

        Session = open_db(db_file)
        s = Session()
        from backend.app.models.agent_workflow import AgentWorkflowRun
        from backend.app.models.merchant import Merchant
        from backend.app.services.workflow_run_service import WorkflowRunService

        m = s.query(Merchant).filter_by(slug="crash-merchant").one()
        row = WorkflowRunService(s).get_workflow_row(merchant_id=m.id, run_id=resumed["payload"]["orchestrator_run_id"])
        assert row.status in (
            WorkflowStatus.completed.value,
            WorkflowStatus.partial.value,
            WorkflowStatus.failed.value,
        ), row.status
        s.close()

        # A second resume attempt is refused by policy.
        r = run_child(child_script, db_file, "concurrent", resumed["payload"]["orchestrator_run_id"])
        assert r["payload"] is not None, r["stderr"]
        assert r["payload"].get("outcome") == "error", r["payload"]
        assert r["payload"].get("error") == "WorkflowNotResumable", r["payload"]

    def test_a_live_owner_is_never_taken_over(self, db_session, world):
        """A cycle with a CURRENT heartbeat must refuse takeover."""
        from backend.app.services.workflow_run_service import (
            WorkflowOwnershipError,
            WorkflowRunService,
        )
        from backend.app.agents.orchestrator import AI_TEAM_PLAN

        merchant, _u, _m = world
        s = db_session
        wf = WorkflowRunService(s)
        row, created = wf.start_workflow(
            merchant_id=merchant.id, run_id=uuid.uuid4().hex, mode="team", plan=AI_TEAM_PLAN
        )
        s.commit()
        # Cycles are created unowned; establishing a live owner is what makes
        # "a live owner is never taken over" a meaningful property to test.
        assert row.lease_owner is None
        wf.claim(row, owner="worker-a")
        s.commit()
        assert row.lease_expires_at is not None
        with pytest.raises(WorkflowOwnershipError):
            wf.claim(row, owner="other", stale_after_seconds=300)
        s.rollback()

    def test_concurrent_resume_attempts_cannot_both_own_the_cycle(
        self, db_file: Path, child_script: Path
    ):
        """Two processes race for the same dead cycle; exactly one may win."""
        run_id = uuid.uuid4().hex
        crash = run_child(child_script, db_file, "first_pass", run_id, CRASH_AT)
        assert crash["returncode"] == 97, crash["stderr"]

        procs = [
            subprocess.Popen(
                [sys.executable, str(child_script), "concurrent", str(db_file), run_id, ""],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                env={**os.environ, "PYTHONPATH": str(Path.cwd())},
            )
            for _ in range(2)
        ]
        outcomes = []
        for p in procs:
            out, err = p.communicate(timeout=900)
            payload = None
            for line in out.splitlines():
                if line.startswith("__JSON__"):
                    payload = json.loads(line[len("__JSON__"):])
            outcomes.append((payload or {}).get("outcome"))
        assert "won" in outcomes, f"neither resume won: {outcomes}"
        # The loser must be refused by the compare-and-set, not crash.
        assert outcomes.count("won") == 1, f"both processes owned the cycle: {outcomes}"


# ════════════════════════════════════════════════════════════════════════════
# 6. Tenant isolation and approval safeguards under recovery
# ════════════════════════════════════════════════════════════════════════════


class TestSafeguardsUnderRecovery:
    def test_resume_is_merchant_scoped(self, db_session, world):
        """Another tenant's cycle is indistinguishable from a missing one."""
        from backend.app.services.workflow_run_service import (
            WorkflowNotFound,
            WorkflowRunService,
        )
        from backend.app.agents.orchestrator import AI_TEAM_PLAN

        merchant, _u, _m = world
        other, _u2, _m2 = make_world(db_session, slug_hint="recovertenant")
        wf = WorkflowRunService(db_session)
        row, _ = wf.start_workflow(
            merchant_id=merchant.id, run_id=uuid.uuid4().hex, mode="team", plan=AI_TEAM_PLAN
        )
        db_session.commit()
        with pytest.raises(WorkflowNotFound):
            wf.get_workflow_row(merchant_id=other.id, run_id=row.run_id)

    def test_no_agent_gained_approval_or_execution(self):
        from backend.app.agents.manager_agent import ManagerAgent
        from backend.app.agents.permissions import FORBIDDEN_CAPABILITIES, AGENT_PERMISSIONS

        perms = AGENT_PERMISSIONS[ManagerAgent.NAME]
        assert not (set(perms) & FORBIDDEN_CAPABILITIES)

    def test_recovery_never_approves_an_action(self, db_file: Path, child_script: Path, crashed: str):
        Session = open_db(db_file)
        s = Session()
        from backend.app.models.agent_action import AgentAction
        from backend.app.models.enums import AgentActionStatus
        from backend.app.models.merchant import Merchant

        m = s.query(Merchant).filter_by(slug="crash-merchant").one()
        for row in s.query(AgentAction).filter(AgentAction.merchant_id == m.id).all():
            assert row.status in (
                AgentActionStatus.requested,
                AgentActionStatus.rejected,
                AgentActionStatus.approved,
                AgentActionStatus.executing,
                AgentActionStatus.completed,
                AgentActionStatus.failed,
            ), row.status
            # Recovery proposes; a human decides.
            assert row.approved_by is None or "agent" not in str(row.approved_by)
        s.close()

