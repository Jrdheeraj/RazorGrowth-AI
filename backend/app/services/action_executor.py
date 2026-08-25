"""
Safe execution engine for Phase 4 agent actions.

CRITICAL REQUIREMENTS:
- NO arbitrary tool execution.
- Executor may ONLY execute explicitly supported action types.
- Unknown action type → reject safely → audit → never execute.
- Idempotency: duplicate executes produce no-op result
  (enforced by the state machine in action_service.execute_action).
- Double guardrail: guardrails re-evaluated immediately before execution
  (enforced by action_service BEFORE this module is invoked).
- Real Razorpay execution remains disabled by default (RAZORPAY_ENABLED=false).
  When disabled, retry_payment returns a clear non-success result —
  a fake/simulated payment success is NEVER recorded.
- Test-mode executors label their output explicitly (mode="test") and never
  claim that a real external side effect occurred.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from backend.app.core.config import get_settings
from backend.app.guardrails.policy import GuardrailResult
from backend.app.schemas.action import (
    SendCampaignPayload,
    CreateDiscountPayload,
    RetryPaymentPayload,
    GenerateOpportunityPayload,
    validate_action_payload,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Executor result
# ---------------------------------------------------------------------------


class ExecutorResult:
    """Structured result from an action executor."""

    def __init__(
        self,
        success: bool,
        error: str | None = None,
        result_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.success = success
        self.error = error
        self.result_metadata = result_metadata or {}


def _validated_payload(schema_name: str, action: Any) -> tuple[Any | None, str | None]:
    """
    Validate the stored input payload against its typed schema.
    Returns (payload_instance, error_message). Defense-in-depth: payloads may
    have been written directly to the DB, so they are re-validated here even
    though create_action already validates them at creation time.
    """
    raw = dict(action.input_payload or {})
    raw["merchant_id"] = str(action.merchant_id)
    return validate_action_payload(schema_name, raw)


# ---------------------------------------------------------------------------
# Executor registry
# ---------------------------------------------------------------------------


class BaseActionExecutor:
    """All concrete executors must subclass this."""

    action_type: str  # must match AgentActionType.value
    payload_schema: str  # schema name used by validate_action_payload

    def execute(self, action: Any, db: Any) -> ExecutorResult:
        """Execute the action. Must return ExecutorResult."""
        raise NotImplementedError()


class SendCampaignExecutor(BaseActionExecutor):
    """Executor for send_campaign actions."""

    action_type = "send_campaign"
    payload_schema = "send_campaign"

    def execute(self, action: Any, db: Any) -> ExecutorResult:
        ok, err = _validated_payload(self.payload_schema, action)
        if not ok:
            return ExecutorResult(success=False, error=f"INVALID_PAYLOAD: {err}")
        payload = SendCampaignPayload.model_validate(ok.model_dump())
        campaign_type = payload.campaign_type
        target_count = payload.target_count

        settings = get_settings()
        if settings.CAMPAIGN_MAX_TARGET is not None and target_count > settings.CAMPAIGN_MAX_TARGET:
            return ExecutorResult(
                success=False,
                error=f"CAMPAIGN_TARGET_EXCEEDS_LIMIT: {target_count} > max {settings.CAMPAIGN_MAX_TARGET}",
            )

        # TEST MODE ONLY — no external message is ever sent from here.
        # The result metadata states this explicitly so nothing upstream can
        # mistake it for a real delivery.
        return ExecutorResult(
            success=True,
            result_metadata={
                "campaign_type": campaign_type,
                "target_count": target_count,
                "mode": "test",
                "sent": False,
                "execution": f"test_campaign_{campaign_type}",
                "note": "Development/test mode — no external message sent",
            },
        )


class CreateDiscountExecutor(BaseActionExecutor):
    """Executor for create_discount actions."""

    action_type = "create_discount"
    payload_schema = "create_discount"

    def execute(self, action: Any, db: Any) -> ExecutorResult:
        ok, err = _validated_payload(self.payload_schema, action)
        if not ok:
            return ExecutorResult(success=False, error=f"INVALID_PAYLOAD: {err}")
        payload = CreateDiscountPayload.model_validate(ok.model_dump())

        settings = get_settings()

        # ─── Percentage limits ───────────────────────────────────────────
        pct: Decimal = payload.percentage
        if pct <= 0:
            return ExecutorResult(success=False, error="DISCOUNT_MUST_BE_POSITIVE")
        if pct > 100:
            return ExecutorResult(success=False, error="DISCOUNT_CANNOT_EXCEED_100_PCT")
        max_pct = settings.DISCOUNT_MAX_PERCENTAGE
        if pct > Decimal(str(max_pct)):
            return ExecutorResult(
                success=False,
                error=f"DISCOUNT_EXCEEDS_MAX_PERCENTAGE: {pct}% > max {max_pct}%",
            )

        # ─── Amount limits (optional proposed_amount) ────────────────────
        if payload.proposed_amount is not None:
            try:
                pa = Decimal(str(payload.proposed_amount))
            except (InvalidOperation, TypeError, ValueError):
                return ExecutorResult(success=False, error="INVALID_DISCOUNT_AMOUNT")
            discount_max = Decimal(str(settings.DISCOUNT_MAX_AMOUNT_INR))
            guardrail_max = Decimal(str(settings.GUARDRAIL_MAX_AMOUNT_INR))
            if pa < 0:
                return ExecutorResult(success=False, error="INVALID_DISCOUNT_AMOUNT")
            if pa > discount_max:
                return ExecutorResult(
                    success=False,
                    error=f"DISCOUNT_AMOUNT_EXCEEDS_LIMIT: INR {pa} > max INR {discount_max}",
                )
            if pa > guardrail_max:
                return ExecutorResult(
                    success=False,
                    error=f"DISCOUNT_AMOUNT_EXCEEDS_GUARDRAIL: INR {pa} > max INR {guardrail_max}",
                )

        discount_id = f"discount_{action.id}"
        return ExecutorResult(
            success=True,
            result_metadata={
                "discount_id": discount_id,
                "percentage": float(pct),
                "mode": "test",
                "created": False,
                "execution": "test_discount",
                "note": "Development/test mode — no real discount created",
            },
        )


class RetryPaymentExecutor(BaseActionExecutor):
    """Executor for retry_payment actions."""

    action_type = "retry_payment"
    payload_schema = "retry_payment"

    def execute(self, action: Any, db: Any) -> ExecutorResult:
        ok, err = _validated_payload(self.payload_schema, action)
        if not ok:
            return ExecutorResult(success=False, error=f"INVALID_PAYLOAD: {err}")
        payment_id = ok.payment_id

        settings = get_settings()
        if not settings.RAZORPAY_ENABLED:
            # Disabled → clear, safe NON-success. No fake payment success is
            # recorded anywhere; the action transitions to failed upstream.
            return ExecutorResult(
                success=False,
                error="RAZORPAY_DISABLED",
                result_metadata={
                    "payment_id": payment_id,
                    "razorpay_enabled": False,
                    "note": "Real Razorpay execution is disabled "
                    "(RAZORPAY_ENABLED=false). Nothing was charged or retried.",
                },
            )

        if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
            return ExecutorResult(
                success=False,
                error="RAZORPAY_NOT_CONFIGURED",
                result_metadata={
                    "payment_id": payment_id,
                    "note": "RAZORPAY_ENABLED=true but RAZORPAY_KEY_ID/"
                    "RAZORPAY_KEY_SECRET are not configured. Nothing was retried.",
                },
            )

        # Live retry path intentionally unimplemented until Phase 5+.
        # Returning fake success here would fabricate a real-world payment —
        # refuse honestly instead.
        return ExecutorResult(
            success=False,
            error="RAZORPAY_LIVE_RETRY_NOT_IMPLEMENTED",
            result_metadata={"payment_id": payment_id},
        )


class GenerateOpportunityExecutor(BaseActionExecutor):
    """Executor for generate_opportunity actions."""

    action_type = "generate_opportunity"
    payload_schema = "generate_opportunity"

    def execute(self, action: Any, db: Any) -> ExecutorResult:
        ok, err = _validated_payload(self.payload_schema, action)
        if not ok:
            return ExecutorResult(success=False, error=f"INVALID_PAYLOAD: {err}")

        from backend.app.models.enums import OpportunityType, OpportunityStatus
        from backend.app.repositories.opportunity import GrowthOpportunityRepository

        payload = GenerateOpportunityPayload.model_validate(ok.model_dump())

        try:
            opp_type = OpportunityType(payload.opportunity_type)
        except ValueError:
            valid = sorted(t.value for t in OpportunityType)
            return ExecutorResult(
                success=False,
                error=f"UNSUPPORTED_OPPORTUNITY_TYPE: '{payload.opportunity_type}'. Valid types: {valid}",
            )

        repo = GrowthOpportunityRepository(db)

        # Deterministic key → duplicate executes cannot create duplicate rows.
        opportunity_key = payload.opportunity_key or f"gen-{action.id}"

        # Idempotency: same key returns the existing opportunity.
        existing = repo.get_by_key(action.merchant_id, opportunity_key)
        if existing is not None:
            return ExecutorResult(
                success=True,
                result_metadata={
                    "opportunity_id": str(existing.id),
                    "opportunity_key": existing.opportunity_key,
                    "idempotent": True,
                    "note": "Duplicate prevention — existing opportunity returned",
                },
            )

        new_opp = repo.create(
            merchant_id=action.merchant_id,
            opportunity_key=opportunity_key,
            type=opp_type,
            title=payload.title,
            description=payload.description or None,
            confidence=Decimal(str(payload.confidence)),
            expected_revenue=Decimal(str(payload.expected_revenue)),
            target_customer_count=payload.target_customer_count,
            reasoning=payload.reasoning,
            status=OpportunityStatus.pending_approval,
        )
        db.flush()

        return ExecutorResult(
            success=True,
            result_metadata={
                "opportunity_id": str(new_opp.id),
                "opportunity_key": new_opp.opportunity_key,
                "type": str(getattr(new_opp.type, "value", new_opp.type)),
                "status": str(getattr(new_opp.status, "value", new_opp.status)),
                "execution": "generate_opportunity",
            },
        )


# ---------------------------------------------------------------------------
# Executor dispatcher
# ---------------------------------------------------------------------------

_executor_registry: dict[str, BaseActionExecutor] = {
    "send_campaign": SendCampaignExecutor(),
    "create_discount": CreateDiscountExecutor(),
    "retry_payment": RetryPaymentExecutor(),
    "generate_opportunity": GenerateOpportunityExecutor(),
}


def get_executor(action_type: str) -> BaseActionExecutor | None:
    """Return the executor for the given action type, or None."""
    return _executor_registry.get(action_type)


def execute_approved_action(action: Any, db: Any) -> ExecutorResult:
    """
    Dispatch to the correct executor for the action's type.

    If the action type has no registered executor → safe rejection.
    """
    action_type = str(getattr(action.action_type, "value", action.action_type))
    executor = get_executor(action_type)
    if executor is None:
        log.warning(
            "No executor registered for action type %r. "
            "Action ID=%s merchant=%s will not execute.",
            action_type,
            action.id,
            action.merchant_id,
        )
        return ExecutorResult(
            success=False,
            error=f"UNKNOWN_ACTION_TYPE: '{action_type}' has no registered executor",
        )

    result = executor.execute(action, db)
    log.info(
        "Executor %s for action type %s result: success=%s error=%s",
        type(executor).__name__,
        action_type,
        result.success,
        result.error,
    )
    return result
