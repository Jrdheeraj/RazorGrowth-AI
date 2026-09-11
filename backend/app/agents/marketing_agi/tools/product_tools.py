"""Product knowledge tools — catalog, performance, cross-sell affinities."""
from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.order import Order, OrderItem
from backend.app.models.product import Product
from backend.app.agents.marketing_agi.tools.registry import ToolSpec

PRODUCT_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="get_product_catalog",
        category="products",
        description="List merchant products with price, category, stock.",
        capabilities=["catalog"],
    ),
    ToolSpec(
        name="get_product_performance",
        category="products",
        description="Best/worst selling products by real order-item data.",
        capabilities=["performance"],
    ),
    ToolSpec(
        name="get_product_affinities",
        category="products",
        description=(
            "Products frequently bought together — real basket analysis for "
            "cross-sell campaign design."
        ),
        capabilities=["cross_sell", "basket_patterns"],
    ),
]


def get_product_catalog(
    db: Session, merchant_id: uuid.UUID, *, limit: int = 50
) -> dict[str, Any]:
    products = list(
        db.scalars(
            select(Product)
            .where(Product.merchant_id == merchant_id, Product.active.is_(True))
            .order_by(Product.name)
            .limit(limit)
        ).all()
    )
    return {
        "product_count": len(products),
        "products": [
            {
                "product_id": str(p.id),
                "name": p.name,
                "category": p.category,
                "price_inr": float(p.price),
                "stock_quantity": int(p.stock_quantity or 0),
            }
            for p in products
        ],
    }


def get_product_performance(
    db: Session, merchant_id: uuid.UUID, *, limit: int = 10
) -> dict[str, Any]:
    rows = db.execute(
        select(
            Product.name,
            func.count(OrderItem.id),
            func.coalesce(func.sum(OrderItem.line_total), 0),
        )
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.merchant_id == merchant_id)
        .group_by(Product.name)
        .order_by(func.sum(OrderItem.line_total).desc())
    ).all()

    all_rows = [
        {"product": r[0], "units_sold": int(r[1]), "revenue_inr": float(r[2])}
        for r in rows
    ]
    return {
        "top_products": all_rows[:limit],
        "bottom_products": all_rows[-limit:] if len(all_rows) > limit else [],
        "product_count": len(all_rows),
    }


def get_product_affinities(
    db: Session, merchant_id: uuid.UUID, *, limit: int = 10
) -> dict[str, Any]:
    """Products that genuinely appear in the same orders."""
    order_items = db.execute(
        select(Order.id, Product.name)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .join(Product, Product.id == OrderItem.product_id)
        .where(Order.merchant_id == merchant_id)
    ).all()

    by_order: defaultdict[Any, set[str]] = defaultdict(set)
    for order_id, name in order_items:
        by_order[order_id].add(name)

    pairs: Counter = Counter()
    for items in by_order.values():
        ordered = sorted(items)
        for i, a in enumerate(ordered):
            for b in ordered[i + 1 :]:
                pairs[(a, b)] += 1

    return {
        "affinities": [
            {"product_a": a, "product_b": b, "co_orders": n}
            for (a, b), n in pairs.most_common(limit)
        ],
        "multi_item_order_count": sum(1 for v in by_order.values() if len(v) > 1),
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

    registry.register(PRODUCT_TOOLS[0], _mk(get_product_catalog, limit=50))
    registry.register(PRODUCT_TOOLS[1], _mk(get_product_performance, limit=10))
    registry.register(PRODUCT_TOOLS[2], _mk(get_product_affinities, limit=10))
