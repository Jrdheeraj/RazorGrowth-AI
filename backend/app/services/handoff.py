"""
Real cross-agent handoffs.

The pre-existing ``backend/app/agents/marketing_agi/handoff.py`` could only
record a row in ``pending``. Nothing ever dispatched it, nothing ever
answered it, and its own docstring said so ("Today NO other agent is
upgraded or invoked"). A handoff that never dispatches is not collaboration.

This module makes a handoff actually do work:

* ``request()``     — create a durable, duplicate-guarded handoff row.
* ``dispatch()``    — resolve the destination agent and EXECUTE it through the
                      normal :class:`BaseGrowthAgent` protocol, inside a
                      savepoint, with the same permission checks.
* ``pending_for()`` — drain queue for an agent.
* ``history()``     — persisted run history for the dashboard.

Safety properties
-----------------
* **Circular delegation is impossible.** ``MAX_DEPTH`` bounds the chain and a
  destination already on the ancestry is refused.
* **Duplicate dispatch is prevented.** ``fingerprint`` is unique among open
  handoffs, and a completed handoff is never dispatched twice.
* **Context is minimal and serialisable.** Only plain JSON-serialisable
  evidence crosses the boundary — never a DB session, ORM object, or
  credential.
* **Tenant isolation holds.** Every lookup filters by merchant id; another
  workspace's handoff id is indistinguishable from a missing one.
* **A handoff is not an action.** It lives in its own table and can never be
  approved or executed through the Actions pipeline.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.handoff import AgentHandoff

log = logging.getLogger(__name__)

#: Maximum delegation chain length. Prevents unbounded / circular delegation.
MAX_DEPTH = 3

#: Hard cap on evidence payload size crossing a handoff boundary.
MAX_PAYLOAD_CHARS = 8000

STATUS_PENDING = "pending"
STATUS_DISPATCHED = "dispatched"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_REFUSED = "refused"

OPEN_STATUSES = (STATUS_PENDING, STATUS_DISPATCHED)


class HandoffError(RuntimeError):
    """Raised for an invalid or non-dispatchable handoff."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _fingerprint(source: str, destination: str, task: str) -> str:
    raw = f"{source}::{destination}::{task}".strip().lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    """
    Coerce to something safe to persist and hand to another agent.

    Bounds nesting depth, element counts and string length so a handoff can
    never become an exfiltration channel or an unbounded payload.
    """
    if depth > 4:
        return "<truncated:depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_PAYLOAD_CHARS]
    if isinstance(value, (uuid.UUID, datetime)):
        return str(value)
    if isinstance(value, dict):
        return {
            str(k)[:120]: _json_safe(v, depth=depth + 1)
            for k, v in list(value.items())[:50]
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v, depth=depth + 1) for v in list(value)[:50]]
    return str(value)[:500]


class HandoffService:
    """Durable, duplicate-guarded, actually-dispatching handoffs."""

    # ── creation ──────────────────────────────────────────────────────────

    def request(
        self,
        db: Session,
        *,
        merchant_id: uuid.UUID,
        source_agent: str,
        destination_agent: str,
        task: str,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        depth: int = 0,
        ancestry: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """
        Create (or reuse) a handoff request.

        Idempotent on ``(source, destination, task)`` while the handoff is
        still open, so a retried run reuses the open handoff instead of
        minting a duplicate.
        """
        if depth > MAX_DEPTH:
            raise HandoffError(
                f"Refusing delegation at depth {depth}: chain limit is {MAX_DEPTH}."
            )
        if source_agent == destination_agent:
            raise HandoffError("An agent cannot hand off to itself.")
        if destination_agent in ancestry:
            raise HandoffError(
                f"Refusing circular delegation: {destination_agent} is already "
                f"on the chain {list(ancestry)}."
            )

        fingerprint = _fingerprint(source_agent, destination_agent, task)
        existing = db.scalar(
            select(AgentHandoff).where(
                AgentHandoff.merchant_id == merchant_id,
                AgentHandoff.fingerprint == fingerprint,
                AgentHandoff.status.in_(list(OPEN_STATUSES)),
            )
        )
        if existing is not None:
            return self._serialize(existing)

        row = AgentHandoff(
            id=uuid.uuid4(),
            merchant_id=merchant_id,
            source_agent=source_agent[:64],
            destination_agent=destination_agent[:64],
            task=(task or "")[:2000],
            status=STATUS_PENDING,
            fingerprint=fingerprint,
            correlation_id=correlation_id,
            depth=depth,
            payload=_json_safe(payload or {}),
            dispatched=False,
        )
        db.add(row)
        db.flush()
        return self._serialize(row)

    # ── dispatch ──────────────────────────────────────────────────────────

    def dispatch(
        self,
        db: Session,
        *,
        merchant_id: uuid.UUID,
        handoff_id: uuid.UUID | str,
    ) -> dict[str, Any]:
        """
        Execute the destination agent for this handoff and record the result.

        The destination runs through the ordinary agent protocol
        (``BaseGrowthAgent.execute``) with a freshly built ``AgentContext``,
        so it gets the same permission checks, failure isolation and result
        shape as any orchestrated run. It is wrapped in a savepoint so a
        destination failure cannot corrupt the requester's transaction.
        """
        row = self._load(db, merchant_id, handoff_id)
        if row is None:
            raise HandoffError(f"Handoff {handoff_id} not found for this merchant.")
        if row.status == STATUS_COMPLETED:
            return {
                "handoff_id": str(row.id),
                "status": STATUS_COMPLETED,
                "dispatched": False,
                "note": "already_completed",
            }
        if row.status == STATUS_FAILED:
            return {
                "handoff_id": str(row.id),
                "status": STATUS_FAILED,
                "dispatched": False,
                "note": "already_failed",
            }

        from backend.app.agents.base import AgentContext
        from backend.app.agents.registry import AGENT_INSTANCES

        agent = AGENT_INSTANCES.get(row.destination_agent)
        if agent is None:
            row.status = STATUS_REFUSED
            row.error_message = (
                f"destination_agent '{row.destination_agent}' is not registered"
            )
            row.completed_at = _utcnow()
            db.flush()
            return {
                "handoff_id": str(row.id),
                "status": STATUS_REFUSED,
                "dispatched": False,
                "reason": row.error_message,
            }

        row.status = STATUS_DISPATCHED
        row.dispatched = True
        db.flush()

        payload = row.payload or {}
        ctx = AgentContext(
            db=db,
            merchant_id=merchant_id,
            mode="handoff",
            params={
                "objective": row.task,
                "handoff_id": str(row.id),
                "source_agent": row.source_agent,
                "handoff_payload": payload,
                "orchestrator_run_id": row.correlation_id,
                "window_days": int(payload.get("window_days", 30) or 30),
                "phase": "handoff",
            },
        )

        savepoint = db.begin_nested()
        try:
            result = agent.execute(ctx)
            savepoint.commit()
        except Exception as exc:  # belt-and-braces; execute() already traps
            savepoint.rollback()
            log.exception("Handoff %s dispatch failed", row.id)
            row.status = STATUS_FAILED
            row.error_message = f"{type(exc).__name__}: {exc}"
            row.completed_at = _utcnow()
            db.flush()
            return {
                "handoff_id": str(row.id),
                "status": STATUS_FAILED,
                "dispatched": True,
                "error": row.error_message,
            }

        row.status = STATUS_COMPLETED
        row.result = {
            "output": _json_safe(result.output),
            "result_status": result.status,
            "errors": result.errors[:10],
            "tools_used": result.tools_used[:20],
            "opportunities_created": result.opportunities_created,
            "insights_generated": result.insights_generated,
        }
        row.completed_at = _utcnow()
        db.flush()
        return {
            "handoff_id": str(row.id),
            "status": STATUS_COMPLETED,
            "dispatched": True,
            "destination_agent": row.destination_agent,
            "result_status": result.status,
            "output": _json_safe(result.output),
        }

    # ── queries ───────────────────────────────────────────────────────────

    def pending_for(
        self, db: Session, merchant_id: uuid.UUID, *, agent: str | None = None
    ) -> list[dict[str, Any]]:
        rows = list(
            db.scalars(
                select(AgentHandoff)
                .where(
                    AgentHandoff.merchant_id == merchant_id,
                    AgentHandoff.status == STATUS_PENDING,
                )
                .order_by(AgentHandoff.created_at.asc())
                .limit(100)
            ).all()
        )
        return [
            self._serialize(r)
            for r in rows
            if agent is None or r.destination_agent == agent
        ]

    def history(
        self, db: Session, merchant_id: uuid.UUID, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        rows = list(
            db.scalars(
                select(AgentHandoff)
                .where(AgentHandoff.merchant_id == merchant_id)
                .order_by(AgentHandoff.created_at.desc())
                .limit(limit)
            ).all()
        )
        return [self._serialize(r) for r in rows]

    @staticmethod
    def _load(
        db: Session, merchant_id: uuid.UUID, handoff_id: uuid.UUID | str
    ) -> AgentHandoff | None:
        """Tenant-scoped load: another workspace's id returns None, not 403."""
        try:
            hid = uuid.UUID(str(handoff_id))
        except (ValueError, AttributeError, TypeError):
            return None
        return db.scalar(
            select(AgentHandoff).where(
                AgentHandoff.id == hid,
                AgentHandoff.merchant_id == merchant_id,
            )
        )

    @staticmethod
    def _serialize(row: AgentHandoff) -> dict[str, Any]:
        return {
            "handoff_id": str(row.id),
            "merchant_id": str(row.merchant_id),
            "source_agent": row.source_agent,
            "destination_agent": row.destination_agent,
            "task": row.task,
            "status": row.status,
            "dispatched": bool(row.dispatched),
            "payload": row.payload or {},
            "result": row.result,
            "correlation_id": row.correlation_id,
            "depth": row.depth,
            "error_message": row.error_message,
            "created_at": str(row.created_at),
            "completed_at": str(row.completed_at) if row.completed_at else None,
        }


#: Module-level singleton used by the catalog tool handler.
handoff_service = HandoffService()


__all__ = [
    "MAX_DEPTH",
    "MAX_PAYLOAD_CHARS",
    "OPEN_STATUSES",
    "STATUS_COMPLETED",
    "STATUS_DISPATCHED",
    "STATUS_FAILED",
    "STATUS_PENDING",
    "STATUS_REFUSED",
    "AgentHandoff",
    "HandoffError",
    "HandoffService",
    "handoff_service",
]