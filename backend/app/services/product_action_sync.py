"""Product Agent mirror sync — propagate canonical action transitions.

CANONICAL SOURCE OF TRUTH: ``agent_actions.status`` (requested → approved →
executing → completed/failed, or rejected).

The Product Agent keeps a *mirror* of that state in:
* ``product_agent_runs.status`` / ``current_stage`` / ``approval_status``
* ``product_agent_recommendations.status`` (prepare-time snapshot)
* ``product_agent_events`` (real activity feed for the dashboard)

Without this module those mirrors froze at prepare-time, so the Product
Agent dashboard kept showing "waiting for approval" forever after the
merchant approved/executed the action from /actions.

Every function here is called from ``action_service`` AFTER the canonical
transition has flushed (the route still owns the commit). Sync failures
are logged and swallowed — approval/execution must never fail because a
mirror update hiccuped. Tenant isolation is re-verified before touching
any product agent row.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.agent_action import AgentAction
from backend.app.models.product_agi import (
    ProductAgentEvent,
    ProductAgentRecommendation,
    ProductAgentRun,
)

log = logging.getLogger(__name__)


#: Canonical action status → the recommendation's own lifecycle vocabulary.
_RECOMMENDATION_STATUS: dict[str, str] = {
    "approved": "approved",
    "rejected": "rejected",
    "executing": "executing",
    "completed": "executed",
    "failed": "failed",
}

#: Recommendation lifecycle, ordered. Index IS the rank, so a mirror update can
#: only ever move a recommendation forward.
RECOMMENDATION_LIFECYCLE: tuple[str, ...] = (
    "proposed",
    "awaiting_approval",
    "approved",
    "executing",
    "executed",
    "failed",
    "rejected",
)

#: Recommendation states that are final — nothing may move them afterwards.
TERMINAL_RECOMMENDATION_STATUSES = frozenset({"executed", "failed", "rejected"})

# Run statuses that mark the run itself as finished. Stamping
# ``completed_at`` is limited to these, so the dashboard's elapsed time can
# never present an approval instant as the run's completion.
TERMINAL_RUN_STATUSES = frozenset(
    {"completed", "completed_no_actions", "completed_with_failures", "failed", "cancelled"}
)

# Canonical action status → (event_type, message) for the activity feed.
# The run-level verdict is NOT taken from here: it always comes from
# ``aggregate_run_state`` over ALL of the run's actions.
_SYNC_MAP: dict[str, tuple[str, str]] = {
    "approved": ("action_approved", "Action approved by you — ready to execute"),
    "rejected": ("action_rejected", "Action was not approved"),
    "executing": ("execution_started", "Action execution started"),
    "completed": ("action_executed", "Action executed successfully"),
    "failed": ("action_failed", "Action execution failed"),
}

# Stage recorded ON the activity event: the step the event happened at (the
# approval gate for approve/reject), not the run's stage after the
# transition — the feed keeps describing its own moment.
_EVENT_STAGE: dict[str, str] = {
    "approved": "waiting_approval",
    "rejected": "waiting_approval",
    "executing": "execute_measure",
    "completed": "execute_measure",
    "failed": "execute_measure",
}


#: Run-level outcomes decided by the run itself (crash, safety block,
#: cancel) — the action aggregate must never overwrite them, because they
#: are not implied by any action row.
RUN_LEVEL_STATUSES = frozenset({"failed", "blocked", "cancelled"})

#: Canonical action statuses that close an action.
TERMINAL_ACTION_STATUSES = frozenset({"completed", "failed", "rejected"})


def _enum_value(v: object) -> str:
    return v.value if hasattr(v, "value") else str(v)


def aggregate_run_state(
    action_statuses: list[str],
) -> tuple[str, str, str] | None:
    """(run_status, current_stage, approval_status) implied by canonical actions.

    ``agent_actions.status`` is the single source of truth, so this is the
    ONE mapping from action rows to run state — used both when mirroring a
    transition (``sync_product_agent_from_action``) and when reading the
    dashboard (``product_agi.service.build_status``). One mapping means the
    dashboard can never disagree with the actions pipeline.

    Precedence is deliberate and mirrors the workflow:

      * any action still ``requested``   → the run is still waiting for a
        human, even if a sibling action was already approved or executed
      * any action ``executing``         → execution is genuinely running
      * any action ``approved``          → approvals are satisfied, but
        execution has not finished (never "completed")
      * all actions terminal             → completed / completed with
        failures, from what actually happened

    Returns None when no canonical action exists (nothing to aggregate).
    """
    if not action_statuses:
        return None
    has_requested = "requested" in action_statuses
    has_executing = "executing" in action_statuses
    has_approved = "approved" in action_statuses
    has_completed = "completed" in action_statuses
    has_failed = "failed" in action_statuses

    if has_requested:
        return "waiting_approval", "waiting_approval", "required"
    if has_executing:
        return "executing", "execute_measure", "executing"
    if has_approved:
        # Approval itself is done, so the run sits at the NEXT step:
        # execution. Keeping the stage at ``waiting_approval`` here is what
        # made the progress tracker show "waiting for approval" while the
        # merchant had already approved.
        return "approved_awaiting_execution", "execute_measure", "approved"
    if has_failed:
        return "completed_with_failures", "execute_measure", "failed"
    if has_completed:
        return "completed", "execute_measure", "completed"
    # Every action was rejected: the run finished, nothing executed.
    return "completed", "execute_measure", "rejected"


def _find_recommendations(db: Session, action: AgentAction) -> list[ProductAgentRecommendation]:
    """All Product Agent recommendations linked to an action (tenant-verified)."""
    stmt = (
        select(ProductAgentRecommendation)
        .where(
            ProductAgentRecommendation.action_id == action.id,
            ProductAgentRecommendation.merchant_id == action.merchant_id,
        )
        .order_by(ProductAgentRecommendation.created_at.asc())
    )
    return list(db.scalars(stmt).all())


def _find_runs(db: Session, action: AgentAction) -> list[ProductAgentRun]:
    """Every Product Agent run that has recommendations linked to this action."""
    recs = _find_recommendations(db, action)
    if not recs:
        return []
    # Deterministic order: a set made ``runs[0]`` (and therefore the AI Team
    # audit row it feeds) depend on hash ordering.
    run_ids = sorted({r.run_id for r in recs})
    runs = []
    for run_id in run_ids:
        run = db.get(ProductAgentRun, run_id)
        if run is not None and run.merchant_id == action.merchant_id:
            runs.append(run)
    return runs


def _recalc_run_approval_state(db: Session, run: ProductAgentRun) -> tuple[str, str, str]:
    """Recalculate run-level status, stage, approval_status from live actions.

    Returns (status, stage, approval_status). The verdict comes from
    ``aggregate_run_state`` — the same function the read model uses — so a
    stored mirror can never describe a different world than the dashboard.
    """
    recs = db.scalars(
        select(ProductAgentRecommendation).where(
            ProductAgentRecommendation.run_id == run.id,
            ProductAgentRecommendation.merchant_id == run.merchant_id,
            ProductAgentRecommendation.action_id.is_not(None),
        )
    ).all()

    if not recs:
        # No actions were ever created for this run
        if run.status in ("queued", "running"):
            return run.status, run.current_stage, "not_required"
        return run.status, run.current_stage, run.approval_status or "not_required"

    action_statuses = []
    for rec in recs:
        act = db.get(AgentAction, rec.action_id)
        if act and act.merchant_id == run.merchant_id:
            action_statuses.append(_enum_value(act.status))

    if not action_statuses:
        return run.status, run.current_stage, "required"

    aggregate = aggregate_run_state(action_statuses)
    if aggregate is None:
        return run.status, run.current_stage, run.approval_status or "required"
    return aggregate


def _emit_run_event(
    db: Session,
    run: ProductAgentRun,
    event_type: str,
    message: str,
    action: AgentAction,
    stage: str | None = None,
) -> None:
    """Append a real run event (next seq) so activity timelines show it.

    Idempotent per (run, event_type, action): a repeated sync for the same
    canonical transition must not mint a duplicate activity row. The
    de-duplication query is scoped to this event TYPE rather than to the last
    N rows — a fixed window silently stopped de-duplicating once a run had
    emitted more events than the window (a long run emits one row per MCP
    call), which is how duplicate activity rows appeared in the feed.
    """
    action_key = str(action.id)
    already = db.scalar(
        select(func.count())
        .select_from(ProductAgentEvent)
        .where(
            ProductAgentEvent.run_id == run.id,
            ProductAgentEvent.event_type == event_type,
            ProductAgentEvent.data["action_id"].as_string() == action_key,
        )
    )
    if already:
        return
    max_seq = db.scalar(
        select(func.max(ProductAgentEvent.seq)).where(
            ProductAgentEvent.run_id == run.id
        )
    )
    event = ProductAgentEvent(
        run_id=run.id,
        merchant_id=run.merchant_id,
        seq=int(max_seq or 0) + 1,
        stage=stage or run.current_stage,
        event_type=event_type,
        message=message,
        data={"action_id": action_key},
    )
    db.add(event)
    db.flush()


def _complete_ai_team_audit_row(
    db: Session,
    *,
    merchant_id: uuid.UUID,
    cycle_id: str,
    status: str,
    output: dict[str, Any] | None = None,
    errors: list[str] | None = None,
) -> None:
    """Close the AgentRun audit row so the AI Team page shows live status."""
    from backend.app.models.agent_run import AgentRun
    from backend.app.models.enums import AgentRunStatus

    row = db.scalar(
        select(AgentRun).where(
            AgentRun.merchant_id == merchant_id,
            AgentRun.orchestrator_run_id == cycle_id,
            AgentRun.agent_name == "ProductAGI",
        )
    )
    if row is None:
        return
    try:
        row.status = AgentRunStatus(status)
    except ValueError:
        row.status = AgentRunStatus.failed
    row.completed_at = datetime.now(timezone.utc)
    if output is not None:
        row.output_summary = output
    if errors is not None:
        row.errors = errors
    db.flush()


def sync_product_agent_from_action(
    db: Session, action: AgentAction
) -> ProductAgentRun | None:
    """Mirror a canonical action transition onto Product Agent rows.

    Safe to call after approve/reject/executing/completed/failed. No-ops
    when the action has no linked Product Agent recommendation. Never commits —
    the caller owns the transaction. Never raises.

    The mirror runs inside a SAVEPOINT. A mirror failure (bad column width,
    constraint, transient DB error) must not be able to poison the caller's
    transaction: without the savepoint the failed statement leaves the Session
    unusable, so the caller's own audit write and ``commit()`` raise
    ``PendingRollbackError`` and the merchant's approval is lost entirely —
    while the log line claims the canonical state was kept.

    Leaving the ``with`` block via an exception rolls the SAVEPOINT back only.
    The caller's flushed canonical transition stays pending and still commits,
    which is exactly the contract: the mirror is best-effort, the action is not.
    """
    try:
        with db.begin_nested():
            return _sync_product_agent_from_action(db, action)
    except Exception:
        log.exception(
            "Product Agent mirror sync failed for action %s (canonical state kept)",
            action.id,
        )
        return None


def _sync_product_agent_from_action(
    db: Session, action: AgentAction
) -> ProductAgentRun | None:
    status = _enum_value(action.status)
    mapping = _SYNC_MAP.get(status)
    if mapping is None:
        return None  # "requested" and unknown states need no mirror

    event_type, message = mapping

    # Find all linked recommendations
    recs = _find_recommendations(db, action)
    if not recs:
        return None

    # Update recommendation status snapshots.
    #
    # ``RECOMMENDATION_LIFECYCLE`` ranks the recommendation's OWN vocabulary
    # (proposed → awaiting_approval → approved → executing → executed /
    # failed / rejected). The previous code ranked "completed" while writing
    # "executed", so ``executed`` looked up as order 0 and every completed
    # action left its recommendation frozen on "executing" forever.
    new_rec_status = _RECOMMENDATION_STATUS.get(status, "awaiting_approval")
    new_order = RECOMMENDATION_LIFECYCLE.index(new_rec_status)

    for rec in recs:
        current = rec.status if rec.status in RECOMMENDATION_LIFECYCLE else "proposed"
        current_order = RECOMMENDATION_LIFECYCLE.index(current)
        # Terminal recommendation states are final: a late or duplicated
        # transition must never flip "executed" into "rejected" (or back).
        if current in TERMINAL_RECOMMENDATION_STATUSES:
            continue
        if new_order >= current_order:
            rec.status = new_rec_status
    db.flush()

    # Find and update all affected runs
    runs = _find_runs(db, action)
    if not runs:
        return None

    # Recalculate each run's aggregate state from ALL its actions
    for run in runs:
        new_status, new_stage, new_approval_status = _recalc_run_approval_state(db, run)

        # The aggregate is a pure function of the canonical action rows, so
        # it is applied as-is — a mirror must never lag behind (that is how
        # the dashboard ended up claiming "waiting for approval" while every
        # action had already executed). The only exception is a run-level
        # outcome the run recorded itself: crash, safety block or cancel.
        if run.status not in RUN_LEVEL_STATUSES:
            run.status = new_status
            run.current_stage = new_stage
            run.approval_status = new_approval_status
            if new_status in TERMINAL_RUN_STATUSES:
                run.completed_at = action.completed_at or datetime.now(timezone.utc)
                if run.completed_at.tzinfo is None:
                    run.completed_at = run.completed_at.replace(tzinfo=timezone.utc)
            elif run.completed_at is not None:
                # New unresolved work reopened the run; a finished run must not
                # keep advertising a completion instant it no longer owns.
                run.completed_at = None

        # Update run metrics: executed_count
        executed_count = 0
        all_recs = db.scalars(
            select(ProductAgentRecommendation).where(
                ProductAgentRecommendation.run_id == run.id,
                ProductAgentRecommendation.merchant_id == run.merchant_id,
                ProductAgentRecommendation.action_id.is_not(None),
            )
        ).all()
        for r in all_recs:
            act = db.get(AgentAction, r.action_id)
            if act and act.merchant_id == run.merchant_id:
                if _enum_value(act.status) == "completed":
                    executed_count += 1
        metrics = dict(run.metrics or {})
        metrics["executed_count"] = executed_count
        metrics["action_count"] = len(all_recs)
        run.metrics = metrics

        db.flush()
        _emit_run_event(
            db, run, event_type, message, action, stage=_EVENT_STAGE.get(status)
        )

    # If this action transition is terminal, update AI Team audit row
    if status in TERMINAL_ACTION_STATUSES:
        # Check if ALL actions for this run's cycle are terminal
        primary_run = runs[0]
        if primary_run.analysis_cycle_id:
            all_recs = db.scalars(
                select(ProductAgentRecommendation).where(
                    ProductAgentRecommendation.run_id == primary_run.id,
                    ProductAgentRecommendation.merchant_id == primary_run.merchant_id,
                    ProductAgentRecommendation.action_id.is_not(None),
                )
            ).all()
            all_terminal = True
            any_failed = False
            for r in all_recs:
                act = db.get(AgentAction, r.action_id)
                if act and act.merchant_id == primary_run.merchant_id:
                    act_status = _enum_value(act.status)
                    if act_status not in TERMINAL_ACTION_STATUSES:
                        all_terminal = False
                        break
                    if act_status == "failed":
                        any_failed = True
            if all_terminal:
                audit_status = "failed" if any_failed else "completed"
                output = {
                    "status": primary_run.status,
                    "stage": primary_run.current_stage,
                    "approval_status": primary_run.approval_status,
                    "products_analyzed": primary_run.products_analyzed,
                    "opportunities_found": primary_run.opportunities_found,
                    "recommendations_created": primary_run.recommendations_created,
                    "executed_count": executed_count,
                    "action_count": len(all_recs),
                }
                _complete_ai_team_audit_row(
                    db,
                    merchant_id=primary_run.merchant_id,
                    cycle_id=primary_run.analysis_cycle_id,
                    status=audit_status,
                    output=output,
                )

    return runs[0]