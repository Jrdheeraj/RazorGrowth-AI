"""
Action service — human-in-the-loop approval and execution lifecycle.

Responsibilities:
  - create action (AI proposal)
  - get action
  - list actions for a merchant by status
  - approve action (human merchant only — never the AI agent)
  - reject action (human merchant only)
  - execute approved action (idempotent, double-guardrail-validated)
  - enforce state transitions
  - write audit events at every step
  - return safe structured results

State machine (strictly enforced):

    requested ──approve──▶ approved ──execute──▶ executing ──▶ completed
        │                     │                      │
        └─reject──▶ rejected  └─(guardrail fail)──▶ failed ◀─(executor fail)

Any transition outside this graph is refused with ValueError.
Duplicate execute on a completed action is an idempotent no-op
(audit event action_skipped_idempotent) — it never re-executes.
"""

from __future__ import annotations

import enum
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.enums import AgentActionType, AgentActionStatus, ActorType, AuditEventType
from backend.app.models.agent_action import AgentAction
from backend.app.models.audit_event import AuditEvent
from backend.app.guardrails.policy import (
    evaluate_action,
    ProposedAction,
    GuardrailResult,
    ApprovalStatus,
    RiskLevel,
)
from backend.app.services.action_executor import (
    execute_approved_action,
    ExecutorResult,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Actor identification
# ---------------------------------------------------------------------------

DEVELOPMENT_ACTOR = "dev_user_1"


def _enum_value(v: object) -> str:
    """Return the string value of an Enum member, or the value itself."""
    return v.value if isinstance(v, enum.Enum) else str(v)


# ---------------------------------------------------------------------------
# Guardrail input builder (shared by pre-approval + pre-execution checks)
# ---------------------------------------------------------------------------


def _build_proposed_action(action: AgentAction) -> ProposedAction:
    """Reconstruct a ProposedAction from the stored input payload."""
    payload: dict = action.input_payload or {}
    proposed_amount_raw = payload.get("proposed_amount")
    proposed_amount: Decimal | None = None
    if proposed_amount_raw is not None:
        try:
            proposed_amount = Decimal(str(proposed_amount_raw))
        except Exception:
            proposed_amount = None  # malformed amounts are caught by executors
    return ProposedAction(
        merchant_id=action.merchant_id,
        action_type=_enum_value(action.action_type),
        title=f"{_enum_value(action.action_type)} for merchant {action.merchant_id}",
        reason="Human-approved action execution",
        evidence=payload.get("evidence", []) if isinstance(payload.get("evidence", []), list) else [],
        proposed_amount=proposed_amount,
        target_customer_ids=payload.get("target_customer_ids", []) or [],
        target_product_ids=payload.get("target_product_ids", []) or [],
        metadata=payload.get("metadata", {}) or {},
    )


# ---------------------------------------------------------------------------
# Action service
# ---------------------------------------------------------------------------


def create_action(
    db: Session,
    *,
    merchant_id: uuid.UUID,
    action_type: AgentActionType,
    input_payload: dict | None = None,
    requested_by: str | None = DEVELOPMENT_ACTOR,
) -> AgentAction:
    """
    Create a new AgentAction in 'requested' state.

    The AI agent proposes an action. It must pass through guardrails
    before a human can approve it. The payload is validated against the
    typed schema for the action type — arbitrary JSON is never trusted.
    """
    from backend.app.schemas.action import validate_action_payload

    payload = input_payload or {}
    if payload:
        _, error = validate_action_payload(_enum_value(action_type), {
            **payload, "merchant_id": str(merchant_id),
        })
        if error:
            raise ValueError(f"INVALID_PAYLOAD: {error}")

    action = AgentAction(
        id=uuid.uuid4(),
        merchant_id=merchant_id,
        action_type=action_type,
        status=AgentActionStatus.requested,
        input_payload=payload,
        requested_by=requested_by,
    )
    db.add(action)
    db.flush()

    _write_audit_event(
        db,
        merchant_id,
        ActorType.ai_agent,
        AuditEventType.action_requested,
        str(action.id),
        {
            "action_type": _enum_value(action.action_type),
            "status": _enum_value(action.status),
            "requested_by": action.requested_by,
        },
        actor_id=requested_by,
    )

    log.info(
        "Action created. id=%s merchant=%s type=%s status=%s",
        str(action.id), merchant_id, _enum_value(action.action_type), _enum_value(action.status),
    )
    return action


def get_action(db: Session, action_id: uuid.UUID) -> AgentAction | None:
    """Retrieve a single action by ID."""
    return db.get(AgentAction, action_id)


def list_actions_by_status(
    db: Session,
    merchant_id: uuid.UUID | None = None,
    status: AgentActionStatus | None = None,
) -> list[AgentAction]:
    """List actions, optionally filtered by merchant and/or status."""
    stmt = select(AgentAction)
    if merchant_id is not None:
        stmt = stmt.where(AgentAction.merchant_id == merchant_id)
    if status is not None:
        stmt = stmt.where(AgentAction.status == status)
    stmt = stmt.order_by(AgentAction.created_at.desc())
    result = db.execute(stmt)
    return list(result.scalars().all())


# Backwards-compatible helpers -------------------------------------------------

def list_pending_actions(db: Session, merchant_id: uuid.UUID) -> list[AgentAction]:
    """Return all actions for a merchant that are in 'requested' state."""
    return list_actions_by_status(db, merchant_id, AgentActionStatus.requested)


def list_approved_actions(db: Session, merchant_id: uuid.UUID) -> list[AgentAction]:
    """Return all approved actions for a merchant."""
    return list_actions_by_status(db, merchant_id, AgentActionStatus.approved)


def list_executing_actions(db: Session, merchant_id: uuid.UUID) -> list[AgentAction]:
    """Return all executing actions for a merchant."""
    return list_actions_by_status(db, merchant_id, AgentActionStatus.executing)


# ---------------------------------------------------------------------------
# Human approval / rejection
# ---------------------------------------------------------------------------


class ActionNotFoundError(LookupError):
    """Raised when the referenced action does not exist."""


class InvalidTransitionError(ValueError):
    """Raised when a state transition violates the lifecycle graph."""


def approve_action(
    db: Session, action_id: uuid.UUID, actor: str = DEVELOPMENT_ACTOR
) -> AgentAction:
    """
    Transition action from 'requested' to 'approved'.

    HUMAN-ONLY: this must only ever be invoked from the merchant-facing
    approval endpoint — never from an AI agent tool.

    Guardrails are evaluated BEFORE approval. A guardrail rejection blocks
    approval entirely; the action stays in 'requested' so a human can
    review and reject it.
    """
    action = db.get(AgentAction, action_id)
    if not action:
        raise ActionNotFoundError(f"Action {action_id} not found")

    if action.status != AgentActionStatus.requested:
        raise InvalidTransitionError(
            f"INVALID_ACTION_STATE: action is '{_enum_value(action.status)}', "
            f"cannot approve. Only 'requested' actions may be approved."
        )

    # ─── Guardrail evaluation before approval ────────────────────────────
    guardrail_result = evaluate_action(
        _build_proposed_action(action), db=db, action_id=str(action.id)
    )
    if guardrail_result.is_rejected:
        log.warning(
            "Approval blocked by guardrails. id=%s merchant=%s reason=%s",
            str(action.id), action.merchant_id, guardrail_result.rejection_reason,
        )
        raise InvalidTransitionError(
            f"GUARDRAIL_REJECTED: {guardrail_result.rejection_reason}"
        )

    action.status = AgentActionStatus.approved
    action.approved_by = actor
    db.flush()

    _write_audit_event(
        db,
        action.merchant_id,
        ActorType.merchant_user,
        AuditEventType.action_approved,
        str(action.id),
        {
            "action_type": _enum_value(action.action_type),
            "approved_by": action.approved_by,
        },
        actor_id=actor,
    )

    log.info(
        "Action approved. id=%s merchant=%s actor=%s",
        str(action.id), action.merchant_id, actor,
    )
    return action


def reject_action(
    db: Session, action_id: uuid.UUID, actor: str = DEVELOPMENT_ACTOR
) -> AgentAction:
    """Transition action from 'requested' to 'rejected'. HUMAN-ONLY."""
    action = db.get(AgentAction, action_id)
    if not action:
        raise ActionNotFoundError(f"Action {action_id} not found")

    if action.status != AgentActionStatus.requested:
        raise InvalidTransitionError(
            f"INVALID_ACTION_STATE: action is '{_enum_value(action.status)}', "
            f"cannot reject. Only 'requested' actions may be rejected."
        )

    action.status = AgentActionStatus.rejected
    db.flush()

    _write_audit_event(
        db,
        action.merchant_id,
        ActorType.merchant_user,
        AuditEventType.action_rejected,
        str(action.id),
        {
            "action_type": _enum_value(action.action_type),
            "rejected_by": actor,
        },
        actor_id=actor,
    )

    log.info(
        "Action rejected. id=%s merchant=%s actor=%s",
        str(action.id), action.merchant_id, actor,
    )
    return action


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def execute_action(
    db: Session,
    action_id: uuid.UUID,
    *,
    actor: str = DEVELOPMENT_ACTOR,
) -> ExecutorResult:
    """
    Execute an approved action.

    Enforced workflow (order matters):
      1. Action exists                                   → ACTION_NOT_FOUND
      2. Merchant ownership                              → MERCHANT_ACCESS_DENIED
      3. Terminal/concurrency checks (idempotency):
           completed → idempotent skip (never re-execute, audit event)
           executing → concurrent-execution block
           rejected/failed/requested → invalid state (approval cannot be bypassed)
      4. status == approved else INVALID_ACTION_STATE
      5. Double guardrail: re-evaluated immediately before execution;
         on failure → action transitions to failed, audit event written,
         NO side effect occurs.
      6. Status → executing (audit event action_started)
      7. Run executor
      8. Status → completed / failed (audit event)
    """
    action = db.get(AgentAction, action_id)
    if not action:
        return ExecutorResult(success=False, error="ACTION_NOT_FOUND")

    # ─── Merchant ownership check ────────────────────────────────────────
    if action.merchant_id is None:
        log.warning(
            "Execution denied — action %s has no merchant owner.", str(action.id)
        )
        return ExecutorResult(success=False, error="MERCHANT_ACCESS_DENIED")

    # ─── Idempotency & terminal-state checks (BEFORE anything else) ──────
    if action.status == AgentActionStatus.completed:
        # Duplicate execute → safe no-op. Never perform the action twice.
        log.info(
            "Idempotent skip — action already completed. id=%s merchant=%s",
            str(action.id), action.merchant_id,
        )
        _write_audit_event(
            db,
            action.merchant_id,
            ActorType.merchant_user,
            AuditEventType.action_skipped_idempotent,
            str(action.id),
            {
                "action_type": _enum_value(action.action_type),
                "previous_status": AgentActionStatus.completed.value,
                "requested_by": actor,
            },
            actor_id=actor,
        )
        return ExecutorResult(
            success=True,
            result_metadata={
                "idempotent": True,
                "previous_status": AgentActionStatus.completed.value,
                "note": "Action already completed — duplicate execute is a safe no-op.",
            },
        )

    if action.status in (
        AgentActionStatus.executing,
        AgentActionStatus.rejected,
        AgentActionStatus.failed,
        AgentActionStatus.requested,
    ):
        reasons = {
            AgentActionStatus.executing: "ACTION_ALREADY_EXECUTING",
            AgentActionStatus.requested: "INVALID_ACTION_STATE: action is 'requested', expected 'approved'. Approval cannot be bypassed.",
            AgentActionStatus.rejected: "INVALID_ACTION_STATE: action is 'rejected', expected 'approved'",
            AgentActionStatus.failed: "INVALID_ACTION_STATE: action is 'failed', expected 'approved'",
        }
        error = reasons[action.status]
        log.info("Execution blocked. id=%s merchant=%s — %s", str(action.id), action.merchant_id, error)
        return ExecutorResult(
            success=False,
            error=error,
            result_metadata={"previous_status": _enum_value(action.status)},
        )

    if action.status != AgentActionStatus.approved:
        return ExecutorResult(
            success=False,
            error=f"INVALID_ACTION_STATE: action is '{_enum_value(action.status)}', expected 'approved'",
        )

    # ─── Double guardrail: re-evaluate immediately before execution ──────
    guardrail_result = evaluate_action(
        _build_proposed_action(action), db=db, action_id=str(action.id)
    )
    if guardrail_result.is_rejected:
        action.status = AgentActionStatus.failed
        action.error_code = "GUARDRAIL_REJECTED"
        action.error_message = guardrail_result.rejection_reason or "Guardrail re-evaluation rejected the action"
        action.completed_at = datetime.now(timezone.utc)
        db.flush()

        _write_audit_event(
            db,
            action.merchant_id,
            ActorType.system,
            AuditEventType.action_failed,
            str(action.id),
            {
                "action_type": _enum_value(action.action_type),
                "error": action.error_message,
                "stage": "pre_execution_guardrail",
            },
            actor_id="guardrail_policy",
        )

        log.warning(
            "Action execution blocked by guardrails. id=%s merchant=%s reason=%s",
            str(action.id), action.merchant_id, action.error_message,
        )
        return ExecutorResult(success=False, error=action.error_message)

    # ─── Status → executing ──────────────────────────────────────────────
    action.status = AgentActionStatus.executing
    db.flush()

    _write_audit_event(
        db,
        action.merchant_id,
        ActorType.merchant_user,
        AuditEventType.action_started,
        str(action.id),
        {
            "action_type": _enum_value(action.action_type),
            "executed_by": actor,
        },
        actor_id=actor,
    )

    # ─── Run the executor ────────────────────────────────────────────────
    try:
        exec_result = execute_approved_action(action, db=db)
    except Exception as exc:
        # Executor crashed — record a real failure, never a fake success.
        log.exception("Executor raised for action %s", str(action.id))
        exec_result = ExecutorResult(success=False, error=f"EXECUTION_ERROR: {exc}")

    if exec_result.success:
        action.status = AgentActionStatus.completed
        action.output_payload = exec_result.result_metadata or {}
        action.error_code = None
        action.error_message = None
        action.completed_at = datetime.now(timezone.utc)

        _write_audit_event(
            db,
            action.merchant_id,
            ActorType.merchant_user,
            AuditEventType.action_completed,
            str(action.id),
            {
                "action_type": _enum_value(action.action_type),
                "result": exec_result.result_metadata,
            },
            actor_id=actor,
        )

        log.info(
            "Action completed. id=%s merchant=%s result=%s",
            str(action.id), action.merchant_id, exec_result.result_metadata,
        )
    else:
        action.status = AgentActionStatus.failed
        action.error_code = exec_result.error or "EXECUTION_FAILED"
        action.error_message = exec_result.error or "Execution failed"
        action.completed_at = datetime.now(timezone.utc)

        _write_audit_event(
            db,
            action.merchant_id,
            ActorType.merchant_user,
            AuditEventType.action_failed,
            str(action.id),
            {
                "action_type": _enum_value(action.action_type),
                "error": action.error_message,
            },
            actor_id=actor,
        )

        log.error(
            "Action failed. id=%s merchant=%s error=%s",
            str(action.id), action.merchant_id, action.error_message,
        )

    return exec_result


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


def _write_audit_event(
    db: Session,
    merchant_id: uuid.UUID,
    actor_type: ActorType,
    event_type: AuditEventType,
    entity_id: str,
    payload: dict,
    actor_id: str | None = None,
) -> None:
    """Append an immutable audit event. Never raises."""
    try:
        evt = AuditEvent(
            merchant_id=merchant_id,
            actor_type=actor_type,
            actor_id=actor_id or actor_type.value,
            event_type=event_type,
            entity_type="agent_action",
            entity_id=entity_id,
            payload=payload,
        )
        db.add(evt)
        db.flush()
    except Exception as exc:
        log.warning("Failed to write audit event %s: %s", event_type, exc)
