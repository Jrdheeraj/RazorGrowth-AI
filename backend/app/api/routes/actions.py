"""
Action API endpoints — Phase 4 human-in-the-loop approval and execution.

Endpoints (final paths after the /api application prefix):
  GET    /api/actions                                  — analyst+
  GET    /api/actions/{action_id}                      — analyst+
  POST   /api/actions/{action_id}/approve              — owner/admin ONLY
  POST   /api/actions/{action_id}/reject               — owner/admin ONLY
  POST   /api/actions/{action_id}/execute              — operator+ (still guardrailed)
  GET    /api/actions/{action_id}/audit                — analyst+

The router below declares prefix="/actions" ONLY; the "/api" prefix is added
exactly once in main.py via include_router(prefix="/api").

Approval/rejection are HUMAN-ONLY operations, restricted to admin/owner
roles via merchant membership. Agents are not users and can never hold a
membership or role; there is no agent login path.

All routes resolve tenant identity from the authenticated security context.
A supplied merchant_id that does not match an active membership of the
caller is rejected with 403 MERCHANT_ACCESS_DENIED (Phase 4 contract).
"""

from __future__ import annotations

import enum
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.deps import (
    MerchantContext,
    approver_ctx,
    merchant_ctx,
    operator_ctx,
)
from backend.app.db.session import get_db
from backend.app.services.action_service import (
    approve_action,
    reject_action,
    execute_action,
    get_action,
    list_actions_by_status,
    DEVELOPMENT_ACTOR,
    ActionNotFoundError,
    InvalidTransitionError,
)
from backend.app.schemas.action import (
    ActionResponse,
    ActionListResponse,
    ActionTransitionResponse,
    AuditEventResponse,
    AuditEventListResponse,
    ExecutionResponse,
)
from backend.app.models.enums import AgentActionStatus, ActorType
from backend.app.models.agent_action import AgentAction

log = logging.getLogger(__name__)

router = APIRouter(prefix="/actions", tags=["actions"])


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------


def _parse_action_id(action_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(action_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid action_id format")


def _enum_value(v: object) -> str:
    return v.value if isinstance(v, enum.Enum) else str(v)


def _actor_label(ctx: MerchantContext) -> str:
    """Audit actor identity: user id when authenticated, dev actor otherwise."""
    if ctx.authenticated and ctx.user is not None:
        return f"user:{ctx.user.id}"
    return DEVELOPMENT_ACTOR


def _verify_tenant_access(action: AgentAction, ctx: MerchantContext) -> None:
    """
    Enforce merchant ownership.

    Authenticated: the action MUST belong to the caller's membership
    merchant. Anonymous (optional dev mode): legacy behaviour — reject only
    when an explicit non-matching merchant_id was supplied; otherwise the
    action is served regardless of owner (pre-auth development semantics).
    """
    if ctx.authenticated:
        if action.merchant_id != ctx.merchant_id:
            # Do not disclose existence of other tenants' actions.
            raise HTTPException(status_code=403, detail="MERCHANT_ACCESS_DENIED")
        return
    # Legacy anonymous path preserved for development tooling.
    if ctx.explicit_merchant and action.merchant_id != ctx.merchant_id:
        raise HTTPException(status_code=403, detail="MERCHANT_ACCESS_DENIED")


def _action_to_response(action: AgentAction) -> dict[str, Any]:
    return {
        "id": str(action.id),
        "merchant_id": str(action.merchant_id),
        "action_type": _enum_value(action.action_type),
        "status": _enum_value(action.status),
        "requested_by": action.requested_by,
        "approved_by": action.approved_by,
        "input_payload": action.input_payload,
        "output_payload": action.output_payload,
        "error_code": action.error_code,
        "error_message": action.error_message,
        "completed_at": str(action.completed_at) if action.completed_at else None,
        "created_at": str(action.created_at),
    }


# -------------------------------------------------------------------------
# GET /api/actions — list actions, optionally filtered by status
# -------------------------------------------------------------------------


@router.get("", response_model=ActionListResponse)
def list_actions(
    status: str | None = None,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """
    List actions for the caller's merchant (tenant-isolated).

    Anonymous optional-mode callers without an explicit merchant keep the
    legacy unfiltered listing for development tooling.
    """
    status_enum: AgentActionStatus | None = None
    if status is not None:
        try:
            status_enum = AgentActionStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    if not ctx.authenticated and not ctx.explicit_merchant:
        mid: uuid.UUID | None = None  # legacy development behaviour
    else:
        mid = ctx.merchant_id

    actions = list_actions_by_status(db, mid, status_enum)

    return {"actions": [_action_to_response(a) for a in actions]}


# -------------------------------------------------------------------------
# GET /api/actions/{action_id}
# -------------------------------------------------------------------------


@router.get("/{action_id}", response_model=ActionResponse)
def get_action_route(
    action_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Retrieve a single action by ID (tenant-isolated)."""
    aid = _parse_action_id(action_id)

    action = get_action(db, aid)
    if not action:
        raise HTTPException(status_code=404, detail="ACTION_NOT_FOUND")

    _verify_tenant_access(action, ctx)
    return _action_to_response(action)


# -------------------------------------------------------------------------
# POST /api/actions/{action_id}/approve — HUMAN OWNER/ADMIN ONLY
# -------------------------------------------------------------------------


@router.post("/{action_id}/approve", response_model=ActionTransitionResponse)
def approve_action_route(
    action_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(approver_ctx),
) -> Any:
    """
    Transition action from 'requested' to 'approved'.

    HUMAN-ONLY and restricted to owner/admin roles. Guardrails are evaluated
    before approval; a guardrail rejection blocks approval with 400.
    No role and no token can bypass this endpoint's guardrail evaluation.
    """
    aid = _parse_action_id(action_id)

    action = get_action(db, aid)
    if not action:
        raise HTTPException(status_code=404, detail="ACTION_NOT_FOUND")
    _verify_tenant_access(action, ctx)

    try:
        action = approve_action(db, aid, actor=_actor_label(ctx))
    except ActionNotFoundError:
        db.rollback()
        raise HTTPException(status_code=404, detail="ACTION_NOT_FOUND")
    except InvalidTransitionError as exc:
        # Persist any audit evidence written before the refusal
        # (e.g. guardrail_rejected), then surface the error.
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()

    return {
        "id": str(action.id),
        "action_type": _enum_value(action.action_type),
        "status": _enum_value(action.status),
        "requested_by": action.requested_by,
        "approved_by": action.approved_by,
        "rejected_by": None,
        "merchant_id": str(action.merchant_id),
        "created_at": str(action.created_at),
    }


# -------------------------------------------------------------------------
# POST /api/actions/{action_id}/reject — HUMAN OWNER/ADMIN ONLY
# -------------------------------------------------------------------------


@router.post("/{action_id}/reject", response_model=ActionTransitionResponse)
def reject_action_route(
    action_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(approver_ctx),
) -> Any:
    """Transition action from 'requested' to 'rejected'. Human owner/admin only."""
    aid = _parse_action_id(action_id)

    action = get_action(db, aid)
    if not action:
        raise HTTPException(status_code=404, detail="ACTION_NOT_FOUND")
    _verify_tenant_access(action, ctx)

    try:
        action = reject_action(db, aid, actor=_actor_label(ctx))
    except ActionNotFoundError:
        db.rollback()
        raise HTTPException(status_code=404, detail="ACTION_NOT_FOUND")
    except InvalidTransitionError as exc:
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()

    return {
        "id": str(action.id),
        "action_type": _enum_value(action.action_type),
        "status": _enum_value(action.status),
        "requested_by": action.requested_by,
        "approved_by": None,
        "rejected_by": _actor_label(ctx),
        "merchant_id": str(action.merchant_id),
        "created_at": str(action.created_at),
    }


# -------------------------------------------------------------------------
# POST /api/actions/{action_id}/execute — operator+ behind double guardrail
# -------------------------------------------------------------------------


@router.post("/{action_id}/execute", response_model=ExecutionResponse)
def execute_action_route(
    action_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(operator_ctx),
) -> Any:
    """
    Execute an approved action (operator role or above).

    Enforced by action_service.execute_action regardless of who calls:
      1. Action exists
      2. Tenant ownership
      3. Idempotency / terminal-state checks (never re-executes)
      4. status == approved (approval cannot be bypassed by ANY role)
      5. Double guardrail immediately before execution (cannot be bypassed)
      6. Status → executing → completed / failed
      7. Audit events at each stage
    """
    aid = _parse_action_id(action_id)

    action = get_action(db, aid)
    if not action:
        raise HTTPException(status_code=404, detail="ACTION_NOT_FOUND")
    _verify_tenant_access(action, ctx)

    result = execute_action(db, aid, actor=_actor_label(ctx))

    # Persist the terminal transition (completed/failed/idempotent-skip)
    # and its audit events before responding.
    db.commit()

    if result.success:
        refreshed = get_action(db, aid)
        return {
            "action_id": str(aid),
            "action_type": _enum_value(refreshed.action_type),
            "status": _enum_value(refreshed.status),
            "result": result.result_metadata,
            "message": (
                "Duplicate execute ignored (idempotent no-op)"
                if result.result_metadata.get("idempotent")
                else "Action executed successfully"
            ),
        }

    # Failure — the service has already persisted the failed transition
    # and written the audit event. Surface a structured error.
    raise HTTPException(
        status_code=400,
        detail={
            "error": result.error or "EXECUTION_FAILED",
            "action_id": str(aid),
            "metadata": result.result_metadata or {},
        },
    )


# -------------------------------------------------------------------------
# GET /api/actions/{action_id}/audit
# -------------------------------------------------------------------------


@router.get("/{action_id}/audit", response_model=AuditEventListResponse)
def get_action_audit(
    action_id: str,
    db: Session = Depends(get_db),
    ctx: MerchantContext = Depends(merchant_ctx),
) -> Any:
    """Retrieve the audit trail for an action (tenant-isolated)."""
    aid = _parse_action_id(action_id)

    action = get_action(db, aid)
    if not action:
        raise HTTPException(status_code=404, detail="ACTION_NOT_FOUND")
    _verify_tenant_access(action, ctx)

    from backend.app.models.audit_event import AuditEvent

    stmt = (
        select(AuditEvent)
        .where(AuditEvent.entity_id == str(aid))
        .order_by(AuditEvent.created_at.desc())
    )
    events = list(db.execute(stmt).scalars().all())

    return {
        "audit_events": [
            {
                "id": str(e.id),
                "event_type": _enum_value(e.event_type),
                "actor_type": _enum_value(e.actor_type),
                "actor_id": e.actor_id,
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "payload": e.payload,
                "created_at": str(e.created_at),
            }
            for e in events
        ]
    }
