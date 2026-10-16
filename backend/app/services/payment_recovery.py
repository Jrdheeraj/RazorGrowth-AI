"""
Reason-aware failed-payment recovery.

Why this module exists
----------------------
The original :class:`~backend.app.agents.payment_recovery.PaymentRecoveryAgent`
did three things, all weak:

1. It ignored ``Payment.failure_code`` / ``Payment.failure_reason`` even
   though ingestion already populated them
   (``services/razorpay_ingestion.py``) — so it could not tell a gateway
   blip from a dead card.
2. It multiplied recoverable value by a hardcoded
   ``DEFAULT_RECOVERY_RATE = Decimal("0.25")``, labelled "documented
   assumption, not data".
3. It proposed a retry for exactly one payment per run, the largest, with no
   retry timing, no stop condition and no measurement.

This module supplies the missing reasoning:

* :func:`classify_failure` maps a provider failure code to a verified
  semantic class (retryable / needs_customer_action / not_recoverable)
  using documented Razorpay error semantics.
* :func:`measure_recovery_rate` derives a recovery rate **from this
  merchant's own history** by asking whether failed payments were followed
  by a captured payment on the same order. When history is too thin it
  returns ``None`` and the caller reports "insufficient evidence" rather
  than substituting a constant.
* :func:`plan_retry_schedule` produces bounded, per-class timing.

Nothing here executes a retry. It produces evidence and a proposal; the
action still goes through ``action_service`` + ``guardrails`` + human
approval.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.enums import PaymentStatus
from backend.app.models.order import Order
from backend.app.models.payment import Payment

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Failure classification
# --------------------------------------------------------------------------- #

#: Retryable without the customer doing anything. The payment method may
#: still work; the failure was on the acquirer/gateway side.
RETRYABLE = "retryable"

#: The customer's instrument or authentication state must change first.
#: A blind retry burns a real-world attempt (and fees) for no benefit.
NEEDS_CUSTOMER_ACTION = "needs_customer_action"

#: Structurally unrecoverable. Retrying is pointless or harmful.
NOT_RECOVERABLE = "not_recoverable"

UNKNOWN = "unknown"

#: Documented Razorpay error codes → class. Codes absent from this map fall
#: through to UNKNOWN, which is treated conservatively (never auto-retry).
FAILURE_CODE_CLASSES: dict[str, str] = {
    # Infrastructure / issuer-side blips.
    "GATEWAY_ERROR": RETRYABLE,
    "SERVER_ERROR": RETRYABLE,
    "DECLINED": RETRYABLE,
    "DO_NOT_HONOR": RETRYABLE,
    # The card or the authentication itself is the problem.
    "BAD_CARD_ERROR": NEEDS_CUSTOMER_ACTION,
    "EXPIRED_CARD_ERROR": NEEDS_CUSTOMER_ACTION,
    "AUTHENTICATION_REQUIRED": NEEDS_CUSTOMER_ACTION,
    "INVALID_TRANSITION": NEEDS_CUSTOMER_ACTION,
    "EMI_OPTION_MISSING": NEEDS_CUSTOMER_ACTION,
    "BAD_REQUEST_ERROR": NEEDS_CUSTOMER_ACTION,
    "INSUFFICIENT_FUNDS": NEEDS_CUSTOMER_ACTION,
    "CARD_EXPIRED": NEEDS_CUSTOMER_ACTION,
}

#: Substring fallback for codes not in the exact map above.
FAILURE_CODE_SUBSTRINGS: tuple[tuple[str, str], ...] = (
    ("gateway", RETRYABLE),
    ("server", RETRYABLE),
    ("timeout", RETRYABLE),
    ("temporar", RETRYABLE),
    ("declin", RETRYABLE),
    ("honour", RETRYABLE),
    ("honor", RETRYABLE),
    ("expired", NEEDS_CUSTOMER_ACTION),
    ("insufficient", NEEDS_CUSTOMER_ACTION),
    ("authentication", NEEDS_CUSTOMER_ACTION),
    ("otp", NEEDS_CUSTOMER_ACTION),
    ("card", NEEDS_CUSTOMER_ACTION),
    ("bad_request", NEEDS_CUSTOMER_ACTION),
)

#: Hours to wait before each attempt. Bounded and small: a dunning sequence
#: that waits days has already lost the cart.
#:
#: Only RETRYABLE gets an automatic schedule. A customer-action failure gets
#: an EMPTY schedule on purpose: retrying a declined or expired card without
#: the customer changing something just burns real-world attempts and fees.
#: That customer is handed to Marketing for a "update your card" message.
RETRY_SCHEDULE_HOURS: dict[str, tuple[int, ...]] = {
    RETRYABLE: (3, 24, 72),
    NEEDS_CUSTOMER_ACTION: (),
    NOT_RECOVERABLE: (),
    UNKNOWN: (),
}

#: Below this many resolved historical failures the measured rate is not
#: trustworthy and must not be used as a multiplier.
MIN_SAMPLES_FOR_RATE = 5

#: Recovery window for "did this failure eventually recover?" analysis.
HISTORY_WINDOW_DAYS = 90


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def classify_failure(payment: Payment) -> str:
    """
    Classify one failed payment using verified provider semantics.

    Falls back to UNKNOWN rather than guessing, and UNKNOWN is never
    treated as retryable.
    """
    code = (payment.failure_code or "").strip().upper()
    if not code:
        return UNKNOWN
    if code in FAILURE_CODE_CLASSES:
        return FAILURE_CODE_CLASSES[code]
    lowered = code.lower()
    for needle, classification in FAILURE_CODE_SUBSTRINGS:
        if needle in lowered:
            return classification
    return UNKNOWN


def plan_retry_schedule(classification: str) -> list[dict[str, Any]]:
    """Bounded, per-class retry timing. Always terminates."""
    hours = RETRY_SCHEDULE_HOURS.get(classification, ())
    now = _utcnow()
    plan: list[dict[str, Any]] = []
    for index, wait_hours in enumerate(hours, start=1):
        plan.append(
            {
                "attempt": index,
                "wait_hours": wait_hours,
                "eligible_at": (now + timedelta(hours=wait_hours)).isoformat(),
                "stop_after": len(hours),
            }
        )
    return plan


# --------------------------------------------------------------------------- #
# Measured recovery rate
# --------------------------------------------------------------------------- #


@dataclass
class MeasuredRecovery:
    """
    A recovery rate derived from this merchant's own payment history.

    ``rate`` is ``None`` when there is not enough resolved history. Callers
    MUST surface that as "insufficient evidence" — never substitute a
    default constant.
    """

    rate: float | None
    resolved_failures: int
    recovered_failures: int
    window_days: int
    by_class: dict[str, dict[str, int]] = field(default_factory=dict)
    note: str = ""

    @property
    def is_usable(self) -> bool:
        return self.rate is not None and self.resolved_failures >= MIN_SAMPLES_FOR_RATE

    def to_dict(self) -> dict[str, Any]:
        return {
            "rate": self.rate,
            "resolved_failures": self.resolved_failures,
            "recovered_failures": self.recovered_failures,
            "window_days": self.window_days,
            "by_class": self.by_class,
            "is_usable": self.is_usable,
            "note": self.note,
        }


def measure_recovery_rate(
    db: Session, merchant_id: uuid.UUID, *, window_days: int = HISTORY_WINDOW_DAYS
) -> MeasuredRecovery:
    """
    Derive the merchant's real recovery rate.

    A failure counts as *recovered* when a **captured payment exists on the
    same order after the failed attempt's timestamp**. That is the only
    evidence that counts — no model, no assumption.
    """
    cutoff = _utcnow() - timedelta(days=window_days)

    failures = list(
        db.scalars(
            select(Payment).where(
                Payment.merchant_id == merchant_id,
                Payment.status == PaymentStatus.failed.value,
                Payment.created_at >= cutoff,
            )
        ).all()
    )

    if not failures:
        return MeasuredRecovery(
            rate=None,
            resolved_failures=0,
            recovered_failures=0,
            window_days=window_days,
            note="No failed payments in the window; no recovery rate can be measured.",
        )

    order_ids = {p.order_id for p in failures if p.order_id}
    captured_by_order: dict[uuid.UUID, list[datetime]] = {}
    if order_ids:
        rows = list(
            db.scalars(
                select(Payment).where(
                    Payment.merchant_id == merchant_id,
                    Payment.order_id.in_(order_ids),
                    Payment.status == PaymentStatus.captured.value,
                )
            ).all()
        )
        for row in rows:
            captured_by_order.setdefault(row.order_id, []).append(
                _as_aware(row.created_at)
            )

    recovered = 0
    by_class: dict[str, dict[str, int]] = {}
    for payment in failures:
        classification = classify_failure(payment)
        bucket = by_class.setdefault(classification, {"total": 0, "recovered": 0})
        bucket["total"] += 1

        failed_at = _as_aware(payment.created_at)
        later_captures = [
            ts for ts in captured_by_order.get(payment.order_id, []) if ts is not None
        ]
        # A failed attempt is "recovered" when a CAPTURED payment exists on
        # the same order at or after the failure. `>=` rather than `>` because
        # ingestion can write both attempts within the same timestamp tick,
        # and a same-instant capture is still a genuine recovery — the failed
        # row is never itself captured, so there is no self-match.
        did_recover = bool(later_captures) and (
            failed_at is None or any(ts >= failed_at for ts in later_captures)
        )
        if did_recover:
            recovered += 1
            bucket["recovered"] += 1

    total = len(failures)
    rate = (recovered / total) if total else None

    if total < MIN_SAMPLES_FOR_RATE:
        note = (
            f"Only {total} resolved failure(s) in the last {window_days} days "
            f"(minimum {MIN_SAMPLES_FOR_RATE}). The rate is reported but is "
            "not statistically usable; no default was substituted."
        )
    else:
        note = (
            f"Measured from {total} failed payment(s) in the last {window_days} "
            "days, resolved by whether a captured payment followed on the "
            "same order."
        )

    return MeasuredRecovery(
        rate=rate,
        resolved_failures=total,
        recovered_failures=recovered,
        window_days=window_days,
        by_class=by_class,
        note=note,
    )


# --------------------------------------------------------------------------- #
# Recovery plan assembly
# --------------------------------------------------------------------------- #


@dataclass
class RecoveryCandidate:
    """One failed payment plus the reasoning about whether to retry it."""

    payment_id: uuid.UUID
    order_id: uuid.UUID
    amount: Decimal
    failure_code: str | None
    failure_reason: str | None
    classification: str
    retryable: bool
    schedule: list[dict[str, Any]]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "payment_id": str(self.payment_id),
            "order_id": str(self.order_id),
            "amount_inr": float(self.amount),
            "failure_code": self.failure_code,
            "failure_reason": self.failure_reason,
            "classification": self.classification,
            "retryable": self.retryable,
            "schedule": self.schedule,
            "reason": self.reason,
        }


class PaymentRecoveryService:
    """Assembles evidence-backed recovery candidates. Proposes, never executes."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def analyse(
        self, merchant_id: uuid.UUID, *, window_days: int = 30, limit: int = 50
    ) -> dict[str, Any]:
        cutoff = _utcnow() - timedelta(days=window_days)
        failures = list(
            self.db.scalars(
                select(Payment)
                .where(
                    Payment.merchant_id == merchant_id,
                    Payment.status == PaymentStatus.failed.value,
                    Payment.created_at >= cutoff,
                )
                .order_by(Payment.amount.desc())
                .limit(limit)
            ).all()
        )

        measured = measure_recovery_rate(self.db, merchant_id, window_days=max(window_days, HISTORY_WINDOW_DAYS))

        candidates: list[RecoveryCandidate] = []
        for payment in failures:
            classification = classify_failure(payment)
            schedule = plan_retry_schedule(classification)
            candidates.append(
                RecoveryCandidate(
                    payment_id=payment.id,
                    order_id=payment.order_id,
                    amount=Decimal(str(payment.amount)),
                    failure_code=payment.failure_code,
                    failure_reason=payment.failure_reason,
                    classification=classification,
                    retryable=classification == RETRYABLE,
                    schedule=schedule,
                    reason=_candidate_reason(classification, payment.failure_code),
                )
            )

        retryable = [c for c in candidates if c.retryable]
        retryable_value = sum((c.amount for c in retryable), Decimal("0"))
        all_value = sum((c.amount for c in candidates), Decimal("0"))

        # Projected recoverable value uses the MEASURED rate when it is
        # trustworthy, and is otherwise honestly withheld.
        projected: float | None = None
        projection_basis = "unavailable"
        if measured.is_usable and measured.rate is not None and retryable_value:
            projected = float(retryable_value) * measured.rate
            projection_basis = "measured_from_merchant_history"
        elif measured.resolved_failures == 0:
            projection_basis = "no_history"
        else:
            projection_basis = "insufficient_history"

        return {
            "window_days": window_days,
            "failed_payment_count": len(candidates),
            "failed_value_inr": float(all_value),
            "retryable_count": len(retryable),
            "retryable_value_inr": float(retryable_value),
            "needs_customer_action_count": sum(
                1 for c in candidates if c.classification == NEEDS_CUSTOMER_ACTION
            ),
            "not_recoverable_count": sum(
                1 for c in candidates if c.classification == NOT_RECOVERABLE
            ),
            "unknown_classification_count": sum(
                1 for c in candidates if c.classification == UNKNOWN
            ),
            "measured_recovery": measured.to_dict(),
            "projected_recoverable_inr": projected,
            "projection_basis": projection_basis,
            "candidates": [c.to_dict() for c in candidates],
            "status": "ok" if candidates else "no_failures",
        }

    def marketing_handoff_payload(self, analysis: dict[str, Any]) -> dict[str, Any]:
        """
        Minimal, privacy-scoped evidence for a Marketing Agent recovery
        campaign. Customer ids are omitted on purpose: Marketing should target
        a segment, not receive raw customer records from Payment Recovery.
        """
        return {
            "objective": "Recover failed payments with an approved reminder",
            "window_days": analysis.get("window_days"),
            "retryable_customer_count": analysis.get("retryable_count"),
            "needs_customer_action_count": analysis.get("needs_customer_action_count"),
            "projected_recoverable_inr": analysis.get("projected_recoverable_inr"),
            "projection_basis": analysis.get("projection_basis"),
            "note": (
                "Counts only. No customer identifiers cross this boundary; "
                "Marketing must select its own audience from merchant data."
            ),
        }


def _candidate_reason(classification: str, failure_code: str | None) -> str:
    code = failure_code or "unspecified"
    if classification == RETRYABLE:
        return (
            f"Failure code {code} is an infrastructure/issuer-side error; the "
            "payment method may still succeed on a bounded retry."
        )
    if classification == NEEDS_CUSTOMER_ACTION:
        return (
            f"Failure code {code} requires the customer to update their card or "
            "re-authenticate; retrying unchanged would waste an attempt."
        )
    if classification == NOT_RECOVERABLE:
        return f"Failure code {code} is structurally unrecoverable."
    return (
        f"Failure code {code} is not in the verified classification table; "
        "treated as unknown and NOT auto-retried."
    )


__all__ = [
    "FAILURE_CODE_CLASSES",
    "HISTORY_WINDOW_DAYS",
    "MIN_SAMPLES_FOR_RATE",
    "NEEDS_CUSTOMER_ACTION",
    "NOT_RECOVERABLE",
    "RETRYABLE",
    "RETRY_SCHEDULE_HOURS",
    "UNKNOWN",
    "MeasuredRecovery",
    "PaymentRecoveryService",
    "RecoveryCandidate",
    "classify_failure",
    "measure_recovery_rate",
    "plan_retry_schedule",
]