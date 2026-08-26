"""
Customer Intelligence + Churn Risk — Phase 5 Features 4 & 5.

DETERMINISTIC data layer: order frequency, lifetime value, recency,
average order value, and payment success rate are computed from real
rows via SQL. Segment classification and churn risk use transparent,
documented heuristics — this is NOT machine learning and no accuracy is
claimed for it.

The LLM may add a human-readable `strategy_note` (interpretation only);
it never supplies numbers.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from statistics import median
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from backend.app.models.customer import Customer
from backend.app.models.customer_insight import CustomerInsight
from backend.app.models.enums import (
    ChurnRiskLevel,
    InsightType,
    OrderStatus,
    PaymentStatus,
)
from backend.app.models.order import Order
from backend.app.models.payment import Payment

log = logging.getLogger(__name__)

# ── Documented heuristic thresholds ─────────────────────────────────────────
VIP_LTV_MULTIPLIER = Decimal("2.0")          # LTV ≥ 2× merchant median ⇒ VIP
HIGH_VALUE_LTV_MULTIPLIER = Decimal("1.2")   # LTV ≥ 1.2× median ⇒ high_value
DORMANT_DAYS = 90                            # 90+ days since last order ⇒ dormant
NEW_CUSTOMER_ORDER_COUNT = 1                 # exactly one order ⇒ new_customer
REPEAT_CUSTOMER_ORDER_COUNT = 2              # ≥2 orders ⇒ repeat_customer
CHURN_RISK_RECENCY_DAYS = 30                 # beyond this, recency score accrues
CHURN_RISK_MAX_RECENCY_DAYS = 90             # recency component saturates here (~3 months silent)
DISCOUNT_SENSITIVE_SPEND_PCT = Decimal("0.60")  # spend concentrated in discount campaigns
MIN_INTERVAL_SAMPLES = 2                     # orders needed to estimate cadence


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: datetime | None) -> datetime | None:
    """Normalise DB-read datetimes: SQLite returns naive UTC — re-tag it."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _insight_key(merchant_id: uuid.UUID, customer_id: uuid.UUID) -> str:
    raw = f"{merchant_id}:{customer_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ────────────────────────────────────────────────────────────────────────────
# Churn risk engine (Feature 5) — transparent weighted heuristic
# ────────────────────────────────────────────────────────────────────────────


class ChurnRiskEngine:
    """
    Deterministic churn scoring.

    churn_risk_score ∈ [0, 100] =
        0.40 × recency_score        (days since last purchase)
      + 0.25 × frequency_decline    (orders in last window vs prior habit)
      + 0.20 × spending_decline     (spend trend)
      + 0.15 × payment_failure_rate (failed payments as a frustration proxy)

    Each component is computed from real rows; every point of the score can
    be traced to its inputs. No ML accuracy claim is made anywhere.
    """

    WEIGHTS = {
        "recency": Decimal("0.40"),
        "frequency_decline": Decimal("0.25"),
        "spending_decline": Decimal("0.20"),
        "payment_failures": Decimal("0.15"),
    }

    def compute(
        self,
        *,
        recency_days: int | None,
        avg_interval_days: float | None,
        recent_order_count: int,
        baseline_order_count: float,
        recent_spend: Decimal,
        baseline_spend: Decimal,
        payment_count: int,
        failed_payment_count: int,
    ) -> dict[str, Any]:
        reasons: list[str] = []
        evidence: dict[str, Any] = {}

        # ── recency ──────────────────────────────────────────────────────
        if recency_days is None:
            recency_score = Decimal("1")  # never purchased recently at all
            evidence["recency_days"] = None
        else:
            saturation = CHURN_RISK_MAX_RECENCY_DAYS - CHURN_RISK_RECENCY_DAYS
            numerator = min(
                max(recency_days - CHURN_RISK_RECENCY_DAYS, 0), saturation
            )
            recency_score = Decimal(numerator) / Decimal(saturation)
            evidence["recency_days"] = recency_days
            if recency_days >= CHURN_RISK_RECENCY_DAYS:
                reasons.append(
                    f"{recency_days} days since last purchase"
                    + (
                        f" (previous average interval: {avg_interval_days:.0f} days)"
                        if avg_interval_days
                        else ""
                    )
                )

        # ── frequency decline ────────────────────────────────────────────
        freq_decline = self._decline(recent_order_count, baseline_order_count)
        evidence["recent_orders"] = recent_order_count
        evidence["baseline_orders_per_window"] = round(float(baseline_order_count), 2)
        if freq_decline >= Decimal("50"):
            reasons.append(
                f"purchase frequency decreased {freq_decline:.0f}%"
            )

        # ── spending decline ─────────────────────────────────────────────
        spend_decline = self._decline(float(recent_spend), float(baseline_spend))
        evidence["recent_spend"] = float(recent_spend)
        evidence["baseline_spend_per_window"] = round(float(baseline_spend), 2)
        if spend_decline >= Decimal("50"):
            reasons.append(f"spending decreased {spend_decline:.0f}%")

        # ── payment failures ─────────────────────────────────────────────
        fail_rate = (
            Decimal(failed_payment_count) / Decimal(payment_count)
            if payment_count > 0
            else Decimal("0")
        )
        fail_component = min(fail_rate * Decimal("4"), Decimal("1"))  # saturate at 25%
        evidence["payments_total"] = payment_count
        evidence["payments_failed"] = failed_payment_count
        if failed_payment_count > 0:
            reasons.append(
                f"{failed_payment_count} of {payment_count} payments failed"
            )

        score = (
            self.WEIGHTS["recency"] * recency_score
            + self.WEIGHTS["frequency_decline"] * _unit(freq_decline / Decimal("100"))
            + self.WEIGHTS["spending_decline"] * _unit(spend_decline / Decimal("100"))
            + self.WEIGHTS["payment_failures"] * fail_component
        ) * Decimal("100")

        churn_risk_score = score.quantize(Decimal("0.01"))
        return {
            "churn_risk_score": churn_risk_score,
            "risk_level": self.level_for(churn_risk_score).value,
            "reasons": reasons,
            "evidence": evidence,
            "components": {
                "recency": float(recency_score),
                "frequency_decline_pct": float(freq_decline),
                "spending_decline_pct": float(spend_decline),
                "payment_failure_component": float(fail_component),
            },
        }

    @staticmethod
    def _decline(current: float, baseline: float) -> Decimal:
        """% by which `current` sits BELOW `baseline`; 0 at-or-above baseline."""
        if baseline <= 0:
            return Decimal("0")
        decline = (baseline - current) / baseline * 100
        return Decimal(str(max(0.0, float(decline)))).quantize(Decimal("0.01"))

    @staticmethod
    def level_for(score: Decimal) -> ChurnRiskLevel:
        if score >= 75:
            return ChurnRiskLevel.critical
        if score >= 55:
            return ChurnRiskLevel.high
        if score >= 35:
            return ChurnRiskLevel.medium
        if score >= 15:
            return ChurnRiskLevel.low
        return ChurnRiskLevel.minimal


def _unit(v: Decimal) -> Decimal:
    return min(Decimal("1"), max(Decimal("0"), v))


# ────────────────────────────────────────────────────────────────────────────
# Customer intelligence service (Feature 4)
# ────────────────────────────────────────────────────────────────────────────

RECENT_WINDOW_DAYS = 60


class CustomerIntelligenceService:
    """Computes and persists per-customer intelligence for one merchant."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.churn_engine = ChurnRiskEngine()

    # ── deterministic aggregates ─────────────────────────────────────────

    def compute_metrics(self, merchant_id: uuid.UUID) -> list[dict[str, Any]]:
        now = _utcnow()
        recent_cutoff = now - timedelta_days(RECENT_WINDOW_DAYS)

        customers = self.db.scalars(
            select(Customer).where(Customer.merchant_id == merchant_id)
        ).all()
        if not customers:
            return []

        cust_ids = [c.id for c in customers]
        ltv_values = [Decimal(str(c.total_spend)) for c in customers]
        median_ltv = Decimal(str(median(ltv_values))) if ltv_values else Decimal("0")

        order_stats = self.db.execute(
            select(
                Order.customer_id,
                func.count(Order.id),
                func.coalesce(func.sum(Order.total), 0),
                func.max(Order.created_at),
                func.min(Order.created_at),
            )
            .where(Order.merchant_id == merchant_id)
            .where(Order.status.in_([OrderStatus.paid.value]))
            .group_by(Order.customer_id)
        ).all()

        pay_rows = self.db.execute(
            select(
                Order.customer_id,
                func.count(Payment.id),
                func.sum(case((Payment.status == PaymentStatus.failed.value, 1), else_=0)),
            )
            .join(Payment, Payment.order_id == Order.id)
            .where(Order.merchant_id == merchant_id)
            .group_by(Order.customer_id)
        ).all()
        pay_map = {cid: (int(cnt), int(failed)) for cid, cnt, failed in pay_rows}

        recent_rows = dict(
            (cid, (int(cnt), Decimal(str(total))))
            for cid, cnt, total in self.db.execute(
                select(
                    Order.customer_id,
                    func.count(Order.id),
                    func.coalesce(func.sum(Order.total), 0),
                )
                .where(Order.merchant_id == merchant_id)
                .where(Order.status.in_([OrderStatus.paid.value]))
                .where(Order.created_at >= recent_cutoff)
                .group_by(Order.customer_id)
            ).all()
        )

        results: list[dict[str, Any]] = []
        by_id = {c.id: c for c in customers}
        for cid, order_count, total_spend, last_at, first_at in order_stats:
            customer = by_id.get(cid)
            if customer is None:
                continue  # cross-tenant safety: never emit without owning row
            order_count = int(order_count)
            total_spend_dec = Decimal(str(total_spend))
            aov = (total_spend_dec / Decimal(order_count)) if order_count else Decimal("0")
            last_at = _as_aware(last_at)
            first_at = _as_aware(first_at)
            recency_days = (
                int((now - last_at).days) if last_at is not None else None
            )
            avg_interval = None
            if order_count >= MIN_INTERVAL_SAMPLES and first_at and last_at and last_at > first_at:
                span_days = (last_at - first_at).days
                avg_interval = Decimal(span_days) / Decimal(order_count - 1)

            pays, fails = pay_map.get(cid, (0, 0))
            success_rate = (
                Decimal(pays - fails) / Decimal(pays) if pays > 0 else Decimal("0")
            )

            segments = self._classify(
                ltv=total_spend_dec,
                median_ltv=median_ltv,
                order_count=order_count,
                recency_days=recency_days,
                fails=fails,
                pays=pays,
            )

            recent_cnt, recent_spend = recent_rows.get(cid, (0, Decimal("0")))
            lifetime_days = (
                max(RECENT_WINDOW_DAYS, (now - first_at).days)
                if first_at is not None
                else RECENT_WINDOW_DAYS
            )
            baseline_orders = order_count * RECENT_WINDOW_DAYS / max(lifetime_days, 1)
            baseline_spend = (
                total_spend_dec * Decimal(RECENT_WINDOW_DAYS) / Decimal(max(lifetime_days, 1))
            )

            churn = self.churn_engine.compute(
                recency_days=recency_days,
                avg_interval_days=float(avg_interval) if avg_interval else None,
                recent_order_count=recent_cnt,
                baseline_order_count=baseline_orders,
                recent_spend=recent_spend,
                baseline_spend=baseline_spend,
                payment_count=pays,
                failed_payment_count=fails,
            )

            results.append(
                {
                    "customer_id": cid,
                    "primary_segment": segments[0],
                    "segments": segments,
                    "order_count": order_count,
                    "lifetime_value": total_spend_dec.quantize(Decimal("0.01")),
                    "avg_order_value": aov.quantize(Decimal("0.01")),
                    "recency_days": recency_days,
                    "avg_interval_days": (
                        avg_interval.quantize(Decimal("0.01")) if avg_interval else None
                    ),
                    "payment_success_rate": success_rate.quantize(Decimal("0.0001")),
                    "failed_payment_count": fails,
                    **churn,
                    "insight_key": _insight_key(merchant_id, cid),
                }
            )
        return results

    def _classify(
        self,
        *,
        ltv: Decimal,
        median_ltv: Decimal,
        order_count: int,
        recency_days: int | None,
        fails: int,
        pays: int,
    ) -> list[str]:
        """Deterministic, documented segmentation rules (priority-ordered)."""
        segments: list[str] = []
        hv_threshold = median_ltv * HIGH_VALUE_LTV_MULTIPLIER
        vip_threshold = median_ltv * VIP_LTV_MULTIPLIER

        if median_ltv > 0 and ltv >= vip_threshold:
            segments.append(InsightType.vip.value)
        elif median_ltv > 0 and ltv >= hv_threshold:
            segments.append(InsightType.high_value.value)

        if recency_days is not None and recency_days >= DORMANT_DAYS:
            segments.append(InsightType.dormant.value)
        if order_count == NEW_CUSTOMER_ORDER_COUNT:
            segments.append(InsightType.new_customer.value)
        if order_count >= REPEAT_CUSTOMER_ORDER_COUNT:
            segments.append(InsightType.repeat_customer.value)
        if pays > 0 and fails >= 2:
            segments.append(InsightType.payment_failure.value)
            segments.append(InsightType.churn_risk.value)

        if not segments:
            segments.append(InsightType.new_customer.value)
        return segments

    # ── persistence ──────────────────────────────────────────────────────

    def refresh(self, merchant_id: uuid.UUID) -> list[CustomerInsight]:
        metrics = self.compute_metrics(merchant_id)
        out: list[CustomerInsight] = []
        for m in metrics:
            existing = self.db.scalars(
                select(CustomerInsight).where(
                    CustomerInsight.merchant_id == merchant_id,
                    CustomerInsight.insight_key == m["insight_key"],
                )
            ).first()
            numeric_fields = {
                k: v
                for k, v in m.items()
                if k
                in (
                    "order_count", "lifetime_value", "avg_order_value",
                    "recency_days", "avg_interval_days", "payment_success_rate",
                    "failed_payment_count", "churn_risk_score",
                )
            }
            label_fields = {
                "primary_segment": m["primary_segment"],
                "segments": m["segments"],
                "churn_risk_level": m["risk_level"],
                "churn_reasons": m["reasons"],
                "churn_evidence": m["evidence"],
            }
            if existing is not None:
                for k, v in {**numeric_fields, **label_fields}.items():
                    setattr(existing, k, v)
                out.append(existing)
                continue
            insight = CustomerInsight(
                merchant_id=merchant_id,
                customer_id=m["customer_id"],
                insight_key=m["insight_key"],
                **numeric_fields,
                **label_fields,
            )
            self.db.add(insight)
            out.append(insight)
        self.db.flush()
        return out

    def list_insights(
        self,
        merchant_id: uuid.UUID,
        *,
        segment: str | None = None,
        limit: int = 200,
    ) -> list[CustomerInsight]:
        stmt = (
            select(CustomerInsight)
            .where(CustomerInsight.merchant_id == merchant_id)
            .order_by(CustomerInsight.churn_risk_score.desc())
            .limit(limit)
        )
        if segment:
            stmt = stmt.where(CustomerInsight.primary_segment == segment)
        return list(self.db.scalars(stmt).all())

    def get_customer_insight(
        self, merchant_id: uuid.UUID, customer_id: uuid.UUID
    ) -> CustomerInsight | None:
        return self.db.scalars(
            select(CustomerInsight).where(
                CustomerInsight.merchant_id == merchant_id,
                CustomerInsight.customer_id == customer_id,
            )
        ).first()


# ── small helpers ───────────────────────────────────────────────────────────


def timedelta_days(days: int):
    from datetime import timedelta

    return timedelta(days=days)
