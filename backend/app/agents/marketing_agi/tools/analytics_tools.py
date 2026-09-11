"""Analytics tools — real SQL over the merchant's real commerce data.

These tools answer: what is happening with revenue, conversion, AOV,
repeat purchases, cohorts, trends, and anomalies. All numbers are
computed from the database — nothing is estimated or invented.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.customer import Customer
from backend.app.models.order import Order, OrderItem
from backend.app.models.payment import Payment
from backend.app.models.product import Product
from backend.app.models.enums import OrderStatus, PaymentStatus
from backend.app.agents.marketing_agi.tools.registry import ToolSpec

ANALYTICS_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="get_business_overview",
        category="analytics",
        description=(
            "Revenue, orders, AOV, customer counts, repeat-purchase rate over a "
            "recent window — the business's current marketing baseline."
        ),
        capabilities=["traffic", "revenue", "conversion", "retention", "aov"],
    ),
    ToolSpec(
        name="get_revenue_trend",
        category="analytics",
        description=(
            "Revenue and order volume split into recent vs previous window to "
            "detect growth or decline with change percentages."
        ),
        capabilities=["trends", "anomalies"],
    ),
    ToolSpec(
        name="get_customer_activity_trend",
        category="analytics",
        description=(
            "Active vs inactive purchasing customers per window — detects "
            "retention decline and cohort behaviour shifts."
        ),
        capabilities=["retention", "cohort_behavior", "trends"],
    ),
    ToolSpec(
        name="get_failed_payment_analytics",
        category="analytics",
        description=(
            "Failed payments with amounts, failure codes, and recoverable "
            "value — the basis for payment-recovery marketing."
        ),
        capabilities=["payments", "anomalies"],
    ),
]


def _paid_order_ids(db: Session, merchant_id: uuid.UUID) -> list[Any]:
    """Order ids with at least one captured payment (real revenue only)."""
    return list(
        db.scalars(
            select(Payment.order_id).where(
                Payment.merchant_id == merchant_id,
                Payment.status == PaymentStatus.captured,
            )
        ).all()
    )


def _window(days: int) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    return now - timedelta(days=days), now


def get_business_overview(db: Session, merchant_id: uuid.UUID, *, window_days: int = 90) -> dict[str, Any]:
    """Core marketing baseline computed from real orders/payments."""
    since, _ = _window(window_days)

    total_customers = db.scalar(
        select(func.count(Customer.id)).where(Customer.merchant_id == merchant_id)
    ) or 0
    repeat_customers = db.scalar(
        select(func.count(Customer.id)).where(
            Customer.merchant_id == merchant_id,
            Customer.total_orders >= 2,
        )
    ) or 0
    total_orders = db.scalar(
        select(func.count(Order.id)).where(Order.merchant_id == merchant_id)
    ) or 0

    paid_ids = _paid_order_ids(db, merchant_id)
    revenue = Decimal("0")
    paid_orders = 0
    if paid_ids:
        row = db.execute(
            select(func.count(Order.id), func.coalesce(func.sum(Order.total), 0))
            .where(Order.id.in_(paid_ids))
        ).one()
        paid_orders, revenue = int(row[0]), Decimal(row[1])

    aov = float(revenue) / paid_orders if paid_orders else 0.0

    # recent-window activity
    recent_orders = db.scalar(
        select(func.count(Order.id)).where(
            Order.merchant_id == merchant_id,
            Order.created_at >= since,
        )
    ) or 0

    recent_revenue = Decimal("0")
    if paid_ids:
        recent_revenue = db.scalar(
            select(func.coalesce(func.sum(Order.total), 0)).where(
                Order.id.in_(paid_ids),
                Order.created_at >= since,
            )
        ) or Decimal("0")

    repeat_rate = (repeat_customers / total_customers) if total_customers else 0.0

    return {
        "window_days": window_days,
        "total_customers": int(total_customers),
        "repeat_customers": int(repeat_customers),
        "repeat_purchase_rate": round(repeat_rate, 4),
        "total_orders": int(total_orders),
        "paid_orders": paid_orders,
        "total_revenue_inr": float(revenue),
        "recent_window_orders": int(recent_orders),
        "recent_window_revenue_inr": float(recent_revenue),
        "average_order_value_inr": round(aov, 2),
        "data_completeness": "full" if total_customers else "no_data",
    }


def get_revenue_trend(
    db: Session, merchant_id: uuid.UUID, *, window_days: int = 30
) -> dict[str, Any]:
    """Recent vs previous window revenue/order comparison (real deltas)."""
    now = datetime.now(timezone.utc)
    mid = now - timedelta(days=window_days)
    prev_start = now - timedelta(days=window_days * 2)

    paid_ids = _paid_order_ids(db, merchant_id)

    def _sum_in(start: datetime, end: datetime) -> tuple[int, Decimal]:
        if not paid_ids:
            return 0, Decimal("0")
        row = db.execute(
            select(func.count(Order.id), func.coalesce(func.sum(Order.total), 0)).where(
                Order.id.in_(paid_ids),
                Order.created_at >= start,
                Order.created_at < end,
            )
        ).one()
        return int(row[0]), Decimal(row[1])

    cur_count, cur_rev = _sum_in(mid, now)
    prev_count, prev_rev = _sum_in(prev_start, mid)

    def _pct(cur: float, prev: float) -> float | None:
        if prev == 0:
            return None if cur == 0 else 100.0
        return round((cur - prev) / prev * 100, 2)

    return {
        "window_days": window_days,
        "current": {"orders": cur_count, "revenue_inr": float(cur_rev)},
        "previous": {"orders": prev_count, "revenue_inr": float(prev_rev)},
        "order_change_pct": _pct(cur_count, prev_count),
        "revenue_change_pct": _pct(float(cur_rev), float(prev_rev)),
        "trend": (
            "no_data"
            if cur_count == 0 and prev_count == 0
            else "growing"
            if (cur_rev or 0) > (prev_rev or 0)
            else "declining"
        ),
    }


def get_customer_activity_trend(
    db: Session, merchant_id: uuid.UUID, *, window_days: int = 30
) -> dict[str, Any]:
    """Which customers purchased in the recent window vs went quiet."""
    since, _ = _window(window_days)

    active_ids = set(
        db.scalars(
            select(Order.customer_id).where(
                Order.merchant_id == merchant_id,
                Order.created_at >= since,
            )
        ).all()
    )
    all_customers = list(
        db.scalars(
            select(Customer).where(Customer.merchant_id == merchant_id)
        ).all()
    )
    inactive = [c for c in all_customers if c.id not in active_ids]

    inactive_with_history = [
        c for c in inactive if (c.total_orders or 0) >= 1
    ]
    inactive_value = sum(
        (c.total_spend or Decimal("0")) for c in inactive_with_history
    )

    return {
        "window_days": window_days,
        "total_customers": len(all_customers),
        "active_customers": len(active_ids),
        "inactive_customers": len(inactive),
        "inactive_with_purchase_history": len(inactive_with_history),
        "inactive_total_spend_inr": float(inactive_value),
        "inactivity_signal": (
            "meaningful" if len(inactive_with_history) >= 3 else "weak"
        ),
    }


def get_failed_payment_analytics(
    db: Session, merchant_id: uuid.UUID, *, limit: int = 50
) -> dict[str, Any]:
    """Real failed payments + recoverable value for recovery marketing."""
    failed = list(
        db.scalars(
            select(Payment)
            .where(
                Payment.merchant_id == merchant_id,
                Payment.status == PaymentStatus.failed,
            )
            .order_by(Payment.amount.desc())
            .limit(limit)
        ).all()
    )
    total = sum((p.amount or Decimal("0")) for p in failed)
    codes: dict[str, int] = {}
    for p in failed:
        code = p.failure_code or "unknown"
        codes[code] = codes.get(code, 0) + 1

    return {
        "failed_payment_count": len(failed),
        "recoverable_value_inr": float(total),
        "failure_codes": codes,
        "largest": [
            {
                "payment_id": str(p.id),
                "amount_inr": float(p.amount or 0),
                "failure_code": p.failure_code,
                "order_id": str(p.order_id),
            }
            for p in failed[:5]
        ],
    }


def register(registry) -> None:
    from backend.app.agents.marketing_agi.tools.registry import ToolContext

    def _mk(fn, **fixed):
        def factory(ctx: ToolContext):
            def call(**kwargs):
                merged = {**fixed, **kwargs}
                return fn(ctx.db, ctx.merchant_id, **merged)
            return call
        return factory

    registry.register(
        ANALYTICS_TOOLS[0],
        _mk(get_business_overview, window_days=90),
    )
    registry.register(
        ANALYTICS_TOOLS[1],
        _mk(get_revenue_trend, window_days=30),
    )
    registry.register(
        ANALYTICS_TOOLS[2],
        _mk(get_customer_activity_trend, window_days=30),
    )
    registry.register(
        ANALYTICS_TOOLS[3],
        _mk(get_failed_payment_analytics, limit=50),
    )
