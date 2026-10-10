"""REAL execution events for the Product Agent loop.

Same contract as the Marketing Agent's recorder — one persisted row per
actual state change, a monotonically increasing ``seq`` that resumes after
existing rows, and tenant identity taken from the run (never from an
argument). The dashboard's activity feed is rendered exclusively from these
rows: there is no manufactured activity anywhere in the Product Agent UI.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.product_agi import ProductAgentEvent, ProductAgentRun

log = logging.getLogger(__name__)


class EventRecorder:
    """Persists real execution events against a Product Agent run."""

    def __init__(self, db: Session, run: ProductAgentRun) -> None:
        self._db = db
        self._run = run
        max_seq = db.scalar(
            select(func.max(ProductAgentEvent.seq)).where(
                ProductAgentEvent.run_id == run.id
            )
        )
        self._seq = int(max_seq or 0)

    @property
    def run(self) -> ProductAgentRun:
        return self._run

    def emit(
        self,
        *,
        stage: str,
        event_type: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> ProductAgentEvent:
        self._seq += 1
        event = ProductAgentEvent(
            run_id=self._run.id,
            merchant_id=self._run.merchant_id,   # always the run's tenant
            seq=self._seq,
            stage=stage,
            event_type=event_type,
            message=message,
            data=data,
        )
        self._db.add(event)
        self._db.flush()
        log.info(
            "ProductAgent run=%s [%s/%s] %s",
            self._run.id, stage, event_type, message,
        )
        return event


def list_events(
    db: Session,
    run_id: uuid.UUID,
    merchant_id: uuid.UUID,
    *,
    after_seq: int = 0,
    limit: int = 500,
) -> list[ProductAgentEvent]:
    """Fetch real events for ONE run, scoped to the caller's tenant.

    Tenant + run scope happens in SQL, then the ``after_seq`` cursor is
    applied to the ordered rows. Ordering is by persisted ``seq`` then
    ``created_at`` so the timeline never reorders on frontend assumptions.
    """
    stmt = (
        select(ProductAgentEvent)
        .where(
            ProductAgentEvent.run_id == run_id,
            ProductAgentEvent.merchant_id == merchant_id,
        )
        .order_by(
            ProductAgentEvent.seq.asc(), ProductAgentEvent.created_at.asc()
        )
        .limit(max(1, min(int(limit), 2000)))
    )
    rows = list(db.scalars(stmt).all())
    return [e for e in rows if e.seq > int(after_seq)]


def serialize_event(event: ProductAgentEvent) -> dict[str, Any]:
    created = event.created_at
    to_iso = getattr(created, "isoformat", None)
    return {
        "id": str(event.id),
        "run_id": str(event.run_id),
        "seq": event.seq,
        "stage": event.stage,
        "event_type": event.event_type,
        "message": event.message,
        "data": event.data or {},
        "created_at": str(to_iso()) if callable(to_iso) else str(created),
    }


__all__ = ["EventRecorder", "list_events", "serialize_event"]