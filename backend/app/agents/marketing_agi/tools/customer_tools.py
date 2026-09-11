"""Customer knowledge tools — CRM + dynamic segmentation.

The agent derives segments from real customer/order behaviour. Named
segments exist as convenient presets, but the agent can also define
arbitrary derived segments (e.g. "3+ purchases, AOV above X, inactive
for Y days") — the tool evaluates the criteria against real SQL.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.customer import Customer
from backend.app.models.order import Order
from backend.app.models.enums import CustomerSegment
from backend.app.agents.marketing_agi.tools.registry import ToolSpec

CUSTOMER_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="get_customer_segments",
        category="customers",
        description=(
            "Aggregate the customer base by stored segment with counts, spend, "
            "and average orders — the CRM overview."
        ),
        capabilities=["crm", "segments"],
    ),
    ToolSpec(
        name="find_customers",
        category="customers",
        description=(
            "Build a dynamic audience from behavioural criteria: "
            "min_orders, min_spend_inr, inactive_days, segment. The agent "
            "decides the criteria; this tool evaluates them against real data."
        ),
        capabilities=["segmentation", "audiences"],
    ),
    ToolSpec(
        name="get_customer_profile",
        category="customers",
        description=(
            "Fetch real profile facts (orders, spend, segment) for one "
            "customer — used for personalization, never invented."
        ),
        capabilities=["crm", "personalization"],
    ),
]


def get_customer_segments(db: Session, merchant_id: uuid.UUID) -> dict[str, Any]:
    rows = db.execute(
        select(
            Customer.segment,
            func.count(Customer.id),
            func.coalesce(func.sum(Customer.total_spend), 0),
            func.coalesce(func.avg(Customer.total_orders), 0),
        )
        .where(Customer.merchant_id == merchant_id)
        .group_by(Customer.segment)
    ).all()

    segments = [
        {
            "segment": str(
                getattr(r[0], "value", r[0])
            ),
            "customers": int(r[1]),
            "total_spend_inr": float(r[2]),
            "avg_orders": round(float(r[3]), 2),
        }
        for r in rows
    ]
    return {
        "segments": segments,
        "total": sum(s["customers"] for s in segments),
    }


def find_customers(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    min_orders: int = 0,
    min_spend_inr: float = 0.0,
    inactive_days: int | None = None,
    segment: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Dynamic segment evaluation — the agent's derived-audience engine."""
    stmt = select(Customer).where(Customer.merchant_id == merchant_id)
    if min_orders:
        stmt = stmt.where(Customer.total_orders >= min_orders)
    if min_spend_inr:
        stmt = stmt.where(Customer.total_spend >= Decimal(str(min_spend_inr)))
    if segment:
        try:
            stmt = stmt.where(Customer.segment == CustomerSegment(segment))
        except ValueError:
            pass  # unknown segment label: ignore filter, never fabricate

    customers = list(db.scalars(stmt.order_by(Customer.total_spend.desc())).all())

    # inactivity filter needs real purchase recency from orders
    if inactive_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=inactive_days)
        recent_buyers = set(
            db.scalars(
                select(Order.customer_id).where(
                    Order.merchant_id == merchant_id,
                    Order.created_at >= cutoff,
                )
            ).all()
        )
        customers = [c for c in customers if c.id not in recent_buyers]

    customers = customers[:limit]

    total_spend = sum((c.total_spend or Decimal("0")) for c in customers)
    return {
        "criteria": {
            "min_orders": min_orders,
            "min_spend_inr": min_spend_inr,
            "inactive_days": inactive_days,
            "segment": segment,
        },
        "audience_count": len(customers),
        "total_spend_inr": float(total_spend),
        "average_spend_inr": (
            float(total_spend) / len(customers) if customers else 0.0
        ),
        "customers": [
            {
                "customer_id": str(c.id),
                "name": c.name,
                "segment": str(getattr(c.segment, "value", c.segment)),
                "total_orders": int(c.total_orders or 0),
                "total_spend_inr": float(c.total_spend or 0),
            }
            for c in customers
        ],
    }


def get_customer_profile(
    db: Session, merchant_id: uuid.UUID, *, customer_id: str
) -> dict[str, Any]:
    """Real profile for one customer — personalization input."""
    try:
        cid = uuid.UUID(customer_id)
    except ValueError:
        return {"error": "INVALID_CUSTOMER_ID", "customer_id": customer_id}

    customer = db.scalar(
        select(Customer).where(
            Customer.merchant_id == merchant_id,
            Customer.id == cid,
        )
    )
    if customer is None:
        return {"error": "CUSTOMER_NOT_FOUND", "customer_id": customer_id}

    orders = list(
        db.scalars(
            select(Order)
            .where(
                Order.merchant_id == merchant_id,
                Order.customer_id == cid,
            )
            .order_by(Order.created_at.desc())
            .limit(10)
        ).all()
    )
    return {
        "customer_id": str(customer.id),
        "name": customer.name,
        "segment": str(getattr(customer.segment, "value", customer.segment)),
        "total_orders": int(customer.total_orders or 0),
        "total_spend_inr": float(customer.total_spend or 0),
        "recent_orders": [
            {
                "order_number": o.order_number,
                "total_inr": float(o.total),
                "status": str(getattr(o.status, "value", o.status)),
                "placed_at": str(o.created_at),
            }
            for o in orders
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

    registry.register(CUSTOMER_TOOLS[0], _mk(get_customer_segments))
    registry.register(CUSTOMER_TOOLS[1], _mk(find_customers))
    registry.register(CUSTOMER_TOOLS[2], _mk(get_customer_profile))
