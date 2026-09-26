"""Marketing Agent mirror sync — propagate canonical action transitions.

CANONICAL SOURCE OF TRUTH: ``agent_actions.status`` (requested → approved →
executing → completed/failed, or rejected).

The Marketing Agent keeps a *mirror* of that state in three places:

* ``marketing_agi_campaigns.lifecycle``
* ``marketing_agi_runs.state["prepared_action"]`` (status snapshot)
* ``marketing_agi_runs.status`` (parked at ``waiting_approval``)

Without this module those mirrors froze at prepare-time, so the Marketing
Agent dashboard kept showing "waiting for approval" forever after the
merchant approved/executed the action from /actions.

Every function here is called from ``action_service`` AFTER the canonical
transition has flushed (the route still owns the commit). Sync failures
are logged and swallowed — approval/execution must never fail because a
mirror update hiccuped. Tenant isolation is re-verified before touching
any marketing row.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.agent_action import AgentAction
from backend.app.models.marketing_agi import (
    MarketingAGICampaign,
    MarketingAGIEvent,
    MarketingAGIRun,
)

log = logging.getLogger(__name__)


# Lifecycle precedence — mirrors only ever move forward, never regress.
_LIFECYCLE_ORDER: dict[str, int] = {
    "idea": 0,
    "research": 1,
    "draft": 2,
    "verify": 3,
    "ready_for_approval": 4,
    "approved": 5,
    "executing": 6,
    "completed": 7,
    "measuring": 8,
    "learned": 9,
    "rejected": 7,
    "failed": 7,
}

# Canonical action status → (lifecycle, approval_state, close_run, event)
_SYNC_MAP: dict[str, tuple[str, str, bool, str, str]] = {
    # status: (lifecycle, approval_state, close_run, event_type, message)
    "approved": (
        "approved",
        "APPROVED",
        False,
        "action_approved",
        "Approved by you — ready to execute",
    ),
    "rejected": (
        "rejected",
        "REJECTED",
        True,
        "action_rejected",
        "Campaign proposal was not approved",
    ),
    "executing": (
        "executing",
        "EXECUTING",
        False,
        "execution_started",
        "Campaign execution started",
    ),
    "completed": (
        "completed",
        "COMPLETED",
        True,
        "action_executed",
        "Campaign executed successfully",
    ),
    "failed": (
        "failed",
        "FAILED",
        True,
        "action_failed",
        "Campaign execution failed",
    ),
}


def _enum_value(v: object) -> str:
    return v.value if hasattr(v, "value") else str(v)


# Lifecycle states that still represent a live (non-terminal) proposal.
OPEN_LIFECYCLES = frozenset({"ready_for_approval", "approved", "executing"})
# Canonical action states that still represent a live proposal.
OPEN_ACTION_STATUSES = frozenset({"requested", "approved", "executing"})


def approval_state_for(status: str) -> str:
    """Merchant-facing approval snapshot label for a canonical status."""
    return {
        "requested": "REQUIRED",
        "approved": "APPROVED",
        "executing": "EXECUTING",
        "completed": "COMPLETED",
        "failed": "FAILED",
        "rejected": "REJECTED",
    }.get(status, status.upper())


def find_open_marketing_action(
    db: Session, merchant_id: uuid.UUID, workflow: str | None
) -> tuple[MarketingAGICampaign, AgentAction] | None:
    """Return the newest still-open (merchant, workflow) proposal, if any.

    Canonical identity for idempotency is (merchant, workflow, open) —
    never title/amount/timestamp. A re-run, retry, worker restart, refresh
    or new analysis cycle reuses the open approval gate instead of minting
    a duplicate pending action. Terminal actions (completed/failed/
    rejected) never match, so genuinely new work still creates a fresh
    action. Returns (campaign, action) tenant-verified, or None.
    """
    if not workflow:
        return None
    # Canonical filter is the ACTION status (agent_actions), not the campaign
    # lifecycle mirror — a lifecycle that lagged the approval gate must not
    # cause a duplicate action to be minted on the next run.
    stmt = (
        select(MarketingAGICampaign)
        .where(
            MarketingAGICampaign.merchant_id == merchant_id,
            MarketingAGICampaign.workflow == workflow,
            MarketingAGICampaign.action_id.is_not(None),
        )
        .order_by(MarketingAGICampaign.created_at.desc())
        .limit(20)
    )
    for campaign in db.scalars(stmt).all():
        action = db.get(AgentAction, campaign.action_id)
        if action is None:
            continue
        if action.merchant_id != merchant_id:
            continue
        if _enum_value(action.status) in OPEN_ACTION_STATUSES:
            return campaign, action
    return None


def _find_campaigns(db: Session, action: AgentAction) -> list[MarketingAGICampaign]:
    """All campaigns linked to an action (tenant-verified).

    A reuse run may have linked a second draft row to the SAME open action
    before create-phase idempotency was tightened; every linked row must
    mirror the canonical status so no surface shows a stale lifecycle.
    """
    stmt = (
        select(MarketingAGICampaign)
        .where(
            MarketingAGICampaign.action_id == action.id,
            MarketingAGICampaign.merchant_id == action.merchant_id,
        )
        .order_by(MarketingAGICampaign.created_at.asc())
    )
    campaigns = list(db.scalars(stmt).all())
    if campaigns:
        return campaigns
    # Fallback: the prepare-time payload pointer.
    payload: dict[str, Any] = action.input_payload or {}
    target = payload.get("target") or {}
    campaign_id = target.get("marketing_agi_campaign_id")
    if not campaign_id:
        return []
    try:
        cid = uuid.UUID(str(campaign_id))
    except (ValueError, AttributeError):
        return []
    campaign = db.get(MarketingAGICampaign, cid)
    if campaign is None or campaign.merchant_id != action.merchant_id:
        return []
    # Heal the forward pointer for next time.
    if campaign.action_id is None:
        campaign.action_id = action.id
        db.flush()
    return [campaign]


def _find_campaign(db: Session, action: AgentAction) -> MarketingAGICampaign | None:
    """Primary (oldest) campaign linked to an action, if any."""
    campaigns = _find_campaigns(db, action)
    return campaigns[0] if campaigns else None


def _find_runs(db: Session, action: AgentAction) -> list[MarketingAGIRun]:
    """Every run whose frozen prepared_action points at this action.

    Canonical status changes must update ALL runs that prepared the same
    action (primary + reuse) — not just the newest — so no parked run is
    left showing a stale approval_state.
    """
    stmt = (
        select(MarketingAGIRun)
        .where(MarketingAGIRun.merchant_id == action.merchant_id)
        .order_by(MarketingAGIRun.created_at.asc())
        .limit(50)
    )
    needle = str(action.id)
    found: list[MarketingAGIRun] = []
    # Prefer campaign.run_id when set (authoritative owner).
    primary = _find_campaign(db, action)
    if primary is not None and primary.run_id is not None:
        run = db.get(MarketingAGIRun, primary.run_id)
        if run is not None and run.merchant_id == action.merchant_id:
            found.append(run)
    for run in db.scalars(stmt).all():
        if any(r.id == run.id for r in found):
            continue
        try:
            prepared = (run.state or {}).get("prepared_action") or {}
        except Exception:
            continue
        if prepared.get("action_id") == needle:
            found.append(run)
    return found


def _find_run(db: Session, campaign: MarketingAGICampaign, action: AgentAction) -> MarketingAGIRun | None:
    """Back-compat single-run lookup (oldest matching run)."""
    runs = _find_runs(db, action)
    return runs[0] if runs else None


def _emit_run_event(
    db: Session, run: MarketingAGIRun, event_type: str, message: str, action: AgentAction
) -> None:
    """Append a real run event (next seq) so activity timelines show it.

    Idempotent per (run, event_type, action): a repeated sync for the same
    canonical transition must not mint a duplicate activity row.
    """
    action_key = str(action.id)
    recent = db.scalars(
        select(MarketingAGIEvent)
        .where(MarketingAGIEvent.run_id == run.id)
        .order_by(MarketingAGIEvent.seq.desc())
        .limit(50)
    ).all()
    for existing in recent:
        if (
            existing.event_type == event_type
            and (existing.data or {}).get("action_id") == action_key
        ):
            return
    max_seq = db.scalar(
        select(func.max(MarketingAGIEvent.seq)).where(
            MarketingAGIEvent.run_id == run.id
        )
    )
    event = MarketingAGIEvent(
        run_id=run.id,
        merchant_id=run.merchant_id,
        seq=int(max_seq or 0) + 1,
        phase=run.phase,
        event_type=event_type,
        message=message,
        data={"action_id": action_key},
    )
    db.add(event)
    db.flush()


def _record_execution_learning(
    db: Session, campaign: MarketingAGICampaign, action: AgentAction, status: str
) -> None:
    """Persist the terminal execution result as a learning row.

    This closes the execution → learning gap: externally executed actions
    (via /actions, never via the parked agent loop) previously left their
    result stranded in ``agent_actions.output_payload`` with no
    ``marketing_agi_learnings`` row, so what.im.learning stayed empty
    forever. The row records ONLY the real execution result — business
    outcome measurement (e.g. recovered revenue) stays honestly pending
    until real telemetry exists. Idempotent per (campaign, action):
    existing rows are refreshed, never duplicated; a row the agent
    already measured (actual present + learned) is never overwritten.
    """
    from backend.app.models.marketing_agi import MarketingAGILearning

    output: dict[str, Any] = dict(action.output_payload or {})
    output.setdefault("action_status", status)
    if action.completed_at is not None:
        output.setdefault("completed_at", str(action.completed_at))
    output.setdefault("campaign_lifecycle", campaign.lifecycle)
    if status == "failed":
        if action.error_message:
            output.setdefault("error", action.error_message)
        if getattr(action, "error_code", None):
            output.setdefault("error_code", action.error_code)

    expected: dict[str, Any] = {
        "audience_count": campaign.audience_count,
        "success_metric": campaign.success_metric,
    }
    impact = campaign.expected_impact or {}
    if isinstance(impact, dict) and impact.get("estimated_revenue_inr") is not None:
        expected["estimated_revenue_inr"] = impact.get("estimated_revenue_inr")

    existing = db.scalars(
        select(MarketingAGILearning)
        .where(
            MarketingAGILearning.merchant_id == action.merchant_id,
            MarketingAGILearning.campaign_id == campaign.id,
            MarketingAGILearning.action_id == action.id,
        )
        .order_by(MarketingAGILearning.created_at.desc())
        .limit(1)
    ).first()
    if existing is not None:
        # Never overwrite a measured outcome; only fill a still-empty row.
        if not existing.actual:
            existing.actual = output
        if not existing.insights:
            existing.insights = (
                f"Campaign execution failed — {action.error_message}"
                if status == "failed"
                else "Campaign executed — awaiting outcome measurement "
                "(e.g. recovered revenue)."
            )
        if status == "failed" and existing.status == "measuring":
            existing.status = "measurement_pending"
        db.flush()
        return

    row = MarketingAGILearning(
        merchant_id=action.merchant_id,
        campaign_id=campaign.id,
        action_id=action.id,
        status="measuring",
        expected=expected,
        actual=output,
        insights=(
            f"Campaign execution failed — {action.error_message}"
            if status == "failed"
            else "Campaign executed — awaiting outcome measurement "
            "(e.g. recovered revenue)."
        ),
    )
    if status == "failed":
        row.status = "measurement_pending"
    db.add(row)
    db.flush()


def sync_marketing_from_action(
    db: Session, action: AgentAction
) -> MarketingAGICampaign | None:
    """Mirror a canonical action transition onto marketing rows.

    Safe to call after approve/reject/executing/completed/failed. No-ops
    when the action has no linked marketing campaign. Never commits —
    the caller owns the transaction. Never raises.
    """
    try:
        return _sync_marketing_from_action(db, action)
    except Exception:
        log.exception(
            "Marketing mirror sync failed for action %s (canonical state kept)",
            action.id,
        )
        return None


def _sync_marketing_from_action(
    db: Session, action: AgentAction
) -> MarketingAGICampaign | None:
    status = _enum_value(action.status)
    mapping = _SYNC_MAP.get(status)
    if mapping is None:
        return None  # "requested" and unknown states need no mirror
    lifecycle, approval_state, close_run, event_type, message = mapping

    campaigns = _find_campaigns(db, action)
    if not campaigns:
        return None

    # Forward-only lifecycle mirror on EVERY linked campaign row.
    for campaign in campaigns:
        old_order = _LIFECYCLE_ORDER.get(str(campaign.lifecycle), 0)
        new_order = _LIFECYCLE_ORDER.get(lifecycle, 0)
        if new_order >= old_order:
            campaign.lifecycle = lifecycle
    db.flush()

    runs = _find_runs(db, action)
    if not runs:
        return campaigns[0]

    prepared_snapshot = {
        "action_id": str(action.id),
        "status": status,
        "approval_state": approval_state,
    }
    # Refresh the frozen prepared_action snapshot on EVERY run that
    # prepared this action (reassign — never mutate).
    for run in runs:
        state = dict(run.state or {})
        state["prepared_action"] = prepared_snapshot
        if close_run:
            run.status = "completed"
            run.phase = "complete"
            # Canonical terminal time: the run parked at waiting_approval
            # with completed_at set to the PARK time (_finish stamps it even
            # for waiting_approval). A later approve/execute must advance it
            # to the real terminal time — otherwise Recent Work (which must
            # match the canonical action) shows a stale park timestamp while
            # Live Activity correctly shows Just-now execution events.
            # Prefer the canonical action.completed_at when present so the
            # run and the action agree on ONE persisted terminal instant;
            # never regress an already-newer run timestamp.
            terminal_at = action.completed_at or datetime.now(timezone.utc)
            if terminal_at.tzinfo is None:
                terminal_at = terminal_at.replace(tzinfo=timezone.utc)
            existing = run.completed_at
            if existing is not None and existing.tzinfo is None:
                existing = existing.replace(tzinfo=timezone.utc)
            if existing is None or terminal_at >= existing:
                run.completed_at = terminal_at
            state["reasoning_status"] = "done"
            if status == "failed" and action.error_message:
                errors = list(state.get("errors") or [])
                if f"action_failed: {action.error_message}" not in errors:
                    errors.append(f"action_failed: {action.error_message}")
                state["errors"] = errors
        run.state = state
        db.flush()
        _emit_run_event(db, run, event_type, message, action)

    if status in ("completed", "failed"):
        _record_execution_learning(db, campaigns[0], action, status)

    return campaigns[0]
