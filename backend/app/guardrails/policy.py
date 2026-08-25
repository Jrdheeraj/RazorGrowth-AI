"""
Money-action guardrails — Phase 3.

Every AI-proposed action that involves money MUST pass through this module
before it can be executed.  Default outcome: REQUIRES_APPROVAL.

The guardrail chain:
    1. PolicyValidator   — is this action type permitted at all?
    2. RiskValidator     — what is the risk classification?
    3. AmountValidator   — does the proposed amount stay within bounds?
    4. ApprovalGate      — always set status = requires_approval

No financial action is executed here.  Execution belongs to Phase 4+
and must happen only after a human merchant has explicitly approved.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from backend.app.core.config import get_settings
from backend.app.models.enums import ApprovalStatus, RiskLevel

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Action types that the guardrail layer understands
# ─────────────────────────────────────────────────────────────────────────────

PERMITTED_ACTION_TYPES: frozenset[str] = frozenset(
    {
        "send_campaign",
        "create_discount",
        "retry_payment",
        "generate_opportunity",
    }
)

# Actions that always require human approval regardless of amount
HIGH_RISK_ACTIONS: frozenset[str] = frozenset(
    {
        "retry_payment",
        "create_discount",
    }
)


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ProposedAction:
    """
    A proposed action produced by the AI agent.

    This object is the input to the guardrail chain.
    It is NEVER executed autonomously.
    """
    merchant_id: uuid.UUID
    action_type: str
    title: str
    reason: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    proposed_amount: Decimal | None = None          # INR if applicable
    target_customer_ids: list[str] = field(default_factory=list)
    target_product_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class GuardrailResult:
    """
    Output of the guardrail chain for one proposed action.

    Always starts as REQUIRES_APPROVAL.  Can be rejected immediately by
    policy/risk/amount validators.  Approval itself happens externally.
    """
    action_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    merchant_id: str = ""
    action_type: str = ""
    title: str = ""
    reason: str = ""

    # Evaluation outcome
    approval_status: ApprovalStatus = ApprovalStatus.requires_approval
    risk_level: RiskLevel = RiskLevel.low
    rejection_reason: str | None = None

    # Amount bounds
    proposed_amount: Decimal | None = None
    max_allowed_amount: Decimal | None = None

    # Audit fields
    evidence: list[dict[str, Any]] = field(default_factory=list)
    policy_checks_passed: list[str] = field(default_factory=list)
    policy_checks_failed: list[str] = field(default_factory=list)
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None    # approval window

    @property
    def is_approved(self) -> bool:
        return self.approval_status == ApprovalStatus.approved

    @property
    def is_rejected(self) -> bool:
        return self.approval_status == ApprovalStatus.rejected

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "merchant_id": self.merchant_id,
            "action_type": self.action_type,
            "title": self.title,
            "reason": self.reason,
            "approval_status": self.approval_status.value,
            "risk_level": self.risk_level.value,
            "rejection_reason": self.rejection_reason,
            "proposed_amount": float(self.proposed_amount) if self.proposed_amount else None,
            "max_allowed_amount": float(self.max_allowed_amount) if self.max_allowed_amount else None,
            "policy_checks_passed": self.policy_checks_passed,
            "policy_checks_failed": self.policy_checks_failed,
            "evaluated_at": self.evaluated_at.isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Validator chain
# ─────────────────────────────────────────────────────────────────────────────

class PolicyValidator:
    """Check that the action type is in the permitted set."""

    def validate(self, action: ProposedAction, result: GuardrailResult) -> bool:
        if action.action_type not in PERMITTED_ACTION_TYPES:
            result.approval_status = ApprovalStatus.rejected
            result.rejection_reason = (
                f"Action type '{action.action_type}' is not permitted in Phase 3. "
                f"Permitted: {sorted(PERMITTED_ACTION_TYPES)}"
            )
            result.policy_checks_failed.append("permitted_action_types")
            log.warning(
                "Guardrail REJECTED: unknown action type %r for merchant %s",
                action.action_type, action.merchant_id,
            )
            return False
        result.policy_checks_passed.append("permitted_action_types")
        return True


class RiskValidator:
    """Classify risk and escalate high-risk actions."""

    def validate(self, action: ProposedAction, result: GuardrailResult) -> bool:
        if action.action_type in HIGH_RISK_ACTIONS:
            result.risk_level = RiskLevel.high
        elif action.proposed_amount and action.proposed_amount > Decimal("10000"):
            result.risk_level = RiskLevel.medium
        else:
            result.risk_level = RiskLevel.low

        # All actions require approval — no auto-execution
        result.policy_checks_passed.append("risk_classification")
        log.info(
            "Guardrail risk classification: action=%r risk=%s merchant=%s",
            action.action_type, result.risk_level.value, action.merchant_id,
        )
        return True


class AmountValidator:
    """Reject actions whose proposed amount exceeds the configured maximum."""

    def validate(self, action: ProposedAction, result: GuardrailResult) -> bool:
        settings = get_settings()
        max_amount = Decimal(str(settings.GUARDRAIL_MAX_AMOUNT_INR))
        result.max_allowed_amount = max_amount

        if action.proposed_amount is None:
            result.policy_checks_passed.append("amount_within_bounds")
            return True

        result.proposed_amount = action.proposed_amount
        if action.proposed_amount > max_amount:
            result.approval_status = ApprovalStatus.rejected
            result.rejection_reason = (
                f"Proposed amount INR {action.proposed_amount} exceeds maximum "
                f"allowed INR {max_amount}. Requires manual review."
            )
            result.policy_checks_failed.append("amount_within_bounds")
            log.warning(
                "Guardrail REJECTED: amount INR %s > max INR %s for merchant %s",
                action.proposed_amount, max_amount, action.merchant_id,
            )
            return False

        result.policy_checks_passed.append("amount_within_bounds")
        return True


class ApprovalGate:
    """Final gate — always sets status to requires_approval (never auto-approves)."""

    def validate(self, action: ProposedAction, result: GuardrailResult) -> bool:
        settings = get_settings()
        if settings.GUARDRAIL_REQUIRE_APPROVAL and not result.is_rejected:
            result.approval_status = ApprovalStatus.requires_approval
        result.policy_checks_passed.append("approval_gate")
        return True


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def _write_guardrail_audit(db: Any, action: ProposedAction, result: GuardrailResult) -> None:
    """
    Persist the guardrail outcome as an immutable audit event.

    Never raises — an audit-write failure must never block evaluation.
    Payload contains no secrets (see GuardrailResult.to_dict()).
    """
    try:
        from backend.app.models.audit_event import AuditEvent
        from backend.app.models.enums import ActorType, AuditEventType

        evt = AuditEvent(
            merchant_id=action.merchant_id,
            actor_type=ActorType.ai_agent,
            actor_id="guardrail_policy",
            event_type=(
                AuditEventType.guardrail_rejected
                if result.is_rejected
                else AuditEventType.guardrail_evaluated
            ),
            entity_type="proposed_action",
            entity_id=result.action_id,
            payload=result.to_dict(),
        )
        db.add(evt)
        db.flush()
    except Exception as exc:
        log.warning("Failed to write guardrail audit event: %s", exc)


def evaluate_action(
    action: ProposedAction,
    *,
    db: Any | None = None,
    action_id: str | None = None,
) -> GuardrailResult:
    """
    Run the full guardrail chain for a proposed action.

    Args:
        action: the AI-proposed action to evaluate.
        db:     optional SQLAlchemy session. When provided, the outcome is
                appended to the audit trail (guardrail_evaluated /
                guardrail_rejected) associated with action.merchant_id.
        action_id: optional external identifier. When provided it becomes
                the GuardrailResult.action_id so the audit record is linked
                to the real AgentAction row instead of a random id.

    Returns a GuardrailResult whose approval_status is one of:
      - requires_approval  (default — needs human sign-off)
      - rejected           (policy/amount violation — never execute)

    The result is always rejected or requires_approval.
    No action is executed here.  Execution requires Phase 4+.
    """
    result = GuardrailResult(
        merchant_id=str(action.merchant_id),
        action_type=action.action_type,
        title=action.title,
        reason=action.reason,
        evidence=action.evidence,
    )
    if action_id is not None:
        result.action_id = action_id

    validators = [
        PolicyValidator(),
        RiskValidator(),
        AmountValidator(),
        ApprovalGate(),
    ]

    for validator in validators:
        ok = validator.validate(action, result)
        if not ok:
            # Chain stops on first hard failure
            break

    if db is not None:
        _write_guardrail_audit(db, action, result)

    log.info(
        "Guardrail evaluation complete. action=%r status=%s risk=%s merchant=%s",
        action.action_type,
        result.approval_status.value,
        result.risk_level.value,
        action.merchant_id,
    )
    return result
