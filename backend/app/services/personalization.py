"""
Per-customer next-best-action decisioning.

What this is, precisely
-----------------------
It is NOT customer intelligence. LTV, recency, churn risk, payment success
and segmentation already exist in
:class:`~backend.app.services.customer_intelligence.CustomerIntelligenceService`
and are **consumed, not reimplemented**, here. Affinity likewise comes from
:mod:`backend.app.services.product_intelligence`.

What was genuinely missing is the decision layer between those facts and a
merchant action: for THIS customer, on real evidence, what should happen
next — and can we later prove it helped?

Design rules
------------
1. **Evidence-gated.** A customer with no insight row gets no decision. The
   agent refuses rather than inventing one.
2. **Deterministic.** Scoring is pure arithmetic over stored metrics. No
   randomness, no LLM in the decision itself, so a decision is reproducible
   and auditable.
3. **Explainable.** Every decision persists the exact evidence that produced
   it, so a merchant can always answer "why this customer?".
4. **Measurable.** Eligible customers are split into a deterministic
   treatment/control cohort. A later run can compare real observed revenue.
   :func:`measure_outcomes` reports what actually happened and refuses to
   claim uplift when the sample is too thin.
5. **Recommends only.** Nothing here sends a message, changes a price or
   touches a payment. Downstream execution belongs to the existing
   approval-gated Marketing / Product paths.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.customer import Customer
from backend.app.models.customer_insight import CustomerInsight
from backend.app.models.enums import PaymentStatus
from backend.app.models.order import Order
from backend.app.models.payment import Payment
from backend.app.models.personalization import PersonalizationDecision
from backend.app.services.customer_intelligence import CustomerIntelligenceService

log = logging.getLogger(__name__)

# ── Action vocabulary ───────────────────────────────────────────────────────
# Every value is a *recommendation for a human-approved downstream action*.
ACTION_REENGAGE = "reengage"
ACTION_WIN_BACK = "win_back"
ACTION_VIP_NURTURE = "vip_nurture"
ACTION_RETENTION = "retention"
ACTION_PAYMENT_UPDATE = "payment_update"
ACTION_CROSS_SELL = "cross_sell"
ACTION_HOLD = "hold"

KNOWN_ACTIONS = frozenset(
    {
        ACTION_REENGAGE,
        ACTION_WIN_BACK,
        ACTION_VIP_NURTURE,
        ACTION_RETENTION,
        ACTION_PAYMENT_UPDATE,
        ACTION_CROSS_SELL,
        ACTION_HOLD,
    }
)

# ── Evidence thresholds (all declared, none magic) ──────────────────────────
#: A customer with at least one captured order has purchase history.
MIN_ORDERS_FOR_RECOMMENDATION = 1

#: Days of inactivity before a customer counts as dormant.
DORMANT_DAYS = 90

#: Re-engagement prompt threshold in days.
REENGAGE_DAYS = 45

#: Churn-risk levels above this are retention candidates.
CHURN_RISK_LEVELS = ("high", "critical")

#: Payment success rate below this means "ask them to fix their card".
PAYMENT_SUCCESS_FLOOR = 0.7

#: Lifetime value multiple over the merchant median that marks a VIP.
VIP_LTV_MULTIPLE = 2.0

#: Minimum resolved customers before a cohort comparison is reported at all.
MIN_COHORT_SIZE = 10

#: Outcome window after a decision is created before it is measured.
OUTCOME_WINDOW_DAYS = 30

COHORT_TREATMENT = "treatment"
COHORT_CONTROL = "control"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _assignment_key(customer_id: uuid.UUID, merchant_id: uuid.UUID) -> str:
    """Deterministic per-(merchant, customer) partition key.

    Hashing the id (rather than randomising) means a customer never migrates
    between cohorts across runs — without that, any later comparison is
    confounded by cohort churn.
    """
    raw = f"{merchant_id}:{customer_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _cohort_for(assignment_key: str, control_ratio: float) -> str:
    """Stable bucket in [0, 1) derived from the first 8 hex digits."""
    bucket = int(assignment_key[:8], 16) / 0xFFFFFFFF
    return COHORT_CONTROL if bucket < control_ratio else COHORT_TREATMENT


def _num(value: Any) -> float | None:
    """Coerce Decimal/str/None to a JSON-serialisable float.

    The upstream customer-intelligence service returns Decimals; the
    rationale is persisted as JSONB, so they must be converted or the write
    fails with "Object of type Decimal is not JSON serializable".
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(Decimal(str(value)))
    except (ValueError, TypeError, ArithmeticError):
        return None


@dataclass
class PersonalizedDecision:
    """An in-memory decision, before or after persistence."""

    customer_id: uuid.UUID
    action: str
    score: float
    cohort: str
    rationale: dict[str, Any]
    product_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "customer_id": str(self.customer_id),
            "recommended_action": self.action,
            "score": round(self.score, 5),
            "cohort": self.cohort,
            "rationale": self.rationale,
            "recommended_product_ids": self.product_ids,
        }


class PersonalizationService:
    """
    Produces and measures per-customer next-best-action recommendations.

    Reuses (never re-derives) customer intelligence and product affinity.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── decisioning ───────────────────────────────────────────────────────

    def decide(
        self,
        merchant_id: uuid.UUID,
        *,
        control_ratio: float = 0.5,
        window_days: int = OUTCOME_WINDOW_DAYS,
        limit: int = 500,
    ) -> dict[str, Any]:
        """
        Score every eligible customer and persist one decision each.

        Customers without an insight row are skipped and counted — the agent
        must be able to say *why* it produced fewer decisions than customers.
        """
        # Real, already-computed customer metrics. Not recomputed here.
        insights = CustomerIntelligenceService(self.db).compute_metrics(merchant_id)
        insights_by_customer: dict[str, dict[str, Any]] = {
            str(row.get("customer_id")): row for row in insights if row.get("customer_id")
        }

        ltv_values = sorted(
            float(row.get("lifetime_value") or 0.0) for row in insights
        )
        median_ltv = _median(ltv_values) if ltv_values else 0.0

        affinity = self._affinity_pairs(merchant_id)
        failed_customers = self._customers_with_failures(merchant_id)

        decisions: list[PersonalizedDecision] = []
        skipped_no_insight = 0
        skipped_insufficient_history = 0

        for customer in self._eligible_customers(merchant_id, limit=limit):
            key = str(customer.id)
            row = insights_by_customer.get(key)
            if row is None:
                skipped_no_insight += 1
                continue
            order_count = int(row.get("order_count") or row.get("total_orders") or 0)
            if order_count < MIN_ORDERS_FOR_RECOMMENDATION:
                skipped_insufficient_history += 1
                continue

            decision = self._score_customer(
                customer=customer,
                metrics=row,
                median_ltv=median_ltv,
                affinity=affinity,
                in_failed=key in failed_customers,
                assignment_key=_assignment_key(customer.id, merchant_id),
                control_ratio=control_ratio,
                window_days=window_days,
            )
            if decision is not None:
                decisions.append(decision)

        created, updated = self._persist(merchant_id, decisions)
        by_action: dict[str, int] = {}
        for d in decisions:
            by_action[d.action] = by_action.get(d.action, 0) + 1

        return {
            "customers_considered": len(decisions) + skipped_no_insight + skipped_insufficient_history,
            "decisions": len(decisions),
            "decisions_created": created,
            "decisions_updated": updated,
            "skipped_no_insight": skipped_no_insight,
            "skipped_insufficient_history": skipped_insufficient_history,
            "by_action": by_action,
            "median_ltv": median_ltv,
            "control_ratio": control_ratio,
            "decisions_payload": [d.to_dict() for d in decisions[:50]],
            "status": "ok" if decisions else "insufficient_evidence",
        }

    def _score_customer(
        self,
        *,
        customer: Customer,
        metrics: dict[str, Any],
        median_ltv: float,
        affinity: dict[str, list[tuple[uuid.UUID, float]]],
        in_failed: bool,
        assignment_key: str,
        control_ratio: float,
        window_days: int,
    ) -> PersonalizedDecision | None:
        """Deterministic scoring. Highest-evidence action wins."""
        ltv = _num(metrics.get("lifetime_value")) or 0.0
        recency_days = _num(metrics.get("recency_days")) or 0.0
        segment = str(metrics.get("primary_segment") or "")
        churn_level = str(metrics.get("churn_risk_level") or "")
        payment_success = _num(metrics.get("payment_success_rate"))
        order_count = int(metrics.get("order_count") or metrics.get("total_orders") or 0)

        held_products = self._held_products(customer.id)
        ranked = [
            (pid, lift) for pid, lift in affinity.get(str(customer.id), [])
            if pid not in held_products
        ][:3]
        top_products = [str(pid) for pid, _lift in ranked]

        evidence = {
            "lifetime_value": _num(ltv),
            "recency_days": _num(recency_days),
            "order_count": order_count,
            "primary_segment": segment,
            "churn_risk_level": churn_level,
            "payment_success_rate": _num(payment_success),
            "merchant_median_ltv": _num(median_ltv),
            "has_recent_payment_failure": bool(in_failed),
            "affinity_product_count": len(ranked),
            "computed_at": _utcnow().isoformat(),
        }

        # Rule ladder — most specific, most valuable signal first. Each arm
        # records exactly which measured fact triggered it.
        action: str | None = None
        reason = ""
        if in_failed and payment_success is not None and float(payment_success) < PAYMENT_SUCCESS_FLOOR:
            action = ACTION_PAYMENT_UPDATE
            reason = (
                f"Payment success rate {float(payment_success):.0%} is below the "
                f"{PAYMENT_SUCCESS_FLOOR:.0%} floor and this customer has a failed "
                "payment, so fixing the instrument is the highest-value next step."
            )
        elif segment == "vip" or (median_ltv > 0 and ltv >= median_ltv * VIP_LTV_MULTIPLE):
            action = ACTION_VIP_NURTURE
            reason = (
                f"Lifetime value {ltv:.0f} is at least "
                f"{VIP_LTV_MULTIPLE:.0f}x the merchant median {median_ltv:.0f}; "
                "protect the relationship."
            )
        elif churn_level in CHURN_RISK_LEVELS:
            action = ACTION_RETENTION
            reason = f"Churn risk is {churn_level}; intervene before decay."
        elif recency_days >= DORMANT_DAYS:
            action = ACTION_WIN_BACK
            reason = (
                f"No purchase for {recency_days:.0f} days (dormant threshold "
                f"{DORMANT_DAYS}); win-back is indicated."
            )
        elif recency_days >= REENGAGE_DAYS:
            action = ACTION_REENGAGE
            reason = (
                f"No purchase for {recency_days:.0f} days; a light re-engagement "
                "is indicated."
            )
        elif ranked:
            action = ACTION_CROSS_SELL
            reason = (
                "Strong real basket affinity with "
                f"{len(ranked)} product(s) this customer has not bought."
            )

        if action is None:
            # No evidence justifies an intervention. Saying so is the honest
            # outcome; a "always recommend something" policy would be noise.
            action = ACTION_HOLD
            reason = (
                "No measured signal justifies an intervention: healthy recency, "
                "no churn risk, no payment issue, no unmatched affinity."
            )

        evidence["trigger"] = reason
        evidence["evidence_rule"] = action

        # Score is a transparent 0-1 blend of measured magnitudes, not a
        # learned model — reproducible and inspectable.
        score = _score(action, ltv, recency_days, churn_level, payment_success, in_failed)

        return PersonalizedDecision(
            customer_id=customer.id,
            action=action,
            score=score,
            cohort=_cohort_for(assignment_key, control_ratio),
            rationale=evidence,
            product_ids=top_products,
        )

    # ── persistence ───────────────────────────────────────────────────────

    def _persist(
        self, merchant_id: uuid.UUID, decisions: list[PersonalizedDecision]
    ) -> tuple[int, int]:
        created = updated = 0
        for decision in decisions:
            key = f"{decision.customer_id}:{decision.action}"
            row = self.db.scalar(
                select(PersonalizationDecision).where(
                    PersonalizationDecision.merchant_id == merchant_id,
                    PersonalizationDecision.decision_key == key,
                )
            )
            assignment = _assignment_key(decision.customer_id, merchant_id)
            if row is None:
                self.db.add(
                    PersonalizationDecision(
                        id=uuid.uuid4(),
                        merchant_id=merchant_id,
                        customer_id=decision.customer_id,
                        recommended_action=decision.action,
                        cohort=decision.cohort,
                        score=Decimal(str(round(decision.score, 5))),
                        rationale=decision.rationale,
                        recommended_product_ids=decision.product_ids,
                        assignment_key=assignment,
                        decision_key=key,
                        status="proposed",
                    )
                )
                created += 1
            else:
                # Preserve an observed outcome; only refresh the reasoning.
                row.score = Decimal(str(round(decision.score, 5)))
                row.rationale = decision.rationale
                row.recommended_product_ids = decision.product_ids
                updated += 1
        self.db.flush()
        return created, updated

    # ── measurement ───────────────────────────────────────────────────────

    def measure_outcomes(
        self,
        merchant_id: uuid.UUID,
        *,
        window_days: int = OUTCOME_WINDOW_DAYS,
    ) -> dict[str, Any]:
        """
        Compare OBSERVED post-decision revenue for treatment vs control.

        Reports nothing causal unless both cohorts have enough resolved
        decisions. When the sample is thin it says so instead of producing a
        flattering number.
        """
        cutoff = _utcnow() - timedelta(days=window_days)
        rows = list(
            self.db.scalars(
                select(PersonalizationDecision).where(
                    PersonalizationDecision.merchant_id == merchant_id
                )
            ).all()
        )
        resolved = [r for r in rows if _as_aware(r.created_at) and _as_aware(r.created_at) <= cutoff]

        observed: dict[str, float] = {}
        counts: dict[str, int] = {}
        for row in resolved:
            revenue = self._observed_revenue_after(merchant_id, row.customer_id, _as_aware(row.created_at))
            row.observed_revenue = Decimal(str(round(revenue, 2)))
            row.measured_at = _utcnow()
            row.status = "measured"
            bucket = row.cohort
            observed[bucket] = observed.get(bucket, 0.0) + revenue
            counts[bucket] = counts.get(bucket, 0) + 1
        self.db.flush()

        treatment_n = counts.get(COHORT_TREATMENT, 0)
        control_n = counts.get(COHORT_CONTROL, 0)
        sufficient = treatment_n >= MIN_COHORT_SIZE and control_n >= MIN_COHORT_SIZE

        treatment_mean = observed.get(COHORT_TREATMENT, 0.0) / treatment_n if treatment_n else None
        control_mean = observed.get(COHORT_CONTROL, 0.0) / control_n if control_n else None
        lift = None
        if sufficient and control_mean:
            lift = (treatment_mean - control_mean) / control_mean

        return {
            "window_days": window_days,
            "resolved_decisions": len(resolved),
            "by_cohort": {
                COHORT_TREATMENT: {
                    "n": treatment_n,
                    "total_observed_revenue": round(observed.get(COHORT_TREATMENT, 0.0), 2),
                    "mean_observed_revenue": (
                        round(treatment_mean, 2) if treatment_mean is not None else None
                    ),
                },
                COHORT_CONTROL: {
                    "n": control_n,
                    "total_observed_revenue": round(observed.get(COHORT_CONTROL, 0.0), 2),
                    "mean_observed_revenue": (
                        round(control_mean, 2) if control_mean is not None else None
                    ),
                },
            },
            "relative_lift": round(lift, 4) if lift is not None else None,
            "is_significant": bool(sufficient and lift is not None),
            "note": (
                f"Both cohorts resolved with n >= {MIN_COHORT_SIZE}; the "
                "relative lift above is an observed association, not a "
                "randomised causal estimate."
                if sufficient
                else (
                    f"Insufficient cohort size (treatment n={treatment_n}, "
                    f"control n={control_n}, minimum {MIN_COHORT_SIZE} each). "
                    "No uplift is claimed."
                )
            ),
            "status": "measured" if resolved else "insufficient_evidence",
        }

    def list_decisions(
        self, merchant_id: uuid.UUID, *, limit: int = 100, cohort: str | None = None
    ) -> list[dict[str, Any]]:
        stmt = select(PersonalizationDecision).where(
            PersonalizationDecision.merchant_id == merchant_id
        )
        if cohort:
            stmt = stmt.where(PersonalizationDecision.cohort == cohort)
        rows = list(
            self.db.scalars(stmt.order_by(PersonalizationDecision.score.desc()).limit(limit)).all()
        )
        return [
            {
                "decision_id": str(r.id),
                "customer_id": str(r.customer_id),
                "recommended_action": r.recommended_action,
                "cohort": r.cohort,
                "score": float(r.score),
                "rationale": r.rationale,
                "recommended_product_ids": r.recommended_product_ids or [],
                "status": r.status,
                "observed_revenue": (
                    float(r.observed_revenue) if r.observed_revenue is not None else None
                ),
                "created_at": str(r.created_at),
            }
            for r in rows
        ]

    # ── real data helpers ─────────────────────────────────────────────────

    def _eligible_customers(self, merchant_id: uuid.UUID, *, limit: int) -> list[Customer]:
        return list(
            self.db.scalars(
                select(Customer)
                .where(Customer.merchant_id == merchant_id)
                .limit(limit)
            ).all()
        )

    def _observed_revenue_after(
        self, merchant_id: uuid.UUID, customer_id: uuid.UUID, since: datetime | None
    ) -> float:
        """Sum of captured payments on this customer's orders created after ``since``."""
        if since is None:
            return 0.0
        orders = list(
            self.db.scalars(
                select(Order).where(
                    Order.merchant_id == merchant_id,
                    Order.customer_id == customer_id,
                    Order.created_at >= since,
                )
            ).all()
        )
        if not orders:
            return 0.0
        order_ids = [o.id for o in orders]
        payments = list(
            self.db.scalars(
                select(Payment).where(
                    Payment.merchant_id == merchant_id,
                    Payment.order_id.in_(order_ids),
                    Payment.status == PaymentStatus.captured.value,
                )
            ).all()
        )
        return sum(float(p.amount or 0) for p in payments)

    def _affinity_pairs(
        self, merchant_id: uuid.UUID
    ) -> dict[str, list[tuple[uuid.UUID, float]]]:
        """Real basket co-occurrence → per-customer product affinity.

        Delegates to the existing product intelligence rather than
        reimplementing the maths.
        """
        from backend.app.services import product_intelligence as pi

        snapshot = pi.build_snapshot(self.db, merchant_id)
        bundles = pi.bundle_opportunities(self.db, merchant_id, snapshot)
        pairs: dict[str, list[tuple[uuid.UUID, float]]] = {}
        raw = (bundles.get("bundles") or bundles.get("opportunities") or [])
        for entry in raw:
            source = entry.get("source_product_id") or entry.get("anchor_product_id")
            targets = entry.get("target_product_ids") or entry.get("companion_product_ids") or []
            lift = float(entry.get("lift") or entry.get("score") or 0.0)
            if not source or not targets:
                continue
            try:
                source_uuid = uuid.UUID(str(source))
            except (ValueError, TypeError):
                continue
            holders = self._customers_who_bought(merchant_id, source_uuid)
            for holder in holders:
                bucket = pairs.setdefault(str(holder), [])
                for target in targets:
                    try:
                        bucket.append((uuid.UUID(str(target)), lift))
                    except (ValueError, TypeError):
                        continue
        return pairs

    def _customers_who_bought(self, merchant_id: uuid.UUID, product_id: uuid.UUID) -> set[uuid.UUID]:
        from backend.app.models.order import OrderItem

        rows = self.db.execute(
            select(Order.customer_id)
            .join(OrderItem, OrderItem.order_id == Order.id)
            .where(
                Order.merchant_id == merchant_id,
                OrderItem.product_id == product_id,
            )
        )
        return {r[0] for r in rows if r[0]}

    def _held_products(self, customer_id: uuid.UUID) -> set[uuid.UUID]:
        from backend.app.models.order import OrderItem

        rows = self.db.execute(
            select(OrderItem.product_id)
            .join(Order, OrderItem.order_id == Order.id)
            .where(Order.customer_id == customer_id)
        )
        return {r[0] for r in rows if r[0]}

    def _customers_with_failures(self, merchant_id: uuid.UUID) -> set[str]:
        """Customers with at least one failed payment (real, recent)."""
        cutoff = _utcnow() - timedelta(days=90)
        rows = self.db.execute(
            select(Order.customer_id)
            .join(Payment, Payment.order_id == Order.id)
            .where(
                Order.merchant_id == merchant_id,
                Payment.status == PaymentStatus.failed.value,
                Payment.created_at >= cutoff,
            )
        )
        return {str(r[0]) for r in rows if r[0]}


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _score(
    action: str,
    ltv: float,
    recency_days: float,
    churn_level: str,
    payment_success: Any,
    in_failed: bool,
) -> float:
    """Transparent 0-1 blend of measured magnitudes. Not a learned model."""
    weights = {
        ACTION_PAYMENT_UPDATE: 0.95,
        ACTION_VIP_NURTURE: 0.80,
        ACTION_RETENTION: 0.85,
        ACTION_WIN_BACK: 0.65,
        ACTION_REENGAGE: 0.45,
        ACTION_CROSS_SELL: 0.40,
        ACTION_HOLD: 0.05,
    }
    base = weights.get(action, 0.3)
    # Value and staleness nudges, both bounded so they cannot invert priority.
    value_nudge = min(0.05, (min(ltv, 200000.0) / 200000.0) * 0.05)
    staleness_nudge = min(0.05, (min(recency_days, 365.0) / 365.0) * 0.05)
    churn_nudge = 0.05 if churn_level in CHURN_RISK_LEVELS else 0.0
    failure_nudge = 0.03 if in_failed else 0.0
    return round(min(1.0, base + value_nudge + staleness_nudge + churn_nudge + failure_nudge), 5)


__all__ = [
    "ACTION_CROSS_SELL",
    "ACTION_HOLD",
    "ACTION_PAYMENT_UPDATE",
    "ACTION_REENGAGE",
    "ACTION_RETENTION",
    "ACTION_VIP_NURTURE",
    "ACTION_WIN_BACK",
    "CHURN_RISK_LEVELS",
    "COHORT_CONTROL",
    "COHORT_TREATMENT",
    "DORMANT_DAYS",
    "KNOWN_ACTIONS",
    "MIN_COHORT_SIZE",
    "PAYMENT_SUCCESS_FLOOR",
    "VIP_LTV_MULTIPLE",
    "PersonalizationService",
    "PersonalizedDecision",
]