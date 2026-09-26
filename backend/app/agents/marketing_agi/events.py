"""REAL execution events for the MarketingAGI loop.

Every event row corresponds to an actual state change inside the agent
run. The frontend live workstream is rendered exclusively from these
rows — there are no decorative fake progress animations anywhere in the
Marketing AGI UI.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.marketing_agi import MarketingAGIEvent, MarketingAGIRun

log = logging.getLogger(__name__)


class EventRecorder:
    """Persists real execution events against a run (tenant-scoped)."""

    def __init__(self, db: Session, run: MarketingAGIRun) -> None:
        self._db = db
        self._run = run
        # Resume after any events already persisted for this run (worker
        # restart / resumed recorder) — restarting at 0 would collide seq
        # values and silently hide rows behind the frontend after_seq cursor.
        max_seq = db.scalar(
            select(func.max(MarketingAGIEvent.seq)).where(
                MarketingAGIEvent.run_id == run.id
            )
        )
        self._seq = int(max_seq or 0)

    def emit(
        self,
        *,
        phase: str,
        event_type: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> MarketingAGIEvent:
        self._seq += 1
        event = MarketingAGIEvent(
            run_id=self._run.id,
            merchant_id=self._run.merchant_id,   # always the run's tenant
            seq=self._seq,
            phase=phase,
            event_type=event_type,
            message=message,
            data=data,
        )
        self._db.add(event)
        self._db.flush()
        log.info(
            "MarketingAGI run=%s [%s/%s] %s",
            self._run.id, phase, event_type, message,
        )
        return event


_LIFECYCLE_TRANSITIONS: dict[str, str] = {
    "action_prepared": "preparing",
    "awaiting_approval": "waiting_approval",
    "action_approved": "approved",
    "execution_started": "executing",
    "action_executed": "executed",
    "action_failed": "failed",
    "action_rejected": "rejected",
    "action_reused": "reused",
}


def _lifecycle_transition_key(event: MarketingAGIEvent) -> str | None:
    """Canonical lifecycle transition this row represents, or None.

    Several distinct rows can represent ONE logical transition for an
    action — e.g. ``awaiting_approval`` immediately followed by the
    ``run_finished`` park row, or a repeated ``action_approved`` from a
    retried mirror sync. The Live Activity timeline shows exactly ONE
    entry per transition (the earliest row), deduplicated at the query
    source so historical rows stay in the database untouched.
    """
    event_type = event.event_type
    if event_type == "phase_started" and event.phase == "prepare":
        return "preparing"
    if event_type == "run_finished" and "waiting" in (event.message or "").lower():
        # Parking the run is the same transition as awaiting_approval.
        return "waiting_approval"
    return _LIFECYCLE_TRANSITIONS.get(event_type)


def _scope_to_run_action(
    db: Session, run_id: uuid.UUID, events: list[MarketingAGIEvent]
) -> list[MarketingAGIEvent]:
    """Keep only events owned by the run's current logical action.

    Ownership chain (no schema change — already first-class):

        action (agent_actions.id)
          ↕  run.state["prepared_action"]["action_id"]
        run  (marketing_agi_runs.id)
          ↕  event.run_id
        event (marketing_agi_events)

    Lifecycle rows additionally carry ``event.data.action_id`` written by
    ``_phase_prepare`` / ``marketing_action_sync``. Rows stamped with a
    DIFFERENT action than the run now points at belong to prior work on
    this run and must never appear in this action's Live Activity.
    Execution-detail rows (research, tool calls, phase markers) carry no
    action_id and belong to the run — they pass through.
    """
    run = db.get(MarketingAGIRun, run_id)
    if run is None:
        return events
    prepared = ((run.state or {}).get("prepared_action") or {}).get("action_id")
    if not prepared:
        return events
    scoped: list[MarketingAGIEvent] = []
    for event in events:
        event_action = (event.data or {}).get("action_id")
        if event_action is None or event_action == prepared:
            scoped.append(event)
    return scoped


def _dedupe_lifecycle(events: list[MarketingAGIEvent]) -> list[MarketingAGIEvent]:
    """Collapse rows that are the same lifecycle transition.

    Keeps the EARLIEST row per transition (chronological order preserved;
    a completed action keeps its genuine historical "waiting" entry as
    long as it precedes the terminal transitions). Non-lifecycle events
    (tool calls, research, observations) are never collapsed.
    """
    seen: set[str] = set()
    out: list[MarketingAGIEvent] = []
    for event in events:
        key = _lifecycle_transition_key(event)
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        out.append(event)
    return out


def list_events(
    db: Session, run_id: uuid.UUID, merchant_id: uuid.UUID, *, after_seq: int = 0
) -> list[MarketingAGIEvent]:
    """Fetch real events for ONE run/action, scoped to the caller's tenant.

    Pipeline (applied before the after_seq cursor so pagination windows
    can never resurrect a collapsed duplicate):

        tenant+run SQL scope
          → action-ownership scope (run's prepared_action)
          → lifecycle-transition deduplication
          → after_seq cursor
          → order by seq, then created_at (never reorders)

    Ordered by persisted seq, then creation time as a deterministic
    secondary key — the timeline never reorders on frontend assumptions.
    """
    stmt = (
        select(MarketingAGIEvent)
        .where(
            MarketingAGIEvent.run_id == run_id,
            MarketingAGIEvent.merchant_id == merchant_id,
        )
        .order_by(MarketingAGIEvent.seq.asc(), MarketingAGIEvent.created_at.asc())
    )
    rows = list(db.scalars(stmt).all())
    rows = _scope_to_run_action(db, run_id, rows)
    rows = _dedupe_lifecycle(rows)
    return [e for e in rows if e.seq > after_seq]


def serialize_event(event: MarketingAGIEvent) -> dict[str, Any]:
    created = event.created_at
    to_iso = getattr(created, "isoformat", None)
    created_at = str(to_iso()) if callable(to_iso) else str(created)
    return {
        "id": str(event.id),
        "run_id": str(event.run_id),
        "action_id": (event.data or {}).get("action_id"),
        "seq": event.seq,
        "phase": event.phase,
        "event_type": event.event_type,
        "message": event.message,
        "data": event.data or {},
        "created_at": created_at,
    }
