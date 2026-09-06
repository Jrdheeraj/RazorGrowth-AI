"""
Growth Radar — Phase 5 Feature 3.

Continuously detects structured business signals from REAL commerce data.
Every signal carries: metric, current value, comparison value, time
window, evidence, confidence. Nothing is fabricated:

  - a signal is only emitted when its underlying SQL aggregate crosses a
    documented deterministic threshold,
  - current/comparison values are the raw aggregates themselves,
  - zero-data windows produce NO signal (absence of data ≠ zero signal),
  - confidence scales deterministically with sample size.

Signals are persisted idempotently per detection bucket so repeated runs
refresh rather than duplicate.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.models.customer import Customer
from backend.app.models.enums import (
    GrowthSignalType,
    OrderStatus,
    PaymentProvider,
    PaymentStatus,
    SignalStatus,
)
from backend.app.models.growth_signal import GrowthSignal
from backend.app.models.order import Order
from backend.app.models.payment import Payment

log = logging.getLogger(__name__)

# ── Deterministic detection thresholds ──────────────────────────────────────
REVENUE_DROP_PCT = Decimal("-10")        # ≥10% revenue decline ⇒ revenue_drop
EMERGING_GROWTH_PCT = Decimal("20")      # ≥20% growth ⇒ emerging_growth
REPEAT_DECLINE_PCT = Decimal("-15")      # repeat-purchase decline threshold
ORDER_VOLUME_CHANGE_PCT = Decimal("40")  # unusual behaviour band
DORMANT_DAYS = 60                        # no purchase in 60 days ⇒ dormant
HIGH_VALUE_LTV_MULTIPLIER = Decimal("1.5")
MIN_SIGNAL_SAMPLE = 3                    # below this: no signal at all
PAYMENT_FAILURE_ABS_MIN = 1              # any failure is worth surfacing


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: datetime | None) -> datetime | None:
    """Normalise DB-read datetimes: SQLite returns naive UTC — re-tag it."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _bucket_start(now: datetime, window_days: int) -> str:
    """Detection bucket label — one signal row per type per window per day."""
    return now.strftime("%Y%m%d")


def _signal_key(
    merchant_id: uuid.UUID, signal_type: str, window_days: int, bucket: str
) -> str:
    raw = f"{signal_type}:{merchant_id}:{window_days}:{bucket}"
    return hashlib.sha256(raw.encode()).hexdigest()[:48]


def _confidence_for(sample_size: int, strength: int = 0) -> Decimal:
    """
    Deterministic confidence: grows with sample size, capped at 0.90.
    `strength` adds up to +0.05 for strongly corroborated metrics.
    """
    base = Decimal("0.30") + Decimal("0.55") * Decimal(
        min(sample_size, 50)
    ) / Decimal("50")
    return min(Decimal("0.90"), base + Decimal(str(strength)) * Decimal("0.025")).quantize(
        Decimal("0.0001")
    )


def _pct_change(current: Decimal, comparison: Decimal) -> Decimal | None:
    if comparison == 0:
        return None
    return ((current - comparison) / comparison * Decimal("100")).quantize(
        Decimal("0.01")
    )


class GrowthRadarService:
    """Detects, persists, and returns growth signals for one merchant."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def build_real_data_radar(
        self, merchant_id: uuid.UUID, *, window_days: int = 30
    ) -> dict[str, Any]:
        """Build a read-time radar response strictly from the merchant's real Razorpay data."""
        settings = get_settings()
        if getattr(settings, 'REAL_TEST_INTEGRATION_ENABLED', False) and settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET:
            # Only auto-sync the merchant that actually owns the configured
            # Razorpay TEST account: one with existing Razorpay-provider
            # payments. This prevents the single configured TEST account's
            # data from being copied into every newly registered merchant's
            # workspace (multi-tenant isolation).
            has_razorpay_data = bool(self.db.scalar(
                select(func.count(Payment.id)).where(
                    Payment.merchant_id == merchant_id,
                    Payment.provider == PaymentProvider.razorpay.value,
                ).limit(1)
            ))
            if has_razorpay_data:
                try:
                    from backend.app.services.razorpay_ingestion import RazorpayIngestionService
                    RazorpayIngestionService(self.db, merchant_id).ingest_all()
                    self.db.commit()
                except Exception as e:
                    log.warning("GrowthRadar real test data auto-sync failed: %s", e)
                    self.db.rollback()

        now = _utcnow()
        start = now - timedelta(days=window_days)

        captured_revenue, captured_transactions = self._revenue(merchant_id, start, now)
        successful_payments = captured_transactions
        failed_payments = int(self.db.scalar(
            select(func.count(Payment.id)).where(
                Payment.merchant_id == merchant_id,
                Payment.provider == PaymentProvider.razorpay.value,
                Payment.status == PaymentStatus.failed.value,
                Payment.created_at >= start,
            )
        ) or 0)
        total_customers = int(self.db.scalar(
            select(func.count(Customer.id)).where(Customer.merchant_id == merchant_id)
        ) or 0)
        repeat_customers = int(self.db.scalar(
            select(func.count(Customer.id)).where(
                Customer.merchant_id == merchant_id,
                Customer.total_orders >= 2,
            )
        ) or 0)
        total_orders = self._order_volume(merchant_id, start, now)
        average_order_value = Decimal(str(self.db.scalar(
            select(func.coalesce(func.avg(Payment.amount), 0)).where(
                Payment.merchant_id == merchant_id,
                Payment.provider == PaymentProvider.razorpay.value,
                Payment.status == PaymentStatus.captured.value,
                Payment.created_at >= start,
            )
        ) or 0))

        minimum_required = MIN_SIGNAL_SAMPLE
        if captured_transactions == 0 and failed_payments == 0:
            sufficiency = {
                "status": "insufficient_data",
                "message": "No real Razorpay test data available. Create test orders/payments via Checkout to view growth metrics.",
                "minimum_required": minimum_required,
                "available": 0,
            }
        elif captured_transactions < minimum_required:
            sufficiency = {
                "status": "insufficient_data",
                "message": f"More real captured transactions are required to generate a reliable growth signal ({captured_transactions} recorded, {minimum_required} required).",
                "minimum_required": minimum_required,
                "available": captured_transactions,
            }
        else:
            sufficiency = {
                "status": "sufficient",
                "message": "Sufficient real captured transaction data is available for growth analysis.",
                "minimum_required": minimum_required,
                "available": captured_transactions,
            }

        raw_signals = self.detect(merchant_id, window_days=window_days, persist=False)
        signal_guidance = {
            "revenue_drop": (
                "Revenue recovery opportunity",
                "Investigate the real revenue decline and target retention or recovery work.",
            ),
            "emerging_growth": (
                "Revenue expansion opportunity",
                "Study the observed growth source and focus on the best-performing segment.",
            ),
            "payment_failures": (
                "Payment recovery opportunity",
                "Review failed transactions and offer a compliant payment-recovery path.",
            ),
            "payment_recovery_opportunity": (
                "Recover failed-payment revenue",
                "Follow up on the recorded failed payments using an approved recovery workflow.",
            ),
            "declining_repeat_purchases": (
                "Repeat-purchase opportunity",
                "Consider a retention campaign based on the observed repeat-purchase decline.",
            ),
        }
        signals = []
        for item in raw_signals:
            opportunity, action = signal_guidance.get(
                item["signal_type"],
                ("Growth opportunity", "Review the recorded evidence with the merchant team."),
            )
            signals.append({
                "signal": item["signal_type"],
                "title": item["title"],
                "observed_data": item["evidence"] or {},
                "calculated_metric": item["metric"],
                "opportunity": opportunity,
                "confidence": item["confidence"],
                "reason": f"Observed {item['metric']} from {item['window_days']}-day PostgreSQL payment/order data.",
                "recommended_action": action,
            })

        return {
            "merchant_id": str(merchant_id),
            "generated_at": now.isoformat(),
            "overall_health": "insufficient_data" if sufficiency["status"] == "insufficient_data" else "measured",
            "metrics": {
                "captured_revenue": float(captured_revenue),
                "captured_transactions": captured_transactions,
                "successful_payments": successful_payments,
                "failed_payments": failed_payments,
                "total_customers": total_customers,
                "repeat_customers": repeat_customers,
                "total_orders": total_orders,
                "average_order_value": float(average_order_value),
            },
            "data_sufficiency": sufficiency,
            "signals": signals,
        }

    # ── Aggregation helpers (real rows only) ────────────────────────────

    def revenue_for_window(
        self, merchant_id: uuid.UUID, start: datetime, end: datetime
    ) -> tuple[Decimal, int]:
        """Public wrapper — captured revenue for an arbitrary window."""
        return self._revenue(merchant_id, start, end)

    def _revenue(self, merchant_id: uuid.UUID, start: datetime, end: datetime) -> tuple[Decimal, int]:
        stmt = (
            select(func.coalesce(func.sum(Payment.amount), 0), func.count(Payment.id))
            .where(Payment.merchant_id == merchant_id)
            .where(Payment.provider == PaymentProvider.razorpay.value)
            .where(Payment.status == PaymentStatus.captured.value)
            .where(Payment.created_at >= start)
            .where(Payment.created_at < end)
        )
        row = self.db.execute(stmt).one()
        return Decimal(str(row[0])), int(row[1])

    def _order_volume(self, merchant_id: uuid.UUID, start: datetime, end: datetime) -> int:
        stmt = (
            select(func.count(Order.id))
            .where(Order.merchant_id == merchant_id)
            .where(Order.created_at >= start)
            .where(Order.created_at < end)
        )
        return int(self.db.execute(stmt).scalar_one())

    def _repeat_order_volume(self, merchant_id: uuid.UUID, start: datetime, end: datetime) -> int:
        stmt = (
            select(func.count(Order.id))
            .join(Customer, Order.customer_id == Customer.id)
            .where(Order.merchant_id == merchant_id)
            .where(Customer.total_orders >= 2)
            .where(Order.created_at >= start)
            .where(Order.created_at < end)
        )
        return int(self.db.execute(stmt).scalar_one())

    def _failed_payment_stats(self, merchant_id: uuid.UUID, start: datetime, end: datetime) -> dict[str, Any]:
        stmt = (
            select(func.count(Payment.id), func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.merchant_id == merchant_id)
            .where(Payment.provider == PaymentProvider.razorpay.value)
            .where(Payment.status == PaymentStatus.failed.value)
            .where(Payment.created_at >= start)
            .where(Payment.created_at < end)
        )
        count, total = self.db.execute(stmt).one()
        return {"count": int(count), "value": Decimal(str(total))}

    def _avg_customer_ltv(self, merchant_id: uuid.UUID) -> Decimal:
        stmt = select(func.coalesce(func.avg(Customer.total_spend), 0)).where(
            Customer.merchant_id == merchant_id
        )
        return Decimal(str(self.db.execute(stmt).scalar_one()))

    # ── Detection ────────────────────────────────────────────────────────

    def detect(
        self,
        merchant_id: uuid.UUID,
        *,
        window_days: int = 30,
        persist: bool = True,
    ) -> list[dict[str, Any]]:
        now = _utcnow()
        bucket = _bucket_start(now, window_days)
        cur_start = now - timedelta(days=window_days)
        prev_start = cur_start - timedelta(days=window_days)

        detected: list[dict[str, Any]] = []

        def emit(
            signal_type: GrowthSignalType,
            title: str,
            metric: str,
            current: Decimal,
            comparison: Decimal,
            evidence: dict[str, Any],
            sample_size: int,
            change: Decimal | None = None,
            min_sample: int = MIN_SIGNAL_SAMPLE,
        ) -> None:
            if sample_size < min_sample:
                return  # never fabricate a signal from thin data
            detected.append(
                {
                    "signal_type": signal_type.value,
                    "title": title,
                    "metric": metric,
                    "current_value": float(current),
                    "comparison_value": float(comparison),
                    "change_percentage": float(change) if change is not None else None,
                    "window_days": window_days,
                    "confidence": float(_confidence_for(sample_size)),
                    "evidence": evidence,
                }
            )

        # 1 ── Revenue drop / emerging growth ─────────────────────────────
        rev_cur, pay_cur_n = self._revenue(merchant_id, cur_start, now)
        rev_prev, pay_prev_n = self._revenue(merchant_id, prev_start, cur_start)
        rev_change = _pct_change(rev_cur, rev_prev)
        sample = pay_cur_n + pay_prev_n
        if rev_change is not None and rev_change <= REVENUE_DROP_PCT and sample >= MIN_SIGNAL_SAMPLE:
            emit(
                GrowthSignalType.revenue_drop,
                f"Revenue changed {rev_change}% over the last {window_days} days",
                "captured_revenue_inr",
                rev_cur, rev_prev,
                {
                    "current_window": {"captured_payments": pay_cur_n},
                    "previous_window": {"captured_payments": pay_prev_n},
                    "threshold_pct": float(REVENUE_DROP_PCT),
                },
                sample, rev_change,
            )
        elif rev_change is not None and rev_change >= EMERGING_GROWTH_PCT and sample >= MIN_SIGNAL_SAMPLE:
            emit(
                GrowthSignalType.emerging_growth,
                f"Revenue grew {rev_change}% over the last {window_days} days",
                "captured_revenue_inr",
                rev_cur, rev_prev,
                {"trend": "up", "threshold_pct": float(EMERGING_GROWTH_PCT)},
                sample, rev_change,
            )

        # 2 ── Declining repeat purchases ─────────────────────────────────
        rep_cur = self._repeat_order_volume(merchant_id, cur_start, now)
        rep_prev = self._repeat_order_volume(merchant_id, prev_start, cur_start)
        rep_change = _pct_change(Decimal(rep_cur), Decimal(rep_prev))
        if rep_change is not None and rep_change <= REPEAT_DECLINE_PCT and rep_cur + rep_prev >= MIN_SIGNAL_SAMPLE:
            emit(
                GrowthSignalType.declining_repeat_purchases,
                f"Repeat purchases declined {rep_change}% over the last {window_days} days",
                "repeat_customer_orders",
                Decimal(rep_cur), Decimal(rep_prev),
                {"definition": "orders by customers with lifetime_orders >= 2"},
                rep_cur + rep_prev, rep_change,
            )

        # 3 ── Unusual order behaviour ────────────────────────────────────
        vol_cur = self._order_volume(merchant_id, cur_start, now)
        vol_prev = self._order_volume(merchant_id, prev_start, cur_start)
        vol_change = _pct_change(Decimal(vol_cur), Decimal(vol_prev))
        if vol_change is not None and abs(vol_change) >= ORDER_VOLUME_CHANGE_PCT and vol_cur + vol_prev >= MIN_SIGNAL_SAMPLE:
            emit(
                GrowthSignalType.unusual_order_behavior,
                f"Order volume shifted {vol_change}% versus the prior window",
                "order_count",
                Decimal(vol_cur), Decimal(vol_prev),
                {"band_pct": float(ORDER_VOLUME_CHANGE_PCT)},
                vol_cur + vol_prev, vol_change,
            )

        # 4 ── Payment failures ───────────────────────────────────────────
        fails_cur = self._failed_payment_stats(merchant_id, cur_start, now)
        if fails_cur["count"] >= PAYMENT_FAILURE_ABS_MIN:
            emit(
                GrowthSignalType.payment_failures,
                f"{fails_cur['count']} payment failures worth ₹{fails_cur['value']} in the last {window_days} days",
                "failed_payment_value_inr",
                fails_cur["value"], Decimal("0"),
                {"failed_count": fails_cur["count"], "source": "payments.status='failed'"},
                fails_cur["count"], None, min_sample=PAYMENT_FAILURE_ABS_MIN,
            )
            emit(
                GrowthSignalType.payment_recovery_opportunity,
                f"Recoverable failed-payment revenue of ₹{fails_cur['value']}",
                "recoverable_revenue_inr",
                fails_cur["value"], Decimal("0"),
                {"failed_count": fails_cur["count"]},
                fails_cur["count"], None, min_sample=PAYMENT_FAILURE_ABS_MIN,
            )

        # 5 ── Dormant / abandoned customers ──────────────────────────────
        dorm_cutoff = now - timedelta(days=DORMANT_DAYS)
        dormant_stmt = (
            select(func.count(Customer.id))
            .outerjoin(Order, Order.customer_id == Customer.id)
            .where(Customer.merchant_id == merchant_id)
            .where(Customer.total_orders >= 2)
            .group_by(Customer.id)
            .having(func.max(Order.created_at) < dorm_cutoff)
        )
        dormant_ids = [row[0] for row in self.db.execute(select(Customer.id).where(
            Customer.merchant_id == merchant_id,
            Customer.total_orders >= 2,
        ))]
        # portable per-customer recency check
        dormant_count = 0
        high_value_dormant = 0
        avg_ltv = self._avg_customer_ltv(merchant_id)
        hv_threshold = avg_ltv * HIGH_VALUE_LTV_MULTIPLIER
        if dormant_ids:
            last_order_rows = self.db.execute(
                select(Order.customer_id, func.max(Order.created_at))
                .where(Order.customer_id.in_(dormant_ids))
                .group_by(Order.customer_id)
            ).all()
            ltv_rows = {
                cid: spend
                for cid, spend in self.db.execute(
                    select(Customer.id, Customer.total_spend).where(
                        Customer.id.in_(dormant_ids)
                    )
                ).all()
            }
            for cid, last_dt in last_order_rows:
                last_dt = _as_aware(last_dt)
                has_recent = last_dt is not None and last_dt >= dorm_cutoff
                if not has_recent:
                    dormant_count += 1
                    if Decimal(str(ltv_rows.get(cid, 0))) >= hv_threshold:
                        high_value_dormant += 1

        if dormant_count >= MIN_SIGNAL_SAMPLE:
            emit(
                GrowthSignalType.abandoned_customers,
                f"{dormant_count} previously-active customers have not purchased in {DORMANT_DAYS}+ days",
                "dormant_customer_count",
                Decimal(dormant_count), Decimal("0"),
                {"recency_cutoff_days": DORMANT_DAYS, "min_lifetime_orders": 2},
                dormant_count, None,
            )
            emit(
                GrowthSignalType.segment_opportunity,
                f"Win-back opportunity across {dormant_count} dormant customers",
                "targetable_customers",
                Decimal(dormant_count), Decimal("0"),
                {"segment": "dormant"},
                dormant_count, None,
            )
        if high_value_dormant >= MIN_SIGNAL_SAMPLE:
            emit(
                GrowthSignalType.inactive_high_value,
                f"{high_value_dormant} high-value customers went quiet (LTV ≥ ₹{hv_threshold.quantize(Decimal('1'))})",
                "inactive_high_value_customers",
                Decimal(high_value_dormant), Decimal("0"),
                {"ltv_threshold": float(hv_threshold), "multiplier": float(HIGH_VALUE_LTV_MULTIPLIER)},
                high_value_dormant, None,
            )

        if persist:
            self._persist(merchant_id, window_days, bucket, detected)
        return detected

    # ── Persistence (idempotent refresh per bucket) ──────────────────────

    def _persist(
        self,
        merchant_id: uuid.UUID,
        window_days: int,
        bucket: str,
        detected: list[dict[str, Any]],
    ) -> None:
        now = _utcnow()
        for item in detected:
            key = _signal_key(merchant_id, item["signal_type"], window_days, bucket)
            existing = self.db.scalars(
                select(GrowthSignal).where(
                    GrowthSignal.merchant_id == merchant_id,
                    GrowthSignal.signal_key == key,
                )
            ).first()
            if existing is not None:
                for field, value in item.items():
                    setattr(existing, field, value)
                existing.status = SignalStatus.active
                existing.detected_at = now
                continue
            self.db.add(
                GrowthSignal(
                    merchant_id=merchant_id,
                    signal_key=key,
                    signal_type=GrowthSignalType(item["signal_type"]),
                    title=item["title"],
                    status=SignalStatus.active,
                    metric=item["metric"],
                    current_value=Decimal(str(item["current_value"])),
                    comparison_value=Decimal(str(item["comparison_value"])),
                    change_percentage=(
                        Decimal(str(item["change_percentage"]))
                        if item["change_percentage"] is not None
                        else None
                    ),
                    window_days=item["window_days"],
                    confidence=Decimal(str(item["confidence"])),
                    evidence=item["evidence"],
                    detected_at=now,
                )
            )
        self.db.flush()

    # ── Reads ────────────────────────────────────────────────────────────

    def list_signals(
        self,
        merchant_id: uuid.UUID,
        *,
        limit: int = 100,
        signal_type: str | None = None,
    ) -> list[GrowthSignal]:
        stmt = (
            select(GrowthSignal)
            .where(GrowthSignal.merchant_id == merchant_id)
            .where(GrowthSignal.status == SignalStatus.active.value)
            .order_by(GrowthSignal.detected_at.desc())
            .limit(limit)
        )
        if signal_type:
            stmt = stmt.where(GrowthSignal.signal_type == signal_type)
        return list(self.db.scalars(stmt).all())
