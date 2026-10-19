"""
Workflow lifecycle service — durable cycles, step identity and ownership.

This is the persistence layer that makes a multi-agent cycle resumable. It
owns four things and nothing else:

1. **Materialising a plan.** The orchestrator's plans are module-level tuples.
   They are frozen into a concrete, ordered step list and stored on the
   workflow row, so a resume replays *the steps that actually ran* rather than
   whatever the code says today.

2. **Step identity.** ``step_key`` is a stable hash of
   ``(mode, index, agent_name, phase)``. It is what makes legitimate
   repetition safe -- MarketingAgent runs three times in ``growth_team`` and
   each occurrence gets a different key -- while a replay of the same logical
   step collides and is rejected by the database.

3. **Plan compatibility.** A fingerprint over the step list means a resume can
   refuse to graft new-plan results onto old-plan history instead of silently
   producing a nonsense synthesis.

4. **Single-writer ownership.** ``claim`` is a compare-and-set UPDATE: it only
   wins when no live lease exists. A healthy worker is never taken over, and
   two concurrent resumes cannot both own the cycle.

Nothing here executes an agent, approves an action, or bypasses a guardrail.
"""
from __future__ import annotations

import enum
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Iterator, Sequence

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from backend.app.models.agent_run import AgentRun
from backend.app.models.agent_workflow import AgentWorkflowRun
from backend.app.models.enums import AgentRunStatus, WorkflowStatus

log = logging.getLogger(__name__)

#: How long a worker's ownership lease survives without a heartbeat. Chosen to
#: exceed any realistic single-agent step so a slow-but-healthy agent is never
#: declared dead, while still bounding how long a genuinely dead cycle stays
#: locked before it can be recovered.
DEFAULT_LEASE_SECONDS = 900

#: How long a run may go without a heartbeat before it stops counting as live.
#: Comfortably longer than the lease so a merely slow agent is never misreported
#: as dead. Used by BOTH halves of the staleness decision -- the read side
#: (``active_run_report``) and the write side (``reconcile_orphan_runs``) -- so
#: they cannot disagree about what counts as abandoned.
DEFAULT_STALE_AFTER_SECONDS = 900

#: Execution engines that may own a workflow cycle. Persisted on the row at
#: creation so recovery continues the cycle on the engine that started it.
#: ``None`` is reserved for rows that predate engine provenance and is treated
#: as the historical legacy path; anything else is refused, never guessed.
EXECUTION_ENGINE_LANGGRAPH = "langgraph"
EXECUTION_ENGINE_LEGACY = "legacy"
KNOWN_EXECUTION_ENGINES = frozenset(
    {EXECUTION_ENGINE_LANGGRAPH, EXECUTION_ENGINE_LEGACY}
)


class WorkflowNotFound(LookupError):
    """No such workflow for this merchant (indistinguishable from another's)."""


class WorkflowNotResumable(RuntimeError):
    """The workflow exists but policy forbids resuming it right now."""


class PlanIncompatible(RuntimeError):
    """The stored plan does not match the plan requested for recovery."""


class WorkflowOwnershipError(RuntimeError):
    """Another live worker owns this cycle."""


class StaleLeaseError(RuntimeError):
    """
    A worker attempted a protected write after losing its lease.

    This is the fencing token doing its job. The worker was descheduled past its
    lease expiry, another worker legitimately claimed the cycle and bumped the
    generation, and now the first worker is trying to write. Accepting the write
    would corrupt the newer owner's state.

    Deliberately distinct from ``WorkflowOwnershipError``: that one means "I
    could not take ownership", this one means "I had ownership and lost it".
    The caller must abandon the cycle, not retry it.
    """


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


#: The workflow currently executing in this process/thread.
#:
#: Eight call sites invoke ``create_action`` directly rather than through the
#: agent base class, so threading an explicit ``workflow_run_id`` through all
#: of them would be invasive and easy to forget on the ninth. An ambient
#: context set by the orchestrator for the duration of a step lets
#: ``action_service.create_action`` scope idempotency to the right cycle
#: WITHOUT any agent knowing about it.
#:
#: It is a ContextVar rather than a module global so concurrent workers,
#: threads and tests cannot observe each other's cycle.
_CURRENT_WORKFLOW: ContextVar[uuid.UUID | None] = ContextVar(
    "razorgrowth_current_workflow", default=None
)


def current_workflow_id() -> uuid.UUID | None:
    """The workflow id in scope, or None outside any workflow."""
    return _CURRENT_WORKFLOW.get()


@contextmanager
def current_workflow(workflow_id: uuid.UUID | None) -> Iterator[None]:
    """Scope idempotency to one workflow for the duration of a block."""
    token = _CURRENT_WORKFLOW.set(workflow_id)
    try:
        yield
    finally:
        _CURRENT_WORKFLOW.reset(token)


def step_key(mode: str, index: int, agent_name: str, phase: str | None = None) -> str:
    """
    Stable identity for one step of one plan.

    Derived from the plan POSITION, never from the agent alone. Two occurrences
    of the same agent in one plan therefore differ, while the same position
    yields the same key in every process and on every restart.
    """
    raw = f"{mode}|{index}|{agent_name}|{phase or ''}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"{mode}:{index:03d}:{agent_name}:{phase or '-'}:{digest}"


def materialise_plan(
    mode: str, plan: Sequence[tuple[str, dict[str, Any]]]
) -> list[dict[str, Any]]:
    """Freeze a plan tuple into a concrete, ordered, serialisable step list."""
    steps: list[dict[str, Any]] = []
    for index, (agent_name, step_params) in enumerate(plan):
        phase = step_params.get("phase") if isinstance(step_params, dict) else None
        steps.append(
            {
                "step_index": index,
                "step_key": step_key(mode, index, agent_name, phase),
                "agent_name": agent_name,
                "phase": phase,
                "params": dict(step_params) if isinstance(step_params, dict) else {},
            }
        )
    return steps


def plan_fingerprint(steps: Iterable[dict[str, Any]]) -> str:
    """Hash of the step list, used to detect plan drift before a resume."""
    canonical = [
        [s["step_index"], s["step_key"], s["agent_name"], s["phase"]]
        for s in sorted(steps, key=lambda s: s["step_index"])
    ]
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _assert_generation(
    state: Session, *, workflow_id: uuid.UUID | None, expected: int | None
) -> None:
    """
    Reject a protected write from a worker whose lease has been superseded.

    Atomicity is the whole point, so the check is not a bare SELECT. The row is
    locked FOR UPDATE, which holds that lock until the caller's transaction
    commits. A concurrent takeover therefore cannot slip between the check and
    the write that follows it -- it blocks on the lock, and by the time it
    re-evaluates its own predicate the generation has already been consumed.

    SQLite does not implement SELECT ... FOR UPDATE. It also does not need it:
    the whole database has a single writer, so a check and the write that
    follows it inside one transaction are already serialised. That is a genuine
    difference from PostgreSQL and is NOT treated as equivalent -- see the
    module notes in the Phase 2 report.

    ``expected`` of None means "unfenced", which is only used by legacy callers
    that predate fencing. Production paths always pass a generation.
    """
    if workflow_id is None or expected is None:
        return
    # Generation 0 is the "never claimed" sentinel. Every legitimate writer
    # claims first (claim() returns >= 1), so a caller presenting 0 is a worker
    # that never owned this cycle and must be refused -- otherwise a fresh
    # cycle, whose stored generation is also 0, would let it through.
    if int(expected) <= 0:
        raise StaleLeaseError(
            f"workflow {workflow_id}: write refused, generation {expected} is the "
            f"never-claimed sentinel and carries no ownership"
        )
    dialect = state.get_bind().dialect.name
    stmt = select(AgentWorkflowRun.lease_generation).where(
        AgentWorkflowRun.id == workflow_id
    )
    if dialect != "sqlite":
        stmt = stmt.with_for_update()
    current = state.execute(stmt).scalar_one_or_none()
    if current is None:
        raise StaleLeaseError(
            f"workflow {workflow_id} disappeared; refusing a fenced write"
        )
    if int(current) != int(expected):
        raise StaleLeaseError(
            f"workflow {workflow_id}: write rejected, this worker holds "
            f"generation {expected} but the stored generation is {current}"
        )


# ── reuse policy ───────────────────────────────────────────────────────────

class ReuseVerdict(str, enum.Enum):
    """
    What recovery should do with a step that already has a persisted attempt.

    ``REUSE``       replay the persisted result downstream; do not re-execute.
    ``RETRY``       controlled re-execution; nothing suggests an external effect
                    happened, so re-running is safe.
    ``RECONCILE``   do NOT reuse and do NOT retry: an external effect may have
                    occurred without a recorded outcome, so a human or a
                    reconciler must decide. Repeating it blindly is exactly the
                    failure mode this policy exists to prevent.
    """

    REUSE = "reuse"
    RETRY = "retry"
    RECONCILE = "reconcile"


@dataclass(frozen=True)
class ReuseDecision:
    verdict: ReuseVerdict
    reason: str
    evidence: tuple[str, ...] = ()

    @property
    def reusable(self) -> bool:
        return self.verdict is ReuseVerdict.REUSE


#: Action states that mean an external effect may already have started.
#:
#: ``requested`` is deliberately NOT here. A proposal that never left the
#: approval queue has caused no external effect, and proposals are already
#: deduplicated by ``action_idempotency_key``, so replaying the producing step
#: cannot create a second proposal.
_UNCERTAIN_ACTION_STATES = ("approved", "executing")


def _has_uncertain_action(
    db: Session, *, workflow_id: uuid.UUID, merchant_id: uuid.UUID | None
) -> str | None:
    """
    Return evidence if any action from this cycle may have executed already.

    This is the crux of the partial-result policy. "The step said
    ``partially_completed``" is not evidence that nothing happened externally;
    the ACTIONS TABLE is. An action that reached ``approved`` or ``executing``
    may already have hit a provider, so the step must not simply be retried.
    """
    from backend.app.models.agent_action import AgentAction

    stmt = select(AgentAction.id).where(
        AgentAction.workflow_run_id == workflow_id,
        AgentAction.status.in_(_UNCERTAIN_ACTION_STATES),
    )
    if merchant_id is not None:
        stmt = stmt.where(AgentAction.merchant_id == merchant_id)
    found = db.scalars(stmt.limit(1)).first()
    return f"action {found} is in a state where an external effect may have run" if found else None


def decide_reuse(
    db: Session, row: AgentRun, *, merchant_id: uuid.UUID | None = None
) -> ReuseDecision:
    """
    Decide what recovery should do with one persisted step attempt.

    The judgement is made on the PERSISTED evidence, never on optimism:

    ``completed``
        Reusable. The step ran to completion under a matching plan identity and
        its result is durable.

    ``partially_completed``
        NOT automatically reusable. Degraded-but-productive, but the run may
        have stopped part-way through an operation whose external effect is
        unknown. Three outcomes:

        1. an action from this cycle is ``approved``/``executing``
           -> RECONCILE. An external effect may already have happened; neither
              replaying the partial result nor re-running the step is safe.
        2. no uncertain action AND a well-formed, non-empty ``output_summary``
           -> REUSE. The step's durable contribution is intact and its only
              outward-facing writes were proposals, which are idempotent.
        3. otherwise -> RETRY. No usable evidence that the step achieved
           anything, and no evidence of an external effect either, so a
           controlled retry carries no known risk.

    ``needs_reconciliation``
        RECONCILE. A previous recovery already found uncertain evidence.

    ``failed`` / ``blocked`` / ``skipped`` / ``interrupted`` / ``running``
        RETRY. Nothing reusable was recorded, and these states never imply an
        external effect was left in flight.
    """
    status = str(getattr(row.status, "value", row.status))
    key = row.step_key or row.agent_name

    if status == AgentRunStatus.needs_reconciliation.value:
        return ReuseDecision(
            ReuseVerdict.RECONCILE,
            f"step {key} was already flagged as needing reconciliation",
            ("prior reconciliation flag",),
        )

    if status == AgentRunStatus.completed.value:
        return ReuseDecision(
            ReuseVerdict.REUSE,
            f"step {key} completed durably under a matching plan identity",
            (f"status={status}", f"attempt={row.attempt}"),
        )

    if status == AgentRunStatus.partially_completed.value:
        uncertain = _has_uncertain_action(
            db, workflow_id=row.workflow_id, merchant_id=merchant_id
        )
        if uncertain:
            return ReuseDecision(
                ReuseVerdict.RECONCILE,
                f"step {key} is partial and {uncertain}",
                (f"status={status}", "uncertain action state"),
            )
        summary = row.output_summary
        if isinstance(summary, dict) and summary:
            return ReuseDecision(
                ReuseVerdict.REUSE,
                f"step {key} is partial but its persisted result is intact and "
                f"no action left the approval queue",
                (f"status={status}", f"output_keys={sorted(summary)[:5]}"),
            )
        if not isinstance(summary, dict):
            return ReuseDecision(
                ReuseVerdict.RETRY,
                f"step {key} is partial and its persisted result is malformed "
                f"({type(summary).__name__}); there is nothing safe to replay",
                (f"status={status}", f"output_type={type(summary).__name__}"),
            )
        return ReuseDecision(
            ReuseVerdict.RETRY,
            f"step {key} is partial and recorded no reusable output",
            (f"status={status}", "empty output"),
        )

    if status == AgentRunStatus.running.value:
        return ReuseDecision(
            ReuseVerdict.RECONCILE,
            f"step {key} is still recorded as running; it was interrupted by a "
            f"process exit and its outcome is unknown",
            (f"status={status}",),
        )

    return ReuseDecision(
        ReuseVerdict.RETRY,
        f"step {key} finished as {status}, which records no reusable result",
        (f"status={status}",),
    )


# ── stale workflow sweep ───────────────────────────────────────────────────

@dataclass
class SweepReport:
    """What one sweep pass did. Returned rather than only logged, so callers
    (a CLI, a test, a future scheduler) can assert on it."""

    scanned: int = 0
    reclaimed: list[str] = None  # type: ignore[assignment]
    steps_interrupted: dict[str, list[str]] = None  # type: ignore[assignment]
    skipped: int = 0
    #: Abandoned rows outside workflow tracking, closed by the same pass.
    orphans: "OrphanReconciliation | None" = None

    def __post_init__(self) -> None:
        if self.reclaimed is None:
            self.reclaimed = []
        if self.steps_interrupted is None:
            self.steps_interrupted = {}

    @property
    def reclaimed_count(self) -> int:
        return len(self.reclaimed)


@dataclass
class OrphanReconciliation:
    """Counts of abandoned rows closed out by a sweep pass."""

    agent_runs: int = 0
    product_agent_runs: int = 0
    marketing_agi_runs: int = 0

    @property
    def total(self) -> int:
        return self.agent_runs + self.product_agent_runs + self.marketing_agi_runs

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_runs": self.agent_runs,
            "product_agent_runs": self.product_agent_runs,
            "marketing_agi_runs": self.marketing_agi_runs,
            "total": self.total,
        }


#: Statuses that assert an in-flight process in the employee-agent run tables.
_IN_FLIGHT_EMPLOYEE_STATUSES = ("queued", "running")


def reconcile_orphan_runs(
    db: Session,
    *,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
    cutoff: datetime | None = None,
    reason: str = "reclaimed_by_stale_workflow_sweep",
) -> OrphanReconciliation:
    """
    Close out in-flight rows whose owning process is demonstrably gone.

    A row is only touched when it is BOTH marked in flight AND old enough that
    no live worker could still own it:

    * ``agent_runs`` needs no ``workflow_id`` to be stale (that IS the
      condition) and is judged on ``heartbeat_at`` falling back to
      ``started_at`` when no heartbeat was ever written.
    * the employee-agent tables are judged on ``updated_at``, which their own
      workers refresh as they progress.

    This is the write half of the staleness decision. The read half lives in
    ``active_run_report``, which is pure and never mutates -- a GET that repairs
    the database would be exactly the coupling this work removes.

    Every statement is a guarded compare-and-set bounded by the same cutoff, so
    the pass is idempotent and safe to run concurrently.

    ``stale_after_seconds`` is deliberately a real threshold rather than "older
    than now". A cutoff of ``now`` would close a row created a millisecond
    earlier, which is not abandoned at all -- it is a run that has only just
    started. Fifteen minutes matches the bound the read side
    (``active_run_report``) uses, so the two halves of the staleness decision
    cannot disagree.
    """
    cutoff = cutoff or (_utcnow() - timedelta(seconds=max(0, stale_after_seconds)))
    out = OrphanReconciliation()

    from backend.app.models.agent_run import AgentRun as _AgentRun

    # Untracked agent_run rows. heartbeat_at may be NULL for historical rows, so
    # COALESCE falls back to started_at; either being old means dead.
    result = db.execute(
        update(_AgentRun)
        .where(
            _AgentRun.workflow_id.is_(None),
            _AgentRun.status == AgentRunStatus.running.value,
            func.coalesce(_AgentRun.heartbeat_at, _AgentRun.started_at) < cutoff,
        )
        .values(
            status=AgentRunStatus.interrupted.value,
            completed_at=cutoff,
        )
        .execution_options(synchronize_session=False)
    )
    out.agent_runs = int(result.rowcount or 0)

    # Employee-agent run tables, judged on updated_at.
    for attr, label in (
        ("ProductAgentRun", "product_agent_runs"),
        ("MarketingAGIRun", "marketing_agi_runs"),
    ):
        try:
            import backend.app.models as _models

            model = getattr(_models, attr)
        except Exception:
            # The model is not registered in this deployment; skip rather than
            # fail the whole sweep.
            continue
        if "status" not in {c.name for c in model.__table__.columns}:
            continue
        res = db.execute(
            update(model)
            .where(
                model.status.in_(_IN_FLIGHT_EMPLOYEE_STATUSES),
                model.updated_at < cutoff,
            )
            .values(status="interrupted")
            .execution_options(synchronize_session=False)
        )
        if label == "product_agent_runs":
            out.product_agent_runs = int(res.rowcount or 0)
        else:
            out.marketing_agi_runs = int(res.rowcount or 0)

    db.commit()
    db.expire_all()
    if out.total:
        log.warning(
            "Reconciled %d abandoned in-flight row(s): %s",
            out.total, out.to_dict(),
        )
    return out


def sweep_stale_workflows(
    db: Session,
    *,
    now: datetime | None = None,
    grace_seconds: int = 0,
    max_batch: int = 100,
) -> SweepReport:
    """
    Reclaim cycles whose owner is gone, and mark their state accurately.

    A cycle is stale when it is still ``running`` AND its lease has expired (or
    was never taken). For each one this performs a single guarded UPDATE that

      * flips the cycle to ``interrupted``,
      * clears the dead owner's lease,
      * and **bumps ``lease_generation``**.

    That last part is what makes this safe rather than merely tidy: once the
    generation moves, the dead owner's in-flight writes are fenced out, so it
    cannot wake up and overwrite the state recorded here.

    Properties that matter, and why:

    * **Never touches a live owner.** The predicate requires the lease to have
      expired, so a worker that is genuinely running is left alone.
    * **Never touches a finished cycle.** ``status = 'running'`` is part of the
      predicate, so a cycle that completed while the sweep was running is
      unaffected.
    * **Idempotent.** After the first pass the cycle is no longer ``running``,
      so re-running finds nothing and changes nothing.
    * **Safe under concurrent sweeps.** Every transition is a compare-and-set
      whose ``rowcount`` decides the winner; two sweepers never both reclaim
      the same cycle.
    * **Tenant-safe.** Every statement is scoped by ``id`` taken from a filtered
      query, and steps are closed out through the existing per-workflow service
      method. No cross-tenant predicate is ever evaluated.

    This is a callable mechanism, deliberately not a scheduler. The application
    has no background-task infrastructure, and inventing one would be a larger
    and riskier change than the problem needs. See ``sweep_stale_workflows.py``
    for the (a)/(b)/(c) trigger designs and the recommendation.
    """
    cutoff = (now or _utcnow()) - timedelta(seconds=max(0, grace_seconds))
    report = SweepReport()

    candidates = db.scalars(
        select(AgentWorkflowRun.id)
        .where(
            AgentWorkflowRun.status == WorkflowStatus.running.value,
            (AgentWorkflowRun.lease_expires_at.is_(None))
            | (AgentWorkflowRun.lease_expires_at <= cutoff),
        )
        .limit(max_batch)
    ).all()
    report.scanned = len(candidates)

    for workflow_id in candidates:
        errors = [
            f"lease expired or never taken at {cutoff.isoformat()}; "
            f"reclaimed by the stale-workflow sweep"
        ]
        result = db.execute(
            update(AgentWorkflowRun)
            .where(
                AgentWorkflowRun.id == workflow_id,
                AgentWorkflowRun.status == WorkflowStatus.running.value,
                (AgentWorkflowRun.lease_expires_at.is_(None))
                | (AgentWorkflowRun.lease_expires_at <= cutoff),
            )
            .values(
                status=WorkflowStatus.interrupted.value,
                completed_at=cutoff,
                lease_owner=None,
                lease_expires_at=None,
                heartbeat_at=cutoff,
                lease_generation=AgentWorkflowRun.lease_generation + 1,
                errors=errors,
                updated_at=cutoff,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 0:
            # Live lease, already terminal, or another sweeper won the race.
            report.skipped += 1
            continue
        report.reclaimed.append(str(workflow_id))
        closed = WorkflowRunService(db).mark_interrupted_steps(
            workflow_id, reason="reclaimed_by_stale_workflow_sweep"
        )
        if closed:
            report.steps_interrupted[str(workflow_id)] = closed

    # The transitions above were bulk UPDATEs evaluated by the database, so any
    # already-loaded instance of a reclaimed cycle in this session still holds
    # the PRE-sweep status. Expiring is not optional tidiness: without it a
    # caller that immediately re-reads the cycle would be told it is still
    # `running` and could try to resume a cycle that has just been abandoned.
    db.commit()
    db.expire_all()
    report.orphans = reconcile_orphan_runs(
        db, stale_after_seconds=max(grace_seconds, DEFAULT_STALE_AFTER_SECONDS)
    )
    return report


class WorkflowRunService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── creation ────────────────────────────────────────────────────────

    def start_workflow(
        self,
        *,
        merchant_id: uuid.UUID,
        run_id: str,
        mode: str,
        plan: Sequence[tuple[str, dict[str, Any]]],
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        execution_engine: str | None = None,
    ) -> tuple[AgentWorkflowRun, bool]:
        """
        Create the cycle row, or return the existing one for this run id.

        Returns ``(workflow, created)``. The unique ``(merchant_id, run_id)``
        constraint is what makes "reuse this run id" mean "resume this cycle"
        rather than "start a parallel one".

        ``execution_engine`` records which executor owns the cycle. It is
        written ONLY when the row is created: provenance is immutable, so a
        caller cannot silently switch an existing cycle to another engine (that
        raises instead). Historical rows created before this column existed
        keep NULL and are recovered by the legacy path, preserving their
        behaviour.
        """
        if execution_engine is not None and execution_engine not in KNOWN_EXECUTION_ENGINES:
            raise ValueError(
                f"unknown execution engine {execution_engine!r}; expected one of "
                f"{sorted(KNOWN_EXECUTION_ENGINES)}"
            )
        existing = self.get_workflow(merchant_id=merchant_id, run_id=run_id)
        if existing is not None:
            if (
                execution_engine is not None
                and existing.execution_engine is not None
                and existing.execution_engine != execution_engine
            ):
                # Continuing a cycle under a different executor would violate
                # the single execution path the workflow was built on.
                raise WorkflowNotResumable(
                    f"workflow {run_id} was started by the "
                    f"{existing.execution_engine!r} engine; refusing to continue "
                    f"it with {execution_engine!r}"
                )
            return existing, False

        steps = materialise_plan(mode, plan)
        now = _utcnow()
        # Created UNOWNED. Every cycle -- including a brand new one -- must go
        # through claim(), so that every writer holds a fencing generation and
        # there is a single code path for ownership. ``lease_generation`` stays
        # at the 0 sentinel until then, and a worker that never claimed can
        # therefore never satisfy a fencing check.
        row = AgentWorkflowRun(
            merchant_id=merchant_id,
            run_id=run_id,
            mode=mode,
            execution_engine=execution_engine,
            status=WorkflowStatus.running.value,
            plan=steps,
            plan_fingerprint=plan_fingerprint(steps),
            step_count=len(steps),
            started_at=now,
            heartbeat_at=now,
            lease_owner=None,
            lease_expires_at=None,
            lease_generation=0,
        )
        self.db.add(row)
        # Flush so the caller gets an id, but leave the COMMIT to the caller:
        # the orchestrator owns the transaction boundary.
        self.db.flush()
        return row, True

    # ── lookup ──────────────────────────────────────────────────────────

    def get_workflow(
        self, *, merchant_id: uuid.UUID, run_id: str
    ) -> AgentWorkflowRun | None:
        """Merchant-scoped fetch. Another tenant's cycle reads as absent."""
        return self.db.scalars(
            select(AgentWorkflowRun).where(
                AgentWorkflowRun.merchant_id == merchant_id,
                AgentWorkflowRun.run_id == run_id,
            )
        ).first()

    def get_workflow_row(
        self, *, merchant_id: uuid.UUID, run_id: str
    ) -> AgentWorkflowRun:
        row = self.get_workflow(merchant_id=merchant_id, run_id=run_id)
        if row is None:
            raise WorkflowNotFound(run_id)
        return row

    # ── plan compatibility ──────────────────────────────────────────────

    def assert_plan_compatible(
        self,
        workflow: AgentWorkflowRun,
        plan: Sequence[tuple[str, dict[str, Any]]],
        mode: str,
    ) -> list[dict[str, Any]]:
        """
        Refuse to resume against a plan that changed underneath the cycle.

        Returns the STORED step list on success -- a resume always replays the
        steps that actually ran, not the current code's plan.
        """
        stored = workflow.plan or []
        stored_fp = workflow.plan_fingerprint or plan_fingerprint(stored)
        current_fp = plan_fingerprint(materialise_plan(mode, plan))
        if stored_fp != current_fp:
            raise PlanIncompatible(
                f"workflow {workflow.run_id} was created with plan {stored_fp[:12]} "
                f"but recovery requested plan {current_fp[:12]}; resume the "
                f"original plan or start a new cycle"
            )
        if workflow.mode != mode:
            raise PlanIncompatible(
                f"workflow {workflow.run_id} ran in mode {workflow.mode!r}, "
                f"not {mode!r}"
            )
        return stored

    # ── ownership ───────────────────────────────────────────────────────

    def claim(
        self,
        workflow: AgentWorkflowRun,
        *,
        owner: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        stale_after_seconds: int | None = None,
    ) -> int:
        """
        Acquire single-writer ownership with a compare-and-set UPDATE.

        Returns the NEW fencing generation. Every protected write the caller
        subsequently performs must carry it. A worker that never claims has no
        generation and therefore cannot pass any fencing check.

        The WHERE clause is the whole safety property: the UPDATE lands only if
        no live lease exists, so a second concurrent resume affects zero rows
        and raises instead of both proceeding.

        ``stale_after_seconds`` relaxes the condition to "or the owner's own
        heartbeat has gone cold". That is how a DEAD-but-unexpired lease is
        taken over without waiting out the full lease, and it stays a genuine
        compare-and-set: the winning UPDATE stamps ``heartbeat_at = now``, so a
        racing second takeover no longer matches the predicate and loses.
        """
        now = _utcnow()
        predicate = (
            (AgentWorkflowRun.lease_expires_at.is_(None))
            | (AgentWorkflowRun.lease_expires_at <= now)
        )
        if stale_after_seconds is not None:
            cold = now - timedelta(seconds=stale_after_seconds)
            predicate = predicate | (
                AgentWorkflowRun.heartbeat_at.is_(None)
            ) | (AgentWorkflowRun.heartbeat_at <= cold)

        result = self.db.execute(
            update(AgentWorkflowRun)
            .where(AgentWorkflowRun.id == workflow.id, predicate)
            .values(
                lease_owner=owner,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                heartbeat_at=now,
                updated_at=now,
                # The fencing token. Monotonic, so a worker that once held
                # generation N can never act once the column has moved past N.
                lease_generation=AgentWorkflowRun.lease_generation + 1,
            )
            # The predicate must be evaluated BY THE DATABASE. Synchronising it
            # against in-session objects would compare a timezone-aware `now`
            # against the naive datetimes SQLite hands back, which raises
            # rather than deciding the race. rowcount is the authority.
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 0:
            raise WorkflowOwnershipError(
                f"workflow {workflow.run_id} is owned by a live worker; "
                f"refusing to take over"
            )
        # Re-read so the caller sees the values the database actually stored,
        # including the generation this claim just minted.
        self.db.expire(workflow)
        self.db.refresh(workflow)
        return int(workflow.lease_generation)

    def heartbeat(
        self,
        workflow: AgentWorkflowRun,
        *,
        expected_generation: int | None = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> None:
        """
        Extend the lease while the owning process is still working.

        Fenced: when ``expected_generation`` is supplied, a worker whose
        generation has been superseded updates nothing and raises. That is what
        stops a paused worker from extending a lease it no longer owns -- which
        would otherwise keep a recovered cycle locked forever.
        """
        now = _utcnow()
        guard = ()
        if expected_generation is not None:
            guard = (AgentWorkflowRun.lease_generation == expected_generation,)
        result = self.db.execute(
            update(AgentWorkflowRun)
            .where(AgentWorkflowRun.id == workflow.id, *guard)
            .values(
                heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 0:
            raise StaleLeaseError(
                f"workflow {workflow.run_id}: heartbeat rejected, generation "
                f"{expected_generation} is obsolete"
            )
        self.db.flush()

    def release(
        self, workflow: AgentWorkflowRun, *, expected_generation: int | None = None
    ) -> None:
        """
        Drop ownership without changing terminal status.

        Fenced for the same reason as ``heartbeat``: a superseded worker must
        not be able to clear the CURRENT owner's lease.
        """
        now = _utcnow()
        guard = ()
        if expected_generation is not None:
            guard = (AgentWorkflowRun.lease_generation == expected_generation,)
        self.db.execute(
            update(AgentWorkflowRun)
            .where(AgentWorkflowRun.id == workflow.id, *guard)
            .values(lease_owner=None, lease_expires_at=None, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        self.db.flush()

    # ── step status ─────────────────────────────────────────────────────

    def attempt_rows(
        self, workflow_id: uuid.UUID
    ) -> dict[str, AgentRun]:
        """Best attempt per ``step_key`` across every terminal status.

        Highest attempt wins. Unlike the previous ``completed_steps``, nothing is
        filtered out here: the reuse DECISION needs to see failures and
        reconciliations too, because "why is this step not reusable" is exactly
        what an operator has to be told.
        """
        rows = self.db.scalars(
            select(AgentRun)
            .where(AgentRun.workflow_id == workflow_id)
            .order_by(AgentRun.attempt.asc())
        ).all()
        best: dict[str, AgentRun] = {}
        for row in rows:
            if row.step_key:
                best[row.step_key] = row
        return best

    def decide(self, *, step_row: AgentRun, merchant_id: uuid.UUID | None = None):
        """Instance-level access to the reuse policy, for call sites that already
        hold a ``WorkflowRunService``."""
        return decide_reuse(self.db, step_row, merchant_id=merchant_id)

    def mark_needs_reconciliation(
        self, workflow_id: uuid.UUID, step_key: str
    ) -> int:
        """
        Persist ``needs_reconciliation`` on every attempt of a step.

        Called only from the recovery path, and only after the reuse decision
        found evidence of an uncertain external effect. Writing it durably is
        what stops the next recovery from treating the step as retryable and
        simply firing the same uncertain operation again.
        """
        rows = self.db.scalars(
            select(AgentRun).where(
                AgentRun.workflow_id == workflow_id,
                AgentRun.step_key == step_key,
            )
        ).all()
        now = _utcnow()
        for row in rows:
            row.status = AgentRunStatus.needs_reconciliation.value
            row.completed_at = row.completed_at or now
            errors = list(row.errors or [])
            note = "requires reconciliation: external effect may be in flight"
            if note not in errors:
                errors.append(note)
            row.errors = errors
        if rows:
            self.db.flush()
        return len(rows)

    def reusable_steps(
        self, workflow_id: uuid.UUID, *, merchant_id: uuid.UUID | None = None
    ) -> dict[str, AgentRun]:
        """Steps safe to replay downstream, keyed by ``step_key``.

        Delegates the judgement to :func:`decide_reuse` so that "safe to reuse"
        is one evidence-based decision rather than a status whitelist.
        """
        out: dict[str, AgentRun] = {}
        for key, row in self.attempt_rows(workflow_id).items():
            verdict = decide_reuse(self.db, row, merchant_id=merchant_id)
            if verdict.verdict is ReuseVerdict.REUSE:
                out[key] = row
        return out

    def next_attempt(self, workflow_id: uuid.UUID, step_key: str) -> int:
        """Next attempt number for a step, preserving earlier attempts."""
        used = self.db.scalars(
            select(AgentRun.attempt).where(
                AgentRun.workflow_id == workflow_id,
                AgentRun.step_key == step_key,
            )
        ).all()
        return (max(used) + 1) if used else 1

    def mark_interrupted_steps(
        self, workflow_id: uuid.UUID, *, reason: str
    ) -> list[str]:
        """
        Close out steps left ``running`` by a dead process.

        Called only from the recovery path, and only after ownership has been
        acquired -- so a step that is genuinely mid-flight under a live lease is
        never touched. This is what converts an invisible crash into an
        auditable ``interrupted`` record instead of a permanent orphan.
        """
        rows = self.db.scalars(
            select(AgentRun).where(
                AgentRun.workflow_id == workflow_id,
                AgentRun.status == AgentRunStatus.running.value,
            )
        ).all()
        now = _utcnow()
        for row in rows:
            row.status = AgentRunStatus.interrupted.value
            row.completed_at = now
            row.heartbeat_at = row.heartbeat_at or row.started_at
            errors = list(row.errors or [])
            if reason not in errors:
                errors.append(reason)
            row.errors = errors
        if rows:
            self.db.flush()
        return [r.step_key or r.agent_name for r in rows]

    # ── independent-boundary step records ───────────────────────────────

    def record_step_start(
        self,
        state: Session,
        *,
        merchant_id: uuid.UUID,
        agent_name: str,
        orchestrator_run_id: str,
        mode: str,
        input_summary: dict[str, Any],
        workflow_id: uuid.UUID,
        step_key: str,
        step_index: int,
        attempt: int,
        commit: bool = True,
        expected_generation: int | None = None,
    ) -> uuid.UUID:
        """
        Persist "step started" on a DEDICATED session and commit it there.

        Why not ``self.db``: the orchestrator's session also carries merchant
        business data. Committing it to make the start record durable would
        sweep along whatever else happened to be pending, and would make the
        audit row's durability depend on unrelated work. ``state`` is a separate
        Session on the same Engine, so this commit reaches exactly one row.

        Returns the new row's id so the outcome can be recorded against it.

        ``commit=False`` is used for the degraded path where the caller could
        not obtain a separate session and must fall back to its own.
        """
        from backend.app.services.agent_run_service import AgentRunService

        _assert_generation(
            state, workflow_id=workflow_id, expected=expected_generation
        )
        row = AgentRunService(state).start_run(
            merchant_id=merchant_id,
            agent_name=agent_name,
            orchestrator_run_id=orchestrator_run_id,
            mode=mode,
            input_summary=input_summary,
            workflow_id=workflow_id,
            step_key=step_key,
            step_index=step_index,
            attempt=attempt,
        )
        if commit:
            state.commit()
        else:
            state.flush()
        return row.id

    def record_step_result(
        self,
        state: Session,
        run_pk: uuid.UUID,
        result: Any,
        *,
        commit: bool = True,
        expected_generation: int | None = None,
        workflow_id: uuid.UUID | None = None,
    ) -> bool:
        """
        Persist "step finished" on the same dedicated session.

        Runs after the agent's savepoint has been committed OR rolled back, so a
        failed step still records WHY it failed even though its business writes
        were discarded. Returns False if the row vanished, which can only happen
        if the workflow was deleted mid-flight.

        ``commit=False`` mirrors ``record_step_start`` for the degraded path.
        """
        from backend.app.services.agent_run_service import AgentRunService

        # Fenced BEFORE reading the row. A worker whose generation has been
        # superseded must not be able to mark its step complete, even if its row
        # is still present.
        if workflow_id is None:
            candidate = state.get(AgentRun, run_pk)
            workflow_id = candidate.workflow_id if candidate is not None else None
        _assert_generation(
            state, workflow_id=workflow_id, expected=expected_generation
        )

        row = state.get(AgentRun, run_pk)
        if row is None:
            return False
        AgentRunService(state).complete_run(row, result)
        if commit:
            state.commit()
        else:
            state.flush()
        return True

    # ── terminal status ─────────────────────────────────────────────────

    def finish_workflow(
        self,
        workflow: AgentWorkflowRun,
        *,
        status: str,
        errors: list[str] | None = None,
        expected_generation: int | None = None,
    ) -> None:
        now = _utcnow()
        guard = ()
        if expected_generation is not None:
            guard = (AgentWorkflowRun.lease_generation == expected_generation,)
        result = self.db.execute(
            update(AgentWorkflowRun)
            .where(AgentWorkflowRun.id == workflow.id, *guard)
            .values(
                status=status,
                completed_at=now,
                errors=list(errors or []),
                lease_owner=None,
                lease_expires_at=None,
                heartbeat_at=now,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 0:
            raise StaleLeaseError(
                f"workflow {workflow.run_id}: finalisation rejected, generation "
                f"{expected_generation} is obsolete"
            )
        # The terminal status is the single most important field on this row.
        # Because the UPDATE is database-authoritative, the identity-mapped
        # instance would otherwise keep showing the PRE-finish status, and a
        # later resume() in the same session would read that stale value and
        # happily re-run a finished cycle.
        self.db.expire(workflow)
        self.db.flush()


# ── cancellation ───────────────────────────────────────────────────────────

@dataclass
class ActiveRunReport:
    """
    The authoritative answer to "is an analysis really running?".

    Read-only. Nothing here creates, mutates or cancels anything, which is what
    makes it safe for a dashboard to call on mount and on every poll.

    The whole point is that a persisted ``running`` row is NOT proof of life. A
    worker that crashed leaves exactly that row behind, and reporting it as
    active is what made the dashboard claim to be analysing forever. Liveness is
    therefore judged on recency of a heartbeat, and a row with no workflow
    tracking (the historical employee-agent rows) is judged on how long ago it
    was last touched.
    """

    active: bool = False
    run_id: str | None = None
    mode: str | None = None
    status: str | None = None
    started_at: str | None = None
    last_heartbeat_at: str | None = None
    #: Why the dashboard should NOT show "analysing", when active is False.
    idle_reason: str | None = None
    steps_running: int = 0
    cancel_requested_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "run_id": self.run_id,
            "mode": self.mode,
            "status": self.status,
            "started_at": self.started_at,
            "last_heartbeat_at": self.last_heartbeat_at,
            "idle_reason": self.idle_reason,
            "steps_running": self.steps_running,
            "cancel_requested_at": self.cancel_requested_at,
        }


def request_cancel(
    db: Session,
    *,
    merchant_id: uuid.UUID,
    run_id: str,
    expected_generation: int | None = None,
) -> AgentWorkflowRun:
    """
    Persist an operator's request to stop a cycle, and terminalise it.

    Returns the workflow row. Raises ``WorkflowNotFound`` for another tenant's
    cycle, which is deliberately indistinguishable from a missing one.

    The status becomes ``cancelled`` immediately so no surface can keep
    reporting a superseded cycle as active, AND ``cancel_requested_at`` is
    stamped so a worker still mid-plan observes the request between steps. Both
    are needed: the status alone would be invisible to a worker whose session
    already holds a cached row, and the flag alone would leave the dashboard
    showing "running" until the worker happened to notice.

    Terminal states stay terminal: a completed, failed, cancelled or already
    interrupted cycle is returned unchanged, so a late cancellation can never
    rewrite a finished outcome.
    """
    workflow = db.scalars(
        select(AgentWorkflowRun).where(
            AgentWorkflowRun.merchant_id == merchant_id,
            AgentWorkflowRun.run_id == run_id,
        )
    ).first()
    if workflow is None:
        raise WorkflowNotFound(run_id)

    if workflow.status != WorkflowStatus.running.value:
        # Already finished. Cancellation is a no-op, not an error.
        return workflow

    now = _utcnow()
    guard = ()
    if expected_generation is not None:
        guard = (AgentWorkflowRun.lease_generation == expected_generation,)
    result = db.execute(
        update(AgentWorkflowRun)
        .where(AgentWorkflowRun.id == workflow.id, *guard)
        .values(
            status=WorkflowStatus.cancelled.value,
            cancel_requested_at=workflow.cancel_requested_at or now,
            completed_at=now,
            lease_owner=None,
            lease_expires_at=None,
            heartbeat_at=now,
            # Fence the worker: after this it cannot record step outcomes.
            lease_generation=AgentWorkflowRun.lease_generation + 1,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        raise StaleLeaseError(
            f"workflow {run_id}: cancellation rejected, generation "
            f"{expected_generation} is obsolete"
        )
    # Close out the step that was in flight so nothing is left looking active.
    closed = WorkflowRunService(db).mark_interrupted_steps(
        workflow.id, reason="cancelled_by_operator"
    )
    # Also close any AgentRun rows linked to this cycle by orchestrator_run_id
    db.execute(
        update(AgentRun)
        .where(
            AgentRun.merchant_id == merchant_id,
            AgentRun.orchestrator_run_id == run_id,
            AgentRun.status == AgentRunStatus.running.value,
        )
        .values(
            status=AgentRunStatus.cancelled.value,
            completed_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    # And cancel employee agent runs for this cycle
    try:
        from backend.app.models.product_agi import ProductAgentRun
        db.execute(
            update(ProductAgentRun)
            .where(
                ProductAgentRun.merchant_id == merchant_id,
                ProductAgentRun.analysis_cycle_id == run_id,
                ProductAgentRun.status.in_(("queued", "running")),
            )
            .values(
                status="cancelled",
                completed_at=now,
            )
            .execution_options(synchronize_session=False)
        )
    except Exception:
        pass
    try:
        from backend.app.models.marketing_agi import MarketingAGIRun
        db.execute(
            update(MarketingAGIRun)
            .where(
                MarketingAGIRun.merchant_id == merchant_id,
                MarketingAGIRun.analysis_cycle_id == run_id,
                MarketingAGIRun.status.in_(("queued", "running")),
            )
            .values(
                status="cancelled",
                completed_at=now,
            )
            .execution_options(synchronize_session=False)
        )
    except Exception:
        pass
    db.commit()
    db.expire_all()
    refreshed = db.get(AgentWorkflowRun, workflow.id)
    log.info(
        "Workflow %s cancelled by operator; %d in-flight step(s) closed: %s",
        run_id, len(closed), closed,
    )
    return refreshed if refreshed is not None else workflow


def is_cancel_requested(db: Session, workflow_id: uuid.UUID) -> bool:
    """
    Read-only cancellation probe for the orchestrator's between-step check.

    Deliberately a fresh scalar read rather than a cached attribute: the worker
    holds a long-lived session, and a cached value would never observe a
    cancellation requested by another process.
    """
    return bool(
        db.execute(
            select(AgentWorkflowRun.cancel_requested_at).where(
                AgentWorkflowRun.id == workflow_id
            )
        ).scalar_one_or_none()
    )


def active_run_report(
    db: Session,
    *,
    merchant_id: uuid.UUID,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
) -> ActiveRunReport:
    """
    Read-only, liveness-bounded answer to "should the dashboard show ANALYZING?".

    A tracked cycle counts as active only while it is ``running`` AND its
    heartbeat is fresh. An untracked historical ``running`` row (the employee
    agents, and any run written before workflow tracking existed) counts as
    active only if it was last touched within the staleness window.

    This function never writes. Reconciling genuinely dead rows is the sweep's
    job, because a GET that mutates is exactly the coupling this task removes.
    """
    now = _utcnow()
    cutoff = now - timedelta(seconds=stale_after_seconds)

    workflow = db.scalars(
        select(AgentWorkflowRun)
        .where(
            AgentWorkflowRun.merchant_id == merchant_id,
            AgentWorkflowRun.status == WorkflowStatus.running.value,
        )
        .order_by(AgentWorkflowRun.started_at.desc())
        .limit(1)
    ).first()
    if workflow is not None:
        if workflow.cancel_requested_at is not None:
            return ActiveRunReport(
                active=False,
                run_id=workflow.run_id,
                mode=workflow.mode,
                status=WorkflowStatus.cancelled.value,
                started_at=workflow.started_at.isoformat() if workflow.started_at else None,
                last_heartbeat_at=workflow.heartbeat_at.isoformat() if workflow.heartbeat_at else None,
                cancel_requested_at=workflow.cancel_requested_at.isoformat(),
                idle_reason="cancellation requested by operator",
            )
        beat = workflow.heartbeat_at
        beat_utc = beat if beat and beat.tzinfo else (beat.replace(tzinfo=timezone.utc) if beat else None)
        if beat_utc is not None and beat_utc > cutoff:
            running_steps = db.scalar(
                select(func.count()).select_from(AgentRun).where(
                    AgentRun.workflow_id == workflow.id,
                    AgentRun.status == AgentRunStatus.running.value,
                )
            )
            return ActiveRunReport(
                active=True,
                run_id=workflow.run_id,
                mode=workflow.mode,
                status=workflow.status,
                started_at=workflow.started_at.isoformat() if workflow.started_at else None,
                last_heartbeat_at=beat.isoformat() if beat else None,
                steps_running=int(running_steps or 0),
                cancel_requested_at=(
                    workflow.cancel_requested_at.isoformat()
                    if workflow.cancel_requested_at else None
                ),
            )
        return ActiveRunReport(
            active=False,
            run_id=workflow.run_id,
            mode=workflow.mode,
            status=workflow.status,
            started_at=workflow.started_at.isoformat() if workflow.started_at else None,
            last_heartbeat_at=beat.isoformat() if beat else None,
            idle_reason="workflow heartbeat is stale; the owning worker is gone",
        )

    # No tracked cycle. Fall back to untracked historical rows, bounded by age.
    legacy = db.execute(
        select(AgentRun.agent_name, AgentRun.started_at, AgentRun.heartbeat_at,
               AgentRun.orchestrator_run_id)
        .where(
            AgentRun.merchant_id == merchant_id,
            AgentRun.workflow_id.is_(None),
            AgentRun.status == AgentRunStatus.running.value,
        )
        .order_by(AgentRun.started_at.desc())
        .limit(1)
    ).first()
    if legacy is not None:
        _name, started, beat, cycle_id = legacy
        reference = beat or started
        if reference is not None:
            reference_utc = (
                reference if reference.tzinfo
                else reference.replace(tzinfo=timezone.utc)
            )
            if reference_utc > cutoff:
                return ActiveRunReport(
                    active=True,
                    run_id=cycle_id,
                    status=AgentRunStatus.running.value,
                    started_at=started.isoformat() if started else None,
                    last_heartbeat_at=reference.isoformat() if reference else None,
                    steps_running=1,
                )
        return ActiveRunReport(
            active=False,
            run_id=cycle_id,
            status=AgentRunStatus.running.value,
            started_at=started.isoformat() if started else None,
            last_heartbeat_at=reference.isoformat() if reference else None,
            idle_reason=(
                "an untracked run row is still marked running but has not been "
                "touched within the staleness window; its worker is gone"
            ),
        )

    return ActiveRunReport(active=False, idle_reason="no run in progress")


def is_resumable(workflow: AgentWorkflowRun) -> bool:
    """
    Policy gate for automatic resume.

    A FINISHED cycle is never auto-resumed: re-running it would redo completed
    work and re-propose actions. Anything unfinished is a candidate, but a cycle
    with a CURRENT heartbeat may still be executing under a healthy worker --
    that case is settled by ``claim()``'s compare-and-set, not here, so a
    dead-but-unexpired lease is not locked out forever.
    """
    if workflow.status in (
        WorkflowStatus.completed.value,
        WorkflowStatus.partial.value,
        # A cancelled cycle is terminal. Recovery must never restart something an
        # operator deliberately stopped -- that is precisely the "never stops"
        # behaviour this change exists to remove.
        WorkflowStatus.cancelled.value,
    ):
        return False
    return True


__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "EXECUTION_ENGINE_LANGGRAPH",
    "EXECUTION_ENGINE_LEGACY",
    "KNOWN_EXECUTION_ENGINES",
    "OrphanReconciliation",
    "PlanIncompatible",
    "ActiveRunReport",
    "DEFAULT_STALE_AFTER_SECONDS",
    "ReuseDecision",
    "ReuseVerdict",
    "StaleLeaseError",
    "SweepReport",
    "decide_reuse",
    "sweep_stale_workflows",
    "WorkflowNotFound",
    "WorkflowNotResumable",
    "WorkflowOwnershipError",
    "WorkflowRunService",
    "current_workflow",
    "current_workflow_id",
    "active_run_report",
    "is_cancel_requested",
    "is_resumable",
    "materialise_plan",
    "request_cancel",
    "plan_fingerprint",
    "reconcile_orphan_runs",
    "step_key",
]
