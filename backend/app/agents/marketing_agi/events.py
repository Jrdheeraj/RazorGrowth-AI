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

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.marketing_agi import MarketingAGIEvent, MarketingAGIRun

log = logging.getLogger(__name__)


class EventRecorder:
    """Persists real execution events against a run (tenant-scoped)."""

    def __init__(self, db: Session, run: MarketingAGIRun) -> None:
        self._db = db
        self._run = run
        self._seq = 0

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


def list_events(
    db: Session, run_id: uuid.UUID, merchant_id: uuid.UUID, *, after_seq: int = 0
) -> list[MarketingAGIEvent]:
    """Fetch real events for a run, scoped to the caller's tenant."""
    stmt = (
        select(MarketingAGIEvent)
        .where(
            MarketingAGIEvent.run_id == run_id,
            MarketingAGIEvent.merchant_id == merchant_id,
            MarketingAGIEvent.seq > after_seq,
        )
        .order_by(MarketingAGIEvent.seq.asc())
    )
    return list(db.scalars(stmt).all())


def serialize_event(event: MarketingAGIEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "run_id": str(event.run_id),
        "seq": event.seq,
        "phase": event.phase,
        "event_type": event.event_type,
        "message": event.message,
        "data": event.data or {},
        "created_at": str(event.created_at),
    }
