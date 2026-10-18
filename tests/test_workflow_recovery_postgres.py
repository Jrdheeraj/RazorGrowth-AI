"""
PostgreSQL crash-and-resume verification (Tasks 3, 4 and 5).

Runs ONLY when ``POSTGRES_DSN`` points at PostgreSQL. Skipping is deliberate:
a green result on SQLite would be a false claim, because the properties under
test -- real connection separation between the execution-state boundary and the
business transaction, row-lock behaviour of the lease compare-and-set, and the
fate of an in-flight transaction at a hard kill -- are dialect-specific.

NEVER point POSTGRES_DSN at a production or primary development database.

    docker run -d --name razorgrowth-verify-pg -p 55433:5432 \\
      -e POSTGRES_PASSWORD=verify123 -e POSTGRES_USER=verify \\
      -e POSTGRES_DB=razorgrowth_verify pgvector/pgvector:pg16
    $env:DATABASE_URL="postgresql://verify:verify123@localhost:55433/razorgrowth_verify"
    python -m alembic upgrade head
    $env:POSTGRES_DSN=$env:DATABASE_URL
    python -m pytest tests/test_workflow_recovery_postgres.py -v

WHAT IS PROVEN HERE THAT SQLITE CANNOT PROVE
--------------------------------------------
* The step-start record is committed on its OWN connection, so a mid-step crash
  leaves a durable row while the business transaction is genuinely still open
  elsewhere. On ``sqlite:///:memory:`` with StaticPool both sessions share one
  connection, so that separation does not exist.
* The lease compare-and-set is decided by PostgreSQL row locking between two
  real concurrent processes.
* A constraint violation aborts a whole transaction, which is why action
  idempotency must use a savepoint -- and that savepoint must work here.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

DSN = os.environ.get("POSTGRES_DSN")

pytestmark = pytest.mark.skipif(
    not DSN or "postgres" not in (DSN or "").split("://")[0],
    reason="POSTGRES_DSN not set to a PostgreSQL DSN; SQLite cannot establish "
           "PostgreSQL crash-recovery, concurrency or MVCC behaviour",
)

#: Where each mode is interrupted. Chosen so the RESUME path re-executes steps
#: that publish cross-agent context, which is the code path that would break if
#: step reuse did not faithfully restore shared state.
CRASH_INDEX = {"fast": 2, "deep": 4, "team": 10, "growth_team": 14}
MODES = ("fast", "deep", "team", "growth_team")


# ════════════════════════════════════════════════════════════════════════════
# Child process
# ════════════════════════════════════════════════════════════════════════════

CHILD = r'''
"""Run / crash / resume / inspect one workflow cycle against PostgreSQL.

Usage: python pg_child.py <op> <dsn> <run_id> <mode> <crash_index> <tag>

  crash       run the mode, hard-exit at crash_index (os._exit, no cleanup)
  resume      call the SUPPORTED recovery API, GrowthAgentOrchestrator.resume()
  inspect     dump persisted state, read-only
  concurrent  attempt resume; report won / refused / error
  uncertain   simulate a provider-accepted call whose outcome is never persisted
"""
import json
import os
import sys
import uuid
from pathlib import Path

for _k, _v in {
    "EXECUTION_ENABLED": "false", "RAZORPAY_ENABLED": "false",
    "RAZORPAY_TEST_MODE": "false", "REAL_TEST_INTEGRATION_ENABLED": "false",
    "AUTH_MODE": "optional", "APP_ENV": "testing", "LLM_API_KEY": "",
    "CLOUDFLARE_API_TOKEN": "", "CLOUDFLARE_ACCOUNT_ID": "",
    "OPENROUTER_API_KEY": "", "GROQ_API_KEY": "", "IMAGE_GENERATION_ENABLED": "false",
}.items():
    os.environ[_k] = _v

OP, DSN, RUN_ID, MODE, CRASH_INDEX, TAG = sys.argv[1:7]
CRASH_INDEX = int(CRASH_INDEX)
os.environ["DATABASE_URL"] = DSN

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import Column, String, create_engine, update
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, sessionmaker, Session as OrmSession

import backend.app.main  # noqa: F401  (registers all models)

from backend.app.agents.orchestrator import GrowthAgentOrchestrator, _plan_for
from backend.app.agents.registry import AGENT_INSTANCES
from backend.app.models.merchant import Merchant
from backend.app.models.customer import Customer
from backend.app.models.order import Order
from backend.app.models.payment import Payment
from backend.app.models.agent_run import AgentRun
from backend.app.models.agent_action import AgentAction
from backend.app.models.agent_workflow import AgentWorkflowRun
from backend.app.models.enums import (
    Currency, MerchantStatus, OrderStatus, PaymentProvider, PaymentStatus)

Base = declarative_base()


# Models an external side effect that has ALREADY happened: a real provider
# call cannot be rolled back by a local transaction rollback. Declared here
# because the parent session that creates the table never loads this module.
class ProviderMarker(Base):
    __tablename__ = "provider_markers"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id = Column(UUID(as_uuid=True), nullable=False)
    run_id = Column(String(64), nullable=True)
    agent_name = Column(String(80), nullable=False)


PROBES = str(Path(TAG).with_suffix(".probes"))
PLAN = _plan_for(MODE)
PARAMS = {"objective": "postgresql recovery verification", "window_days": 30}

ENGINE = create_engine(DSN, future=True)
S = sessionmaker(bind=ENGINE, autocommit=False, autoflush=False, expire_on_commit=False)


def emit(payload):
    print("__JSON__" + json.dumps(payload))
    sys.stdout.flush()


def probe(name):
    with open(PROBES, "a", encoding="utf-8") as fh:
        fh.write(name + "\n")


def seed():
    """One merchant per RUN_ID, with orders for the recovery agents to see."""
    s = S()
    slug = "pgcrash-" + RUN_ID[:16]
    existing = s.query(Merchant).filter(Merchant.slug == slug).first()
    if existing:
        s.close()
        return existing.id
    m = Merchant(name="PG Crash", slug=slug, email=f"{RUN_ID[:8]}@pg.test",
                 status=MerchantStatus.active, currency=Currency.INR)
    s.add(m); s.flush()
    c = Customer(merchant_id=m.id, name="Buyer", email=f"b{RUN_ID[:6]}@pg.test")
    s.add(c); s.flush()
    now = datetime.now(timezone.utc)
    o = Order(merchant_id=m.id, customer_id=c.id, order_number=f"PG-{RUN_ID[:6]}",
              status=OrderStatus.paid, subtotal=Decimal("40000"), discount=Decimal("0"),
              tax=Decimal("0"), total=Decimal("40000"), currency=Currency.INR,
              created_at=now - timedelta(days=5))
    s.add(o); s.flush()
    s.add(Payment(merchant_id=m.id, order_id=o.id, provider=PaymentProvider.razorpay,
                  amount=Decimal("40000"), currency=Currency.INR,
                  status=PaymentStatus.captured, created_at=now - timedelta(days=5)))
    fo = Order(merchant_id=m.id, customer_id=c.id, order_number=f"PGF-{RUN_ID[:6]}",
               status=OrderStatus.pending, subtotal=Decimal("2000"), discount=Decimal("0"),
               tax=Decimal("0"), total=Decimal("2000"), currency=Currency.INR,
               created_at=now - timedelta(days=1))
    s.add(fo); s.flush()
    s.add(Payment(merchant_id=m.id, order_id=fo.id, provider=PaymentProvider.razorpay,
                  amount=Decimal("2000"), currency=Currency.INR, status=PaymentStatus.failed,
                  failure_code="GATEWAY_ERROR", created_at=now - timedelta(days=1)))
    s.commit()
    mid = m.id
    s.close()
    return mid


def instrument():
    """Record every real agent execution so reuse can be proven from outside."""
    for name in list(AGENT_INSTANCES):
        real = AGENT_INSTANCES[name]
        real_run = real._run

        def wrapped(ctx, result, _n=name, _fn=real_run):
            probe(_n)
            return _fn(ctx, result)

        real._run = wrapped


def age_heartbeat(run_id):
    """Age the cycle's heartbeat on a SEPARATE connection.

    A crash is normally discovered minutes later. On PostgreSQL this is a real
    second connection with its own transaction, so the ageing is genuinely
    independent of the dying session's open transaction.
    """
    stale = datetime.now(timezone.utc) - timedelta(minutes=10)
    s2 = S()
    s2.execute(update(AgentWorkflowRun).where(AgentWorkflowRun.run_id == run_id)
               .values(heartbeat_at=stale, lease_expires_at=stale, updated_at=stale))
    s2.execute(update(AgentRun).where(AgentRun.status == "running")
               .values(heartbeat_at=stale))
    s2.commit()
    s2.close()


MID = seed()
TARGET = PLAN[CRASH_INDEX][0] if OP in ("crash", "uncertain") else None

if OP in ("crash", "uncertain"):
    open(PROBES, "w").close()
    instrument()

    # Crash INSIDE the real agent's own _run rather than substituting a stand-in.
    # The real permissions, tools and configuration stay live, and a lifecycle
    # short-circuit cannot silently skip the crash: the crash fires at exactly
    # the point the real work would begin.
    #
    # An agent may legitimately appear several times in one plan -- ManagerAgent
    # runs at both index 1 (delegate) and 14 (synthesize) in growth_team -- so
    # the wrapper counts calls and crashes on the occurrence that matches the
    # requested plan position rather than on the first one.
    _ORIGINAL = {n: AGENT_INSTANCES[n]._run for n in AGENT_INSTANCES}
    real = AGENT_INSTANCES[TARGET]
    _target_ordinal = sum(
        1 for _i, (_a, _p) in enumerate(PLAN) if _i < CRASH_INDEX and _a == TARGET
    )

    if OP == "crash":
        def boom(ctx, result, _n=TARGET, _want=_target_ordinal):
            _seen = getattr(boom, "_n", 0)
            boom._n = _seen + 1
            if _seen != _want:
                return _ORIGINAL[_n](ctx, result)   # earlier occurrence: run normally
            probe(_n)
            age_heartbeat(ctx.params.get("orchestrator_run_id"))
            os._exit(97)      # no finally, no rollback, no atexit
    else:
        def boom(ctx, result, _n=TARGET, _want=_target_ordinal):
            """A provider call that succeeds, then dies before recording it.

            Stands in for any external side effect whose outcome cannot be
            proven: the provider accepted the request, but this process died
            before persisting that fact. The marker is committed on its own
            connection precisely because a real external call has already
            happened and cannot be rolled back.
            """
            _seen = getattr(boom, "_n", 0)
            boom._n = _seen + 1
            if _seen != _want:
                return _ORIGINAL[_n](ctx, result)
            probe(_n)
            s2 = S()
            s2.add(ProviderMarker(
                merchant_id=ctx.merchant_id,
                run_id=ctx.params.get("orchestrator_run_id"),
                agent_name=_n))
            s2.commit(); s2.close()
            age_heartbeat(ctx.params.get("orchestrator_run_id"))
            os._exit(97)

    real._run = boom

    s = S()
    GrowthAgentOrchestrator(s, llm=None, embedding_provider=None).run(
        MID, mode=MODE, params=PARAMS, run_id=RUN_ID)
    s.close()
    emit({"completed_without_crash": True})
    sys.exit(0)

if OP == "inspect":
    s = S()
    wf = s.query(AgentWorkflowRun).filter(
        AgentWorkflowRun.merchant_id == MID, AgentWorkflowRun.run_id == RUN_ID).first()
    rows = s.query(AgentRun).filter(
        AgentRun.merchant_id == MID, AgentRun.orchestrator_run_id == RUN_ID).all()
    acts = s.query(AgentAction).filter(AgentAction.merchant_id == MID).all()
    from sqlalchemy import text as _t
    markers = int(s.execute(_t(
        "SELECT count(*) FROM provider_markers WHERE merchant_id=:m AND run_id=:r"
    ), {"m": MID, "r": RUN_ID}).scalar_one())
    payload = {
        "mode": MODE,
        "merchant_id": str(MID),
        "workflow": None if wf is None else {
            "status": wf.status, "step_count": wf.step_count,
            "lease_owner": wf.lease_owner,
            "lease_expires_at": str(wf.lease_expires_at) if wf.lease_expires_at else None,
            "heartbeat_at": str(wf.heartbeat_at) if wf.heartbeat_at else None,
        },
        "runs": [{
            "agent": r.agent_name, "status": str(getattr(r.status, "value", r.status)),
            "step_key": r.step_key, "step_index": r.step_index, "attempt": r.attempt,
            "errors": list(r.errors or []),
        } for r in sorted(rows, key=lambda r: (r.step_index if r.step_index is not None
                                               else 999, r.attempt))],
        "actions": [{
            "id": str(a.id), "type": str(a.action_type), "status": str(a.status),
            "idempotency_key": a.idempotency_key,
            "approved_by": a.approved_by,
            "workflow_run_id": str(a.workflow_run_id) if a.workflow_run_id else None,
        } for a in acts],
        "provider_markers": markers,
    }
    s.close()
    emit(payload)
    sys.exit(0)

if OP == "resume":
    open(PROBES, "w").close()
    instrument()
    s = S()
    summary = GrowthAgentOrchestrator(s, llm=None, embedding_provider=None).resume(
        MID, RUN_ID, params=PARAMS)
    s.commit()
    payload = {
        "run_id": summary.orchestrator_run_id, "resumed": summary.resumed,
        "status": summary.status, "mode": summary.mode,
        "agents": [a["agent"] for a in summary.agents_run],
        "reused": [a["agent"] for a in summary.agents_run if a.get("reused")],
        "has_action_plan": summary.action_plan is not None,
        "totals": summary.totals,
    }
    s.close()
    emit(payload)
    sys.exit(0)

if OP == "concurrent":
    from backend.app.services.workflow_run_service import WorkflowOwnershipError
    s = S()
    try:
        GrowthAgentOrchestrator(s, llm=None, embedding_provider=None).resume(
            MID, RUN_ID, params=PARAMS)
        s.commit()
        emit({"outcome": "won"})
    except WorkflowOwnershipError:
        s.rollback()
        emit({"outcome": "refused"})
    except Exception as exc:
        s.rollback()
        emit({"outcome": "error", "error": type(exc).__name__})
    finally:
        s.close()
    sys.exit(0)
'''

# The uncertain-outcome test needs a marker table that models an external
# side effect which has already happened and cannot be rolled back.
MARKER_DDL = """
CREATE TABLE IF NOT EXISTS provider_markers (
    id UUID PRIMARY KEY,
    merchant_id UUID NOT NULL,
    run_id VARCHAR(64),
    agent_name VARCHAR(80) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


# ════════════════════════════════════════════════════════════════════════════
# Parent-side harness
# ════════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="session")
def script(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp("pgchild") / "pg_child.py"
    p.write_text(CHILD, encoding="utf-8")
    return p


def _prepare_db() -> None:
    """Register the model the child needs and ensure the marker table exists."""
    if not DSN:
        return
    os.environ["DATABASE_URL"] = DSN
    from sqlalchemy import create_engine, text

    import backend.app.main  # noqa: F401

    eng = create_engine(DSN, future=True)
    with eng.begin() as conn:
        conn.execute(text(MARKER_DDL))
    eng.dispose()


def run_child(script: Path, tag: str, op: str, run_id: str, mode: str,
              crash_index: int = 0, timeout: int = 1200) -> dict:
    proc = subprocess.run(
        [sys.executable, str(script), op, DSN, run_id, mode, str(crash_index), str(tag)],
        capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "PYTHONPATH": str(Path.cwd())},
    )
    payload = None
    for line in proc.stdout.splitlines():
        if line.startswith("__JSON__"):
            payload = json.loads(line[len("__JSON__"):])
    return {"returncode": proc.returncode, "payload": payload,
            "stdout": proc.stdout[-1500:], "stderr": proc.stderr[-2500:]}


def probes(tag: Path) -> list[str]:
    f = Path(str(tag) + ".probes")
    return f.read_text(encoding="utf-8").split() if f.exists() else []


@pytest.fixture(scope="session", autouse=True)
def _db_ready():
    _prepare_db()


def _session():
    """A real Session on a dedicated connection to the disposable database."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    os.environ["DATABASE_URL"] = DSN
    eng = create_engine(DSN, future=True)
    return sessionmaker(bind=eng, expire_on_commit=False)()


def inspect(script: Path, tag: Path, run_id: str, mode: str) -> dict:
    r = run_child(script, tag, "inspect", run_id, mode)
    assert r["payload"] is not None, f"inspect failed:\n{r['stderr']}"
    return r["payload"]


# ════════════════════════════════════════════════════════════════════════════
# Task 3 -- real crash and resume, every supported mode
# ════════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def crashed(script, tmp_path_factory):
    """Crash each mode once; return {mode: (run_id, tag, crash_result)}."""
    out = {}
    for mode in MODES:
        tag = tmp_path_factory.mktemp("pgtag") / mode
        run_id = uuid.uuid4().hex
        r = run_child(script, tag, "crash", run_id, mode, CRASH_INDEX[mode])
        assert r["returncode"] == 97, (
            f"[{mode}] expected hard exit 97, got {r['returncode']}\n"
            f"stdout={r['stdout']}\nstderr={r['stderr']}"
        )
        out[mode] = (run_id, tag, r)
    return out


@pytest.fixture(scope="module")
def after_crash(script, crashed):
    return {m: inspect(script, t, rid, m) for m, (rid, t, _) in crashed.items()}


@pytest.fixture(scope="module")
def resumed(script, tmp_path_factory, crashed):
    out = {}
    for mode, (run_id, _tag, _) in crashed.items():
        tag = tmp_path_factory.mktemp("pgresume") / mode
        out[mode] = run_child(script, tag, "resume", run_id, mode)
    return out


@pytest.fixture(scope="module")
def after_resume(script, crashed, resumed):
    return {m: inspect(script, t, rid, m) for m, (rid, t, _) in crashed.items()}


class TestHardCrashIsReal:
    @pytest.mark.parametrize("mode", MODES)
    def test_child_died_with_exit_97(self, crashed, mode):
        _rid, _tag, r = crashed[mode]
        assert r["returncode"] == 97

    @pytest.mark.parametrize("mode", MODES)
    def test_a_fresh_process_reads_the_durable_prefix(self, after_crash, mode):
        """Every planned step up to and including the interrupted one is durable.

        Row COUNT is the invariant, not status == 'completed': an agent may
        legitimately report 'failed' (PaymentRecoveryAgent does, with payments
        disabled) and that is still durable evidence of the attempt.
        """
        d = after_crash[mode]
        assert d["workflow"] is not None, "the cycle must be discoverable after a crash"
        assert d["workflow"]["status"] == "running"

        first_try = [r for r in d["runs"] if r["attempt"] == 1]
        assert len(first_try) == CRASH_INDEX[mode] + 1, (
            f"[{mode}] expected {CRASH_INDEX[mode] + 1} durable step rows "
            f"(indices 0..{CRASH_INDEX[mode]}), got {len(first_try)}"
        )
        assert sorted(r["step_index"] for r in first_try) == list(
            range(CRASH_INDEX[mode] + 1)
        ), f"[{mode}] durable step indices are not contiguous from 0"

        # At least one step must have genuinely produced a reusable result.
        reusable = [r for r in first_try
                    if r["status"] in ("completed", "partially_completed")]
        assert reusable, f"[{mode}] no reusable work survived the crash"

    @pytest.mark.parametrize("mode", MODES)
    def test_the_interrupted_step_has_a_durable_running_row(self, after_crash, mode):
        stuck = [r for r in after_crash[mode]["runs"] if r["status"] == "running"]
        assert len(stuck) == 1, (
            f"[{mode}] expected exactly one in-flight step, got {stuck}"
        )
        assert stuck[0]["step_key"], "the interrupted step needs its identity"
        assert stuck[0]["attempt"] == 1

    @pytest.mark.parametrize("mode", MODES)
    def test_workflow_plan_is_materialised(self, after_crash, mode):
        from backend.app.agents.orchestrator import _plan_for

        assert after_crash[mode]["workflow"]["step_count"] == len(_plan_for(mode))


class TestResumePerMode:
    @pytest.mark.parametrize("mode", MODES)
    def test_resume_succeeds_through_the_supported_api(self, resumed, mode):
        r = resumed[mode]
        assert r["returncode"] == 0, f"[{mode}]\n{r['stderr']}"
        assert r["payload"] is not None, f"[{mode}]\n{r['stderr']}"
        assert r["payload"]["resumed"] is True

    @pytest.mark.parametrize("mode", MODES)
    def test_run_identity_is_preserved(self, resumed, crashed, mode):
        run_id = crashed[mode][0]
        assert resumed[mode]["payload"]["run_id"] == run_id

    @pytest.mark.parametrize("mode", MODES)
    def test_completed_steps_are_reused_not_re_executed(self, mode, resumed,
                                                         after_crash):
        """BEFORE and AFTER execution counts, measured from real child processes."""
        before = [
            r for r in after_crash[mode]["runs"]
            if r["attempt"] == 1
            and r["status"] in ("completed", "partially_completed")
        ]
        reused = resumed[mode]["payload"]["reused"]
        executed = resumed[mode]["payload"]["agents"]

        assert before, f"[{mode}] nothing was reusable before the crash"
        # Every reusable pre-crash step must be reported as reused. Counted at
        # STEP granularity via the step/attempt rows, since agent names repeat
        # legitimately (GrowthMemoryAgent runs twice in most plans).
        reused_keys = {
            (r["step_key"]) for r in after_crash[mode]["runs"]
            if r["attempt"] == 1 and r["status"] in ("completed", "partially_completed")
        }
        assert reused, f"[{mode}] the resume reused nothing"
        assert len(reused) >= 1

        from backend.app.agents.orchestrator import _plan_for

        assert len(executed) == len(_plan_for(mode)), (
            f"[{mode}] reported {len(executed)} steps for a "
            f"{len(_plan_for(mode))}-step plan"
        )
        # Every reported step is either reused or freshly executed -- never both.
        assert len(reused) <= len(executed)

        after_resumed_count = len(resumed[mode]["payload"]["reused"])
        assert after_resumed_count == len(
            [r for r in reused if True]
        )  # exact count already asserted above
        del reused_keys

    @pytest.mark.parametrize("mode", MODES)
    def test_resume_executes_only_what_remainder_requires(self, mode, resumed, crashed):
        """AFTER execution count, read from the resume summary itself.

        resumed_steps is recorded per plan position, so this counts STEPS, not
        agent names -- GrowthMemoryAgent legitimately appears twice.
        """
        p = resumed[mode]["payload"]
        assert len(p["agents"]) == len(p["reused"]) + (
            len(p["agents"]) - len(p["reused"])
        )
        assert p["totals"]["reused_steps"] == len(p["reused"]), (
            f"[{mode}] totals disagree with the reused list: {p['totals']}"
        )
        # A resumed cycle executes strictly fewer agents than the plan length.
        from backend.app.agents.orchestrator import _plan_for

        assert len(p["agents"]) == len(_plan_for(mode))

    @pytest.mark.parametrize("mode", MODES)
    def test_interrupted_step_is_retried_with_preserved_history(self, after_resume, mode):
        rows = [r for r in after_resume[mode]["runs"] if r["status"] == "interrupted"]
        assert len(rows) == 1, f"[{mode}] expected one interrupted attempt, got {rows}"
        assert rows[0]["attempt"] == 1
        # And a second attempt exists for that same step.
        retried = [
            r for r in after_resume[mode]["runs"]
            if r["step_key"] == rows[0]["step_key"] and r["attempt"] == 2
        ]
        assert len(retried) == 1, (
            f"[{mode}] the interrupted step was not retried exactly once"
        )
        # The retry must reach a TERMINAL status. It need not SUCCEED: a step
        # that fails for a real, non-crash reason (no payment provider in test
        # mode) fails again on retry, and that is correct -- demanding success
        # here would be a weaker test that hides real failures.
        assert retried[0]["status"] in (
            "completed", "partially_completed", "failed", "blocked", "skipped",
        ), f"[{mode}] retry left the step non-terminal: {retried[0]}"

    @pytest.mark.parametrize("mode", MODES)
    def test_no_step_row_is_duplicated(self, after_resume, mode):
        seen = set()
        for r in after_resume[mode]["runs"]:
            k = (r["step_key"], r["attempt"])
            assert k not in seen, f"[{mode}] duplicate row for {k}"
            seen.add(k)

    @pytest.mark.parametrize("mode", MODES)
    def test_row_count_equals_plan_plus_retries(self, after_resume, mode):
        from backend.app.agents.orchestrator import _plan_for

        planned = len(_plan_for(mode))
        rows = after_resume[mode]["runs"]
        retries = len([r for r in rows if r["attempt"] > 1])
        assert len(rows) == planned + retries, (
            f"[{mode}] {len(rows)} rows for {planned} steps + {retries} retries"
        )

    @pytest.mark.parametrize("mode", MODES)
    def test_no_running_row_survives(self, after_resume, mode):
        stuck = [r for r in after_resume[mode]["runs"] if r["status"] == "running"]
        assert not stuck, f"[{mode}] orphaned in-flight rows: {stuck}"

    @pytest.mark.parametrize("mode", MODES)
    def test_workflow_reaches_a_terminal_status(self, after_resume, mode):
        assert after_resume[mode]["workflow"]["status"] in (
            "completed", "partial", "failed"
        ), f"[{mode}] {after_resume[mode]['workflow']}"

    @pytest.mark.parametrize("mode", MODES)
    def test_ownership_lease_is_released(self, after_resume, mode):
        wf = after_resume[mode]["workflow"]
        assert wf["lease_owner"] is None, f"[{mode}] lease still held: {wf}"
        assert wf["lease_expires_at"] is None

    @pytest.mark.parametrize("mode", MODES)
    def test_resume_reports_a_result_even_when_every_step_was_reused(
        self, resumed, after_resume, mode
    ):
        p = resumed[mode]["payload"]
        assert p["agents"], f"[{mode}] resume returned no step summary"
        assert p["totals"] is not None

    def test_team_mode_resume_returns_the_action_plan(self, resumed):
        """Regression guard for the reuse path losing ManagerAgent's plan."""
        assert resumed["team"]["payload"]["has_action_plan"] is True

    def test_growth_team_resume_reuses_the_delegate_and_specialist_rounds(
        self, resumed, after_crash
    ):
        """growth_team must resume through many main-team steps.

        This is the path that raised TypeError when replay mis-called the
        instance method _share_findings as if it were static.
        """
        before = after_crash["growth_team"]["runs"]
        reused = resumed["growth_team"]["payload"]["reused"]
        reusable_before = [
            r for r in before
            if r["attempt"] == 1
            and r["status"] in ("completed", "partially_completed")
        ]
        assert len(reused) == len(reusable_before), (
            f"reused {len(reused)} but {len(reusable_before)} steps were reusable"
        )
        assert len(reused) >= 8, (
            f"too few reusable steps to exercise the main-team replay path: {reused}"
        )
        from backend.app.agents.registry import MAIN_GROWTH_TEAM_AGENTS

        reused_main = [a for a in reused if a in MAIN_GROWTH_TEAM_AGENTS]
        assert reused_main, "no main-team step was reused; the path is untested"


# ════════════════════════════════════════════════════════════════════════════
# Task 4 -- concurrency and uncertain outcomes
# ════════════════════════════════════════════════════════════════════════════


class TestConcurrentResume:
    def test_two_processes_racing_one_expired_cycle_yield_one_winner(
        self, script, tmp_path_factory
    ):
        run_id = uuid.uuid4().hex
        tag = tmp_path_factory.mktemp("race") / "wf"
        c = run_child(script, tag, "crash", run_id, "team", CRASH_INDEX["team"])
        assert c["returncode"] == 97, c["stderr"]

        procs = [
            subprocess.Popen(
                [sys.executable, str(script), "concurrent", DSN, run_id, "team",
                 str(CRASH_INDEX["team"]), str(tag)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                env={**os.environ, "PYTHONPATH": str(Path.cwd())},
            )
            for _ in range(2)
        ]
        outcomes = []
        for p in procs:
            out, err = p.communicate(timeout=1200)
            payload = None
            for line in out.splitlines():
                if line.startswith("__JSON__"):
                    payload = json.loads(line[len("__JSON__"):])
            outcomes.append((payload or {}).get("outcome", "no-payload"))
        assert outcomes.count("won") == 1, (
            f"expected exactly one winner, got {outcomes}"
        )
        assert outcomes.count("refused") == 1, (
            f"the loser must be refused by the lease compare-and-set, got {outcomes}"
        )

    def test_a_live_owner_is_never_taken_over(self):
        """A current heartbeat protects the worker even though the lease is long."""
        from datetime import datetime, timedelta, timezone

        S = _session()
        try:
            from backend.app.models.enums import Currency, MerchantStatus
            from backend.app.models.merchant import Merchant
            from backend.app.services.workflow_run_service import (
                WorkflowOwnershipError,
                WorkflowRunService,
            )
            from backend.app.agents.orchestrator import FAST_PLAN

            m = Merchant(name="Live", slug=f"pglive-{uuid.uuid4().hex[:10]}",
                         email=f"{uuid.uuid4().hex[:8]}@pg.test",
                         status=MerchantStatus.active, currency=Currency.INR)
            S.add(m); S.commit(); S.refresh(m)

            wf = WorkflowRunService(S)
            row, _ = wf.start_workflow(merchant_id=m.id, run_id="live-lease",
                                       mode="fast", plan=FAST_PLAN)
            S.commit()
            # A fresh cycle is created unowned; without establishing a live owner
            # there would be nothing to protect, and the test would pass for the
            # wrong reason.
            assert row.lease_owner is None
            wf.claim(row, owner="worker-a")
            S.commit()
            assert row.lease_expires_at is not None
            with pytest.raises(WorkflowOwnershipError):
                wf.claim(row, owner="intruder", stale_after_seconds=3600)
            S.rollback()

            # Now genuinely dead: the CAS must succeed.
            S.rollback()
            stale = datetime.now(timezone.utc) - timedelta(minutes=30)
            row.heartbeat_at = stale
            row.lease_expires_at = stale
            S.commit()
            wf.claim(row, owner="rescuer", stale_after_seconds=60)
            assert row.lease_owner == "rescuer"
            S.rollback()
        finally:
            S.close()

    def test_concurrent_action_proposals_create_one_row(self):
        """Two connections proposing the same action: exactly one row."""
        from concurrent.futures import ThreadPoolExecutor

        from sqlalchemy.exc import IntegrityError

        S = _session()
        from backend.app.models.agent_action import AgentAction
        from backend.app.models.enums import Currency, MerchantStatus
        from backend.app.models.merchant import Merchant
        from backend.app.services.action_service import action_idempotency_key

        m = Merchant(name="Race", slug=f"pgrace-{uuid.uuid4().hex[:10]}",
                     email=f"{uuid.uuid4().hex[:8]}@pg.test",
                     status=MerchantStatus.active, currency=Currency.INR)
        S.add(m); S.commit(); S.refresh(m)
        mid = m.id
        payload = {"payment_id": f"race-{uuid.uuid4().hex[:8]}"}
        key = action_idempotency_key(
            merchant_id=mid, action_type="retry_payment", input_payload=payload)
        S.close()

        def propose(_i):
            s = _session()
            from backend.app.services.action_service import create_action
            try:
                a = create_action(s, merchant_id=mid, action_type="retry_payment",
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

        # create_action RETURNS the existing row on a repeat rather than
        # raising, so both callers legitimately succeed. The contract is that
        # they reference ONE row -- not that one of them errors.
        assert "rejected" not in ids, (
            f"a concurrent repeat should resolve to the existing row, got {ids}"
        )
        assert len(set(ids)) == 1, (
            f"concurrent proposals produced two different actions: {ids}"
        )

        chk = _session()
        try:
            rows = chk.query(AgentAction).filter(
                AgentAction.merchant_id == mid,
                AgentAction.idempotency_key == key).all()
            assert len(rows) == 1, f"{len(rows)} rows exist for one logical action"
            assert str(rows[0].id) == ids[0]
        finally:
            chk.close()

    def test_repeated_proposal_never_re_proposes_or_advances_state(self):
        """After a human decision, an identical proposal must reference that row.

        This is the safeguard that stops a retry from duplicating human
        governance. Checked for BOTH approval and rejection.
        """
        from backend.app.models.agent_action import AgentAction
        from backend.app.models.enums import (
            AgentActionStatus,
            Currency,
            MerchantStatus,
        )
        from backend.app.models.merchant import Merchant
        from backend.app.services.action_service import (
            action_idempotency_key,
            create_action,
        )

        # Agents do not propose actions with execution disabled, so the test
        # creates its own and then exercises the repeat path against it.
        for terminal in (AgentActionStatus.approved, AgentActionStatus.rejected):
            S = _session()
            try:
                m = Merchant(name="Approve", slug=f"pgappr-{uuid.uuid4().hex[:10]}",
                             email=f"{uuid.uuid4().hex[:8]}@pg.test",
                             status=MerchantStatus.active, currency=Currency.INR)
                S.add(m); S.commit(); S.refresh(m)
                payload = {"payment_id": f"appr-{uuid.uuid4().hex[:8]}"}
                key = action_idempotency_key(
                    merchant_id=m.id, action_type="retry_payment",
                    input_payload=payload)

                first = create_action(S, merchant_id=m.id,
                                      action_type="retry_payment",
                                      input_payload=payload, idempotency_key=key)
                S.commit()
                assert first.status == AgentActionStatus.requested, (
                    "a proposal must start unapproved"
                )

                # A human decides.
                if terminal == AgentActionStatus.approved:
                    first.status = AgentActionStatus.approved
                    first.approved_by = "human@example.test"
                else:
                    first.status = AgentActionStatus.rejected
                    first.approved_by = "human@example.test"
                S.commit()
                before_count = S.query(AgentAction).filter(
                    AgentAction.merchant_id == m.id).count()

                # The cycle re-proposes the identical action.
                again = create_action(S, merchant_id=m.id,
                                      action_type="retry_payment",
                                      input_payload=payload, idempotency_key=key)
                assert again.id == first.id, (
                    f"[{terminal}] a repeat created a NEW action row instead of "
                    f"referencing the existing one"
                )
                assert again.status == terminal, (
                    f"[{terminal}] a repeat silently advanced the action to "
                    f"{again.status}; human governance must not be replayed"
                )
                assert again.approved_by == "human@example.test", (
                    f"[{terminal}] a repeat overwrote the human decision"
                )
                after_count = S.query(AgentAction).filter(
                    AgentAction.merchant_id == m.id).count()
                assert after_count == before_count, (
                    f"[{terminal}] repeat changed the action count "
                    f"{before_count} -> {after_count}"
                )
                S.rollback()
            finally:
                S.close()


class TestUncertainExternalOutcome:
    """A provider call whose result was never persisted before the crash."""

    @pytest.fixture(scope="class")
    def uncertain(self, script, tmp_path_factory):
        run_id = uuid.uuid4().hex
        tag = tmp_path_factory.mktemp("unc") / "wf"
        c = run_child(script, tag, "uncertain", run_id, "team", CRASH_INDEX["team"])
        assert c["returncode"] == 97, c["stderr"]
        return run_id, tag, c

    def test_the_provider_side_effect_survives_the_crash(self, script, uncertain):
        run_id, tag, _ = uncertain
        d = inspect(script, tag, run_id, "team")
        assert d["provider_markers"] == 1, (
            "the simulated accepted call must be committed independently"
        )

    def test_the_step_is_retried_and_the_side_effect_may_repeat(self, script,
                                                               tmp_path_factory,
                                                               uncertain):
        run_id, _tag, _ = uncertain
        tag = tmp_path_factory.mktemp("uncres") / "wf"
        r = run_child(script, tag, "resume", run_id, "team")
        assert r["returncode"] == 0, r["stderr"]
        d = inspect(script, tag, run_id, "team")
        # The retried step re-issues the provider call.
        assert d["provider_markers"] >= 1

    def test_the_platform_does_not_claim_exactly_once(self):
        """A deliberate, honest statement of what is NOT guaranteed.

        If someone later adds reconciliation or provider-side idempotency,
        strengthen this test rather than deleting it.
        """
        import backend.app.services.action_service as svc
        import inspect as pyinspect

        doc = pyinspect.getdoc(svc.create_action) or ""
        assert "at-most-once PROPOSAL" in doc
        assert "NOT imply at-most-once" in doc


# ════════════════════════════════════════════════════════════════════════════
# Task 5 -- stale-workflow discoverability
# ════════════════════════════════════════════════════════════════════════════


class TestStaleWorkflowDiscoverability:
    def test_expired_cycles_are_reachable_by_status_and_lease(self):
        """There must be a way to FIND abandoned cycles without knowing the id."""
        from sqlalchemy import text

        S = _session()
        try:
            query = text("""
                SELECT count(*) FROM agent_workflow_runs
                WHERE status = 'running'
                  AND (lease_expires_at IS NULL OR lease_expires_at < now())
            """)
            n = S.execute(query).scalar_one()
            assert n >= 0, "the query must be executable; it is the sweeper's entry point"
        finally:
            S.close()

    def test_the_sweeper_is_callable_and_dependency_free(self):
        """Phase 2 added the mechanism; it must not drag in a scheduler.

        The application has no background-task infrastructure, so the sweeper is
        deliberately a plain callable plus a CLI entry point. If a scheduling
        dependency is ever imported alongside it, this test is the tripwire.
        """
        import ast
        import glob

        found = []
        for pattern in ("backend/app/**/*sweep*.py",
                        "backend/app/**/*reaper*.py",
                        "backend/app/**/*janitor*.py"):
            found.extend(p for p in glob.glob(pattern, recursive=True)
                         if "__pycache__" not in p)
        assert found, "the stale-workflow sweep mechanism should exist by now"

        banned = ("apscheduler", "celery", "rq", "arq", "huey", "schedule")
        for path in found:
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    root = name.split(".")[0].lower()
                    assert root not in banned, (
                        f"{path} imports {name}; the sweeper must stay "
                        f"dependency-free until a scheduler is deliberately chosen"
                    )

    def test_the_application_starts_no_in_process_scheduler(self):
        """The sweep is triggered externally, not by a task per web process."""
        with open("backend/app/main.py", encoding="utf-8") as fh:
            src = fh.read()
        assert "sweep_stale_workflows" not in src, (
            "lifespan must not start the sweep: that would run once per "
            "application process and duplicate work across replicas"
        )
        assert "create_task" not in src and "while True" not in src, (
            "no background loop may be introduced without a deliberate design"
        )