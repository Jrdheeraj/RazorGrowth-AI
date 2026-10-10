"""Deterministic product intelligence over the REAL catalog and orders.

Everything here is arithmetic on rows that already exist in this
workspace's database: ``products``, ``orders`` and ``order_items``. No
estimate, no projection and no invented price is ever produced. When a
signal genuinely cannot be computed from the available data the function
returns an explicit ``insufficient``/``unavailable`` marker plus the
reason, so the caller (and the merchant) sees an honest gap instead of a
plausible number.

This module is the single implementation of the product-level maths. The
MCP tools in ``integrations/mcp/servers/`` are thin adapters over these
functions, so the Product Agent reaches every calculation through the
shared MCP layer while the SQL stays in one reviewable place.

The three hard rules encoded here:

  1. Demand is ``SUM(order_items.quantity)`` over REAL demand order
     statuses — never a line-item count.
  2. A product with zero sales is a first-class result, never absent.
  3. "Not enough data" is a valid, returned answer.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.order import Order, OrderItem
from backend.app.models.product import Product

#: Order statuses that represent real, settled demand. A cancelled or
#: refunded order is NOT demand and must never inflate performance.
DEMAND_ORDER_STATUSES: tuple[str, ...] = (
    "pending",
    "confirmed",
    "paid",
    "shipped",
    "delivered",
)

#: Default low-stock threshold in units. Overridable per call; declared as
#: a constant so every threshold decision in the platform is greppable.
DEFAULT_LOW_STOCK_THRESHOLD = 10

#: Days of forward demand used to project a stockout.
DEFAULT_PROJECTION_DAYS = 30

#: Minimum settled orders in the window before a performance comparison is
#: meaningful. Below this the answer is "insufficient data", not "bad".
MIN_ORDERS_FOR_PERFORMANCE = 5

#: Minimum multi-item orders before a bundle claim can be quantified.
MIN_MULTI_ITEM_ORDERS_FOR_BUNDLES = 3

#: Fields a product must carry to be considered content-complete.
CONTENT_FIELDS = ("description", "sku", "category")

#: A description shorter than this reads as a placeholder, not real copy.
MIN_DESCRIPTION_CHARS = 40

#: Weights used for the catalog-health score. They sum to 1.0 so the score
#: is directly readable as a percentage. Changing a weight changes the
#: published meaning of the number, so it is declared here once.
HEALTH_WEIGHTS: dict[str, float] = {
    "content_completeness": 0.35,
    "inventory_health": 0.30,
    "demand_health": 0.35,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_float(value: Any) -> float | None:
    """Coerce a DB numeric/decimal/int to float, or None when not numeric."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_utc(value: datetime | None) -> datetime | None:
    """Attach UTC to a naive datetime read back from the database.

    PostgreSQL returns timezone-aware timestamps; some drivers and SQLite
    return naive ones. Comparing a naive stored value against an aware
    window boundary would raise, so every Python-side comparison normalises
    first. The values are always UTC by construction.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


@dataclass
class CatalogSnapshot:
    """The real catalog plus the derived totals the dashboard renders."""

    products: list[dict[str, Any]] = field(default_factory=list)
    generated_at: datetime = field(default_factory=utcnow)
    window_days: int = 90
    low_stock_threshold: int = DEFAULT_LOW_STOCK_THRESHOLD
    multi_item_order_count: int = 0

    # ── derived catalog facts ────────────────────────────────────────────

    @property
    def product_count(self) -> int:
        return len(self.products)

    @property
    def total_units(self) -> int:
        return sum(int(p["stock_quantity"]) for p in self.products)

    @property
    def categories(self) -> list[str]:
        return sorted({str(p["category"]) for p in self.products if p["category"]})

    @property
    def category_count(self) -> int:
        return len(self.categories)

    @property
    def catalog_value_inr(self) -> float:
        """Stock value at list price — real price × real on-hand units."""
        return round(
            sum(float(p["price_inr"]) * int(p["stock_quantity"]) for p in self.products),
            2,
        )

    @property
    def in_stock_count(self) -> int:
        return sum(1 for p in self.products if int(p["stock_quantity"]) > 0)

    @property
    def out_of_stock_count(self) -> int:
        return self.product_count - self.in_stock_count

    @property
    def total_units_sold(self) -> int:
        return sum(int(p["units_sold"]) for p in self.products)

    @property
    def total_revenue_inr(self) -> float:
        return round(sum(float(p["revenue_inr"]) for p in self.products), 2)

    @property
    def order_count(self) -> int:
        return int(self.metrics.get("settled_orders") or 0)

    @property
    def average_order_value_inr(self) -> float | None:
        orders = self.order_count
        if orders <= 0:
            return None
        return round(self.total_revenue_inr / orders, 2)

    @property
    def low_stock_count(self) -> int:
        return sum(1 for p in self.products if p["low_stock"])

    @property
    def never_sold_count(self) -> int:
        return sum(1 for p in self.products if int(p["units_sold"]) == 0)

    metrics: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        """Tenant-safe aggregate projection (no ids, no payloads)."""
        return {
            "window_days": self.window_days,
            "generated_at": self.generated_at.isoformat(),
            "product_count": self.product_count,
            "total_units": self.total_units,
            "in_stock_count": self.in_stock_count,
            "out_of_stock_count": self.out_of_stock_count,
            "category_count": self.category_count,
            "categories": self.categories,
            "catalog_value_inr": self.catalog_value_inr,
            "low_stock_threshold": self.low_stock_threshold,
            "low_stock_count": self.low_stock_count,
            "total_units_sold": self.total_units_sold,
            "total_revenue_inr": self.total_revenue_inr,
            "settled_orders": self.order_count,
            "average_order_value_inr": self.average_order_value_inr,
            "never_sold_count": self.never_sold_count,
            "multi_item_order_count": self.multi_item_order_count,
            "data_completeness": (
                "full" if self.product_count and self.order_count else "no_data"
            ),
        }


def _demand_statuses() -> list[str]:
    return list(DEMAND_ORDER_STATUSES)


def list_catalog_products(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    active_only: bool = True,
    limit: int = 200,
    offset: int = 0,
) -> list[Product]:
    """Real catalog rows for this workspace, ordered by name."""
    stmt = select(Product).where(Product.merchant_id == merchant_id)
    if active_only:
        stmt = stmt.where(Product.active.is_(True))
    stmt = stmt.order_by(Product.name).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def get_product_by_id(
    db: Session, merchant_id: uuid.UUID, product_id: str
) -> Product | None:
    """One catalog row, always tenant-checked."""
    try:
        pid = uuid.UUID(str(product_id))
    except (TypeError, ValueError):
        return None
    product = db.get(Product, pid)
    if product is None or product.merchant_id != merchant_id:
        return None
    return product


def _sales_rows(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    window_start: datetime | None,
) -> tuple[dict[uuid.UUID, dict[str, Any]], set[uuid.UUID], int]:
    """One grouped query: real units/revenue per product over the window.

    Returns ``(per_product, order_ids_in_window, multi_item_order_count)``.
    ``SUM(quantity)`` is the unit count (a line-item COUNT would silently
    under-report every multi-unit order), and the join is a LEFT-style
    aggregation performed in Python over product rows so a never-sold
    product yields a real zero rather than disappearing.
    """
    # One grouped read feeds three facts (units, revenue, distinct orders)
    # AND the order→product basket map needed for affinity. A single pass
    # keeps the snapshot to one query instead of three.
    stmt = (
        select(
            OrderItem.product_id,
            OrderItem.order_id,
            OrderItem.quantity,
            OrderItem.line_total,
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.merchant_id == merchant_id,
            Order.status.in_(_demand_statuses()),
        )
    )
    if window_start is not None:
        stmt = stmt.where(Order.created_at >= window_start)

    per_product: dict[uuid.UUID, dict[str, Any]] = {}
    product_orders: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    baskets: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for product_id, order_id, quantity, line_total in db.execute(stmt).all():
        agg = per_product.setdefault(
            product_id,
            {"units_sold": 0, "revenue_inr": 0.0, "order_count": 0},
        )
        agg["units_sold"] += int(quantity or 0)
        agg["revenue_inr"] += float(line_total or 0)
        product_orders[product_id].add(order_id)
        baskets[order_id].add(product_id)

    for product_id, order_ids in product_orders.items():
        agg = per_product.get(product_id)
        if agg is not None:
            agg["order_count"] = len(order_ids)

    multi_item = sum(1 for v in baskets.values() if len(v) > 1)
    return per_product, set(baskets), multi_item


def _trend_per_product(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    current_start: datetime,
    prior_start: datetime,
    now: datetime,
) -> dict[uuid.UUID, dict[str, int]]:
    """Recent vs prior half-window unit counts, per product.

    Uses the SAME two scalar windows the frontend already renders, so the
    Product Agent and the workspace tables agree on what "trend" means.
    """
    out: dict[uuid.UUID, dict[str, int]] = defaultdict(
        lambda: {"recent_units": 0, "prior_units": 0}
    )
    stmt = (
        select(OrderItem.product_id, OrderItem.quantity, Order.created_at)
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.merchant_id == merchant_id,
            Order.status.in_(_demand_statuses()),
            Order.created_at >= prior_start,
            Order.created_at <= now,
        )
    )
    for product_id, quantity, created_at in db.execute(stmt).all():
        created_at = _as_utc(created_at)
        if created_at is None:
            continue
        if created_at >= current_start:
            out[product_id]["recent_units"] += int(quantity or 0)
        else:
            out[product_id]["prior_units"] += int(quantity or 0)
    return dict(out)


def _window_start(window_days: int, now: datetime | None = None) -> datetime:
    return (now or utcnow()) - timedelta(days=max(1, int(window_days)))


def build_snapshot(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    window_days: int = 90,
    low_stock_threshold: int = DEFAULT_LOW_STOCK_THRESHOLD,
    active_only: bool = True,
) -> CatalogSnapshot:
    """Real catalog + real windowed demand, joined per product.

    This is the single expensive read behind every Product Agent stage.
    The MCP per-run cache serves it to whichever tool asks first, so the
    agent pays for it once per run rather than once per tool.
    """
    now = utcnow()
    window_start = _window_start(window_days, now)
    products = list_catalog_products(
        db, merchant_id, active_only=active_only, limit=500
    )
    sales, order_ids, multi_item = _sales_rows(
        db, merchant_id, window_start=window_start
    )
    half = max(1, int(window_days) // 2)
    current_start = now - timedelta(days=half)
    prior_start = now - timedelta(days=int(window_days))
    trend = _trend_per_product(
        db,
        merchant_id,
        current_start=current_start,
        prior_start=prior_start,
        now=now,
    )

    rows: list[dict[str, Any]] = []
    settled_revenue = 0.0
    for product in products:
        agg = sales.get(product.id, {"units_sold": 0, "revenue_inr": 0.0, "order_count": 0})
        units = int(agg["units_sold"])
        revenue = round(float(agg["revenue_inr"]), 2)
        settled_revenue += revenue
        stock = int(product.stock_quantity or 0)
        price = float(product.price or 0)
        t = trend.get(product.id, {"recent_units": 0, "prior_units": 0})
        prior_units = int(t["prior_units"])
        recent_units = int(t["recent_units"])
        rows.append(
            {
                "product_id": str(product.id),
                "name": product.name,
                "sku": product.sku,
                "category": product.category,
                "price_inr": round(price, 2),
                "stock_quantity": stock,
                "active": bool(product.active),
                "description": product.description,
                "units_sold": units,
                "revenue_inr": revenue,
                "orders": int(agg["order_count"]),
                "low_stock": stock <= int(low_stock_threshold),
                "recent_units": recent_units,
                "prior_units": prior_units,
                "trend_pct": (
                    round((recent_units - prior_units) / prior_units * 100.0, 1)
                    if prior_units > 0
                    else None
                ),
                "stock_value_inr": round(price * stock, 2),
            }
        )

    snapshot = CatalogSnapshot(
        products=rows,
        generated_at=now,
        window_days=int(window_days),
        low_stock_threshold=int(low_stock_threshold),
        multi_item_order_count=multi_item,
    )
    snapshot.metrics = {
        "settled_orders": len(order_ids),
        "window_revenue_inr": round(settled_revenue, 2),
        "trend_window_days": half,
    }
    return snapshot


# ---------------------------------------------------------------------------
# Inventory risk
# ---------------------------------------------------------------------------


def low_stock_risk(
    snapshot: CatalogSnapshot,
    *,
    projection_days: int = DEFAULT_PROJECTION_DAYS,
    threshold: int | None = None,
) -> dict[str, Any]:
    """Low-stock risks from the configured threshold OR projected demand.

    Two independent, real triggers:

      * ``stock <= threshold``                    — configured floor
      * ``projected_demand > stock``              — observed daily velocity
        extrapolated over ``projection_days``

    Velocity is only used when the product actually sold in the window;
    a never-sold product gets ``velocity_source: "no_sales"`` and is never
    projected from an invented rate.
    """
    limit = int(threshold if threshold is not None else snapshot.low_stock_threshold)
    days = max(1, int(projection_days))
    risks: list[dict[str, Any]] = []
    for row in snapshot.products:
        stock = int(row["stock_quantity"])
        units = int(row["units_sold"])
        window_days = max(1, int(snapshot.window_days))
        daily = (units / window_days) if units > 0 else 0.0
        projected = round(daily * days, 2)
        reasons: list[str] = []
        if stock <= limit:
            reasons.append("below_configured_threshold")
        if units > 0 and projected > stock:
            reasons.append("projected_demand_exceeds_stock")
        if not reasons:
            continue
        risks.append(
            {
                "product_id": row["product_id"],
                "name": row["name"],
                "category": row["category"],
                "stock_quantity": stock,
                "threshold": limit,
                "units_sold_in_window": units,
                "daily_velocity": round(daily, 3),
                "projected_demand_units": projected,
                "projection_days": days,
                "velocity_source": "observed_sales" if units > 0 else "no_sales",
                "reasons": reasons,
                "severity": "high" if stock == 0 else "medium",
            }
        )
    risks.sort(key=lambda r: (r["stock_quantity"], -r["units_sold_in_window"]))
    return {
        "threshold": limit,
        "projection_days": days,
        "risk_count": len(risks),
        "risks": risks,
        "method": (
            "stock <= configured threshold, or projected demand (observed "
            "daily velocity x projection days) greater than available stock"
        ),
    }


# ---------------------------------------------------------------------------
# Performance diagnosis
# ---------------------------------------------------------------------------


def _category_benchmarks(
    snapshot: CatalogSnapshot,
) -> dict[str, dict[str, float]]:
    """Per-category revenue-per-SKU and units-per-SKU averages."""
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in snapshot.products:
        by_category[str(row["category"])].append(row)
    out: dict[str, dict[str, float]] = {}
    for category, rows in by_category.items():
        count = len(rows) or 1
        out[category] = {
            "sku_count": float(count),
            "avg_revenue_inr": round(
                sum(float(r["revenue_inr"]) for r in rows) / count, 2
            ),
            "avg_units": round(
                sum(float(r["units_sold"]) for r in rows) / count, 2
            ),
        }
    return out


def underperforming_products(
    snapshot: CatalogSnapshot, *, limit: int = 10
) -> dict[str, Any]:
    """Products materially below their category AND the catalog average.

    Comparison is relative (category benchmark + catalog benchmark), never
    an arbitrary absolute bar. With too few settled orders the honest
    answer is ``insufficient_data`` — not a list of "bad" products.
    """
    orders = snapshot.order_count
    if snapshot.product_count == 0:
        return {
            "status": "insufficient_data",
            "reason": "This workspace has no products in its catalog.",
            "count": 0,
            "underperforming": [],
        }
    if orders < MIN_ORDERS_FOR_PERFORMANCE:
        return {
            "status": "insufficient_data",
            "reason": (
                f"Only {orders} settled order(s) in the last "
                f"{snapshot.window_days} days; fewer than "
                f"{MIN_ORDERS_FOR_PERFORMANCE} are needed to compare product "
                "performance."
            ),
            "settled_orders": orders,
            "min_orders_required": MIN_ORDERS_FOR_PERFORMANCE,
            "count": 0,
            "underperforming": [],
        }

    benchmarks = _category_benchmarks(snapshot)
    catalog_avg_revenue = (
        snapshot.total_revenue_inr / snapshot.product_count
        if snapshot.product_count
        else 0.0
    )
    rows: list[dict[str, Any]] = []
    for row in snapshot.products:
        category = str(row["category"])
        bench = benchmarks.get(category, {})
        cat_avg = float(bench.get("avg_revenue_inr", catalog_avg_revenue))
        revenue = float(row["revenue_inr"])
        units = int(row["units_sold"])
        # Underperformance = below BOTH its own category and the catalog mean.
        # A zero-revenue SKU is the strongest signal available.
        vs_category = round((revenue - cat_avg) / cat_avg * 100.0, 1) if cat_avg > 0 else None
        vs_catalog = (
            round((revenue - catalog_avg_revenue) / catalog_avg_revenue * 100.0, 1)
            if catalog_avg_revenue > 0
            else None
        )
        never_sold = units == 0
        below_both = (
            (vs_category is not None and vs_category <= -25.0)
            and (vs_catalog is not None and vs_catalog <= -25.0)
        )
        if never_sold:
            below_both = True
        if not below_both:
            continue
        rows.append(
            {
                "product_id": row["product_id"],
                "name": row["name"],
                "category": category,
                "price_inr": row["price_inr"],
                "stock_quantity": row["stock_quantity"],
                "units_sold": units,
                "revenue_inr": revenue,
                "orders": row["orders"],
                "trend_pct": row["trend_pct"],
                "category_avg_revenue_inr": round(cat_avg, 2),
                "catalog_avg_revenue_inr": round(catalog_avg_revenue, 2),
                "vs_category_pct": vs_category,
                "vs_catalog_pct": vs_catalog,
                "never_sold": never_sold,
                "severity": "high" if never_sold else "medium",
                "basis": "revenue_per_sku_vs_category_and_catalog_average",
            }
        )
    rows.sort(key=lambda r: (not r["never_sold"], r["revenue_inr"]))
    return {
        "status": "available",
        "settled_orders": orders,
        "window_days": snapshot.window_days,
        "catalog_avg_revenue_inr": round(catalog_avg_revenue, 2),
        "category_benchmarks": benchmarks,
        "method": (
            "revenue per SKU compared against its category average and the "
            "catalog average; a product with zero settled units always counts"
        ),
        "count": len(rows),
        "underperforming": rows[: max(1, int(limit))],
    }


def product_performance(
    snapshot: CatalogSnapshot, *, limit: int = 10
) -> dict[str, Any]:
    """Ranked product performance including never-sold SKUs.

    One row per catalog product with real units, revenue and rank. The
    ``never_sold`` flag is what makes "your worst performer is invisible"
    impossible.
    """
    ordered = sorted(
        snapshot.products,
        key=lambda r: (-float(r["revenue_inr"]), -int(r["units_sold"]), str(r["name"])),
    )
    rows: list[dict[str, Any]] = []
    total_revenue = snapshot.total_revenue_inr
    for index, row in enumerate(ordered, start=1):
        revenue = float(row["revenue_inr"])
        rows.append(
            {
                "rank": index,
                "product_id": row["product_id"],
                "name": row["name"],
                "category": row["category"],
                "price_inr": row["price_inr"],
                "stock_quantity": row["stock_quantity"],
                "units_sold": int(row["units_sold"]),
                "revenue_inr": revenue,
                "orders": row["orders"],
                "trend_pct": row["trend_pct"],
                "revenue_share_pct": (
                    round(revenue / total_revenue * 100.0, 2) if total_revenue > 0 else 0.0
                ),
                "never_sold": int(row["units_sold"]) == 0,
                "status": _performance_status(snapshot, index, revenue),
            }
        )
    never_sold = [r for r in rows if r["never_sold"]]
    return {
        "status": "available" if rows else "insufficient_data",
        "window_days": snapshot.window_days,
        "settled_orders": snapshot.order_count,
        "total_revenue_inr": total_revenue,
        "total_units_sold": snapshot.total_units_sold,
        "product_count": len(rows),
        "never_sold_count": len(never_sold),
        "average_order_value_inr": snapshot.average_order_value_inr,
        "top_products": rows[: max(1, int(limit))],
        "bottom_products": list(reversed(rows[-max(1, int(limit)) :]))
        if len(rows) > 1
        else [],
        "all_products": rows,
    }


def _performance_status(
    snapshot: CatalogSnapshot, rank: int, revenue: float
) -> str:
    """Honest per-product status label derived from the same snapshot."""
    if snapshot.order_count == 0:
        return "unavailable"
    if revenue <= 0:
        return "no_demand"
    if rank <= max(1, snapshot.product_count // 3):
        return "strong"
    if rank >= max(2, (snapshot.product_count * 2) // 3):
        return "underperforming"
    return "steady"


# ---------------------------------------------------------------------------
# Content gaps
# ---------------------------------------------------------------------------


def content_gaps(
    snapshot: CatalogSnapshot, *, min_description_chars: int = MIN_DESCRIPTION_CHARS
) -> dict[str, Any]:
    """Missing or thin catalog content, from real field inspection.

    Reports what the platform can actually verify (description, SKU,
    category, description length). Product photography is reported as an
    explicit platform limitation rather than as a per-product gap, because
    the schema has no image field to inspect — claiming "this product has
    no image" would be a fabricated finding.
    """
    gaps: list[dict[str, Any]] = []
    complete = 0
    for row in snapshot.products:
        missing: list[str] = []
        weak: list[str] = []
        description = (row.get("description") or "").strip()
        if not description:
            missing.append("description")
        elif len(description) < int(min_description_chars):
            weak.append("description_too_short")
        if not (row.get("sku") or "").strip():
            missing.append("sku")
        if not (row.get("category") or "").strip():
            missing.append("category")
        if not missing and not weak:
            complete += 1
            continue
        gaps.append(
            {
                "product_id": row["product_id"],
                "name": row["name"],
                "category": row["category"],
                "units_sold": int(row["units_sold"]),
                "revenue_inr": float(row["revenue_inr"]),
                "missing_fields": missing,
                "weak_fields": weak,
                "description_chars": len(description),
                "severity": "high" if (missing and float(row["revenue_inr"]) > 0) else "medium",
            }
        )
    gaps.sort(key=lambda g: (-float(g["revenue_inr"]), str(g["name"])))
    total = snapshot.product_count
    return {
        "status": "available" if total else "insufficient_data",
        "method": (
            "inspection of the real product record: description present and "
            f"at least {int(min_description_chars)} characters, SKU present, "
            "category present"
        ),
        "inspected_fields": list(CONTENT_FIELDS),
        "product_count": total,
        "complete_count": complete,
        "gap_count": len(gaps),
        "completeness_pct": round(complete / total * 100.0, 1) if total else 0.0,
        "platform_limitations": [
            (
                "Product photography cannot be audited: the products table "
                "stores no image field, so this platform cannot verify image "
                "coverage for any SKU."
            )
        ],
        "gaps": gaps,
    }


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


def pricing_opportunities(snapshot: CatalogSnapshot) -> dict[str, Any]:
    """Internal price/velocity signals only — never competitor prices.

    No competitor feed, price index or marketplace scrape exists in this
    platform. The tool therefore reports the internal view it can prove
    (a product priced far from its category median, and how fast it
    actually sells at that price) and states plainly that external
    benchmarking is unavailable rather than inventing a competitor.
    """
    by_category: dict[str, list[float]] = defaultdict(list)
    for row in snapshot.products:
        by_category[str(row["category"])].append(float(row["price_inr"]))

    def _median(values: list[float]) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            return round(ordered[mid], 2)
        return round((ordered[mid - 1] + ordered[mid]) / 2, 2)

    medians = {c: _median(v) for c, v in by_category.items()}
    opportunities: list[dict[str, Any]] = []
    for row in snapshot.products:
        category = str(row["category"])
        median = medians.get(category)
        price = float(row["price_inr"])
        units = int(row["units_sold"])
        stock = int(row["stock_quantity"])
        if median is None or median <= 0:
            continue
        delta_pct = round((price - median) / median * 100.0, 1)
        # A real internal signal only when the price gap AND the demand
        # pattern point the same way.
        if abs(delta_pct) < 15.0:
            continue
        signal = None
        if delta_pct > 0 and units == 0 and stock > 0:
            signal = "priced_above_category_without_demand"
        elif delta_pct < 0 and units > 0 and stock <= snapshot.low_stock_threshold:
            signal = "underpriced_and_constrained_by_stock"
        if signal is None:
            continue
        opportunities.append(
            {
                "product_id": row["product_id"],
                "name": row["name"],
                "category": category,
                "price_inr": price,
                "category_median_price_inr": median,
                "price_delta_pct": delta_pct,
                "units_sold": units,
                "revenue_inr": float(row["revenue_inr"]),
                "stock_quantity": stock,
                "signal": signal,
                "basis": "internal_category_median_price_and_observed_demand",
            }
        )
    opportunities.sort(key=lambda o: -abs(float(o["price_delta_pct"])))
    return {
        "status": "available",
        "category_median_price_inr": medians,
        "opportunity_count": len(opportunities),
        "opportunities": opportunities,
        "competitor_pricing": {
            "status": "unavailable",
            "reason": (
                "This platform stores no competitor or marketplace price feed, "
                "so no external price benchmark exists and none is estimated."
            ),
        },
        "method": (
            "internal category median price compared with observed demand; "
            "external benchmarking is reported as unavailable"
        ),
    }


# ---------------------------------------------------------------------------
# Bundles / affinity
# ---------------------------------------------------------------------------


def bundle_opportunities(
    db: Session,
    merchant_id: uuid.UUID,
    snapshot: CatalogSnapshot,
    *,
    window_days: int = 90,
    limit: int = 10,
) -> dict[str, Any]:
    """Real co-purchase affinity with lift — or an honest insufficiency.

    A bundle claim needs actual baskets containing more than one product.
    With fewer than ``MIN_MULTI_ITEM_ORDERS_FOR_BUNDLES`` the result is
    ``insufficient_data`` and no uplift figure is produced at all.
    """
    window_start = _window_start(window_days)
    rows = db.execute(
        select(OrderItem.order_id, OrderItem.product_id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.merchant_id == merchant_id,
            Order.status.in_(_demand_statuses()),
            Order.created_at >= window_start,
        )
    ).all()

    baskets: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for order_id, product_id in rows:
        baskets[order_id].add(product_id)
    multi = [v for v in baskets.values() if len(v) > 1]
    total_orders = len(baskets)
    if len(multi) < MIN_MULTI_ITEM_ORDERS_FOR_BUNDLES:
        return {
            "status": "insufficient_data",
            "reason": (
                f"Only {len(multi)} multi-product order(s) in the last "
                f"{int(window_days)} days (minimum "
                f"{MIN_MULTI_ITEM_ORDERS_FOR_BUNDLES} required). No bundle or "
                "cross-sell uplift can be measured from this data."
            ),
            "multi_item_order_count": len(multi),
            "min_required": MIN_MULTI_ITEM_ORDERS_FOR_BUNDLES,
            "count": 0,
            "bundles": [],
            "impact": {
                "status": "unavailable",
                "reason": "insufficient purchase-history relationship data",
            },
        }

    pairs: dict[tuple[uuid.UUID, uuid.UUID], int] = defaultdict(int)
    singles: dict[uuid.UUID, int] = defaultdict(int)
    for products in baskets.values():
        ordered = sorted(products, key=str)
        for product_id in ordered:
            singles[product_id] += 1
        for i, a in enumerate(ordered):
            for b in ordered[i + 1 :]:
                pairs[(a, b)] += 1

    names = {row["product_id"]: row["name"] for row in snapshot.products}
    ranked = sorted(pairs.items(), key=lambda kv: kv[1], reverse=True)[: max(1, int(limit))]
    bundles: list[dict[str, Any]] = []
    for (a, b), co_orders in ranked:
        pa = singles.get(a, 0) or 1
        pb = singles.get(b, 0) or 1
        # Support = P(B|A); Confidence = P(A|B); lift vs independence.
        support = co_orders / pa
        confidence = co_orders / pb
        lift = (support * total_orders) / pb if pb else 0.0
        bundles.append(
            {
                "product_a_id": str(a),
                "product_a": names.get(str(a), str(a)),
                "product_b_id": str(b),
                "product_b": names.get(str(b), str(b)),
                "co_orders": co_orders,
                "support_pct": round(support * 100.0, 1),
                "confidence_pct": round(confidence * 100.0, 1),
                "lift": round(lift, 3),
                "basis": "orders_containing_both_products",
            }
        )
    return {
        "status": "available",
        "window_days": int(window_days),
        "multi_item_order_count": len(multi),
        "total_orders": total_orders,
        "count": len(bundles),
        "bundles": bundles,
        "impact": {
            "status": "unavailable",
            "reason": (
                "Affinity is measured, but no controlled test has run for any "
                "bundle, so no conversion or revenue uplift is claimed."
            ),
        },
    }


# ---------------------------------------------------------------------------
# Catalog health
# ---------------------------------------------------------------------------


def catalog_health(
    snapshot: CatalogSnapshot,
    *,
    content: dict[str, Any] | None = None,
    inventory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A real composite score from completeness, inventory and demand.

    Every component is a measured ratio over real rows; the weights are
    declared once in ``HEALTH_WEIGHTS`` so the published number has a
    stable, documented meaning.
    """
    content = content or content_gaps(snapshot)
    inventory = inventory or low_stock_risk(snapshot)
    total = snapshot.product_count

    if total == 0:
        return {
            "status": "insufficient_data",
            "reason": "This workspace has no products in its catalog.",
            "score": None,
            "grade": "unavailable",
        }

    completeness = float(content.get("completeness_pct") or 0.0)
    inventory_health = (
        max(0.0, 100.0 - (snapshot.low_stock_count / total) * 100.0)
    )
    sold_products = max(1, total - snapshot.never_sold_count)
    demand_health = sold_products / total * 100.0

    score = (
        completeness * HEALTH_WEIGHTS["content_completeness"]
        + inventory_health * HEALTH_WEIGHTS["inventory_health"]
        + demand_health * HEALTH_WEIGHTS["demand_health"]
    )
    score = round(score, 1)
    if score >= 80:
        grade = "healthy"
    elif score >= 60:
        grade = "needs_attention"
    else:
        grade = "at_risk"
    return {
        "status": "available",
        "score": score,
        "grade": grade,
        "weights": dict(HEALTH_WEIGHTS),
        "components": {
            "content_completeness_pct": round(completeness, 1),
            "inventory_health_pct": round(inventory_health, 1),
            "demand_health_pct": round(demand_health, 1),
        },
        "product_count": total,
        "low_stock_count": snapshot.low_stock_count,
        "never_sold_count": snapshot.never_sold_count,
        "content_gap_count": int(content.get("gap_count") or 0),
        "method": (
            "weighted score of measured content completeness, inventory "
            "coverage and demand coverage across real catalog rows"
        ),
    }


# ---------------------------------------------------------------------------
# Aggregate opportunity view
# ---------------------------------------------------------------------------


def product_opportunities(
    db: Session,
    merchant_id: uuid.UUID,
    snapshot: CatalogSnapshot,
    *,
    limit: int = 25,
) -> dict[str, Any]:
    """Every deterministic opportunity in one structured payload.

    This is what the model reasons over. Each entry carries its own
    ``basis`` so a recommendation can cite the computation that produced
    it, and its own ``status`` so an unavailable signal is visibly
    unavailable instead of silently absent.
    """
    inventory = low_stock_risk(snapshot)
    under = underperforming_products(snapshot)
    content = content_gaps(snapshot)
    pricing = pricing_opportunities(snapshot)
    bundles = bundle_opportunities(
        db, merchant_id, snapshot, window_days=snapshot.window_days
    )
    health = catalog_health(snapshot, content=content, inventory=inventory)

    opportunities: list[dict[str, Any]] = []
    for risk in inventory["risks"]:
        opportunities.append(
            {
                "type": "low_stock",
                "severity": risk["severity"],
                "title": f"Stock risk: {risk['name']}",
                "product_ids": [risk["product_id"]],
                "affected_products": [risk["name"]],
                "detail": (
                    f"{risk['stock_quantity']} unit(s) on hand against a "
                    f"threshold of {risk['threshold']}"
                    + (
                        f"; observed velocity projects {risk['projected_demand_units']} "
                        f"unit(s) over {risk['projection_days']} days"
                        if risk["units_sold_in_window"]
                        else ""
                    )
                ),
                "basis": "commerce inventory + observed demand velocity",
            }
        )
    for row in under.get("underperforming", []):
        opportunities.append(
            {
                "type": "underperforming",
                "severity": row["severity"],
                "title": f"Underperforming: {row['name']}",
                "product_ids": [row["product_id"]],
                "affected_products": [row["name"]],
                "detail": (
                    f"{row['units_sold']} unit(s) and INR {row['revenue_inr']} "
                    f"revenue against a category average of INR "
                    f"{row['category_avg_revenue_inr']}"
                    if not row["never_sold"]
                    else "No settled units in the measured window."
                ),
                "basis": "revenue_per_sku_vs_category_and_catalog_average",
            }
        )
    for gap in content.get("gaps", []):
        opportunities.append(
            {
                "type": "content_gap",
                "severity": gap["severity"],
                "title": f"Content gap: {gap['name']}",
                "product_ids": [gap["product_id"]],
                "affected_products": [gap["name"]],
                "detail": (
                    "missing " + ", ".join(gap["missing_fields"])
                    if gap["missing_fields"]
                    else "weak " + ", ".join(gap["weak_fields"])
                ),
                "basis": "product_record_inspection",
            }
        )
    for row in pricing["opportunities"]:
        opportunities.append(
            {
                "type": "pricing",
                "severity": "medium",
                "title": f"Pricing review: {row['name']}",
                "product_ids": [row["product_id"]],
                "affected_products": [row["name"]],
                "detail": (
                    f"Priced {row['price_delta_pct']}% against a category "
                    f"median of INR {row['category_median_price_inr']} "
                    f"({row['signal'].replace('_', ' ')})"
                ),
                "basis": "internal_category_median_price_and_observed_demand",
            }
        )
    for bundle in bundles.get("bundles", []):
        opportunities.append(
            {
                "type": "bundle",
                "severity": "medium",
                "title": f"Bundle candidate: {bundle['product_a']} + {bundle['product_b']}",
                "product_ids": [bundle["product_a_id"], bundle["product_b_id"]],
                "affected_products": [bundle["product_a"], bundle["product_b"]],
                "detail": (
                    f"Appeared together in {bundle['co_orders']} order(s) "
                    f"({bundle['support_pct']}% support, lift {bundle['lift']})"
                ),
                "basis": "orders_containing_both_products",
            }
        )

    return {
        "window_days": snapshot.window_days,
        "catalog": snapshot.summary(),
        "catalog_health": health,
        "inventory_risk": inventory,
        "underperforming": under,
        "content_gaps": content,
        "pricing": pricing,
        "bundles": bundles,
        "opportunity_count": len(opportunities),
        "opportunities": opportunities[: max(1, int(limit))],
        "unavailable": [
            {"signal": "competitor_pricing", "reason": pricing["competitor_pricing"]["reason"]},
            {"signal": "bundle_uplift", "reason": bundles.get("impact", {}).get("reason")},
            {"signal": "conversion_rate", "reason": (
                "This platform stores no sessions or traffic, so a conversion "
                "rate cannot be computed from order data."
            )},
        ],
    }


def order_rows(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    limit: int = 50,
    window_days: int | None = None,
) -> list[dict[str, Any]]:
    """Real order rows with line items for this workspace."""
    stmt = (
        select(Order)
        .where(Order.merchant_id == merchant_id)
        .order_by(Order.created_at.desc())
        .limit(max(1, int(limit)))
    )
    if window_days:
        stmt = (
            select(Order)
            .where(
                Order.merchant_id == merchant_id,
                Order.created_at >= _window_start(int(window_days)),
            )
            .order_by(Order.created_at.desc())
            .limit(max(1, int(limit)))
        )
    out: list[dict[str, Any]] = []
    for order in db.scalars(stmt).all():
        out.append(
            {
                "order_id": str(order.id),
                "order_number": order.order_number,
                "status": str(getattr(order.status, "value", order.status)),
                "currency": order.currency,
                "subtotal": float(order.subtotal or 0),
                "total": float(order.total or 0),
                "item_count": len(order.items),
                "items": [
                    {
                        "product_id": str(item.product_id),
                        "quantity": int(item.quantity),
                        "unit_price": float(item.unit_price or 0),
                        "line_total": float(item.line_total or 0),
                    }
                    for item in order.items
                ],
                "created_at": order.created_at.isoformat() if order.created_at else None,
            }
        )
    return out


__all__ = [
    "CONTENT_FIELDS",
    "DEFAULT_LOW_STOCK_THRESHOLD",
    "DEFAULT_PROJECTION_DAYS",
    "DEMAND_ORDER_STATUSES",
    "HEALTH_WEIGHTS",
    "MIN_MULTI_ITEM_ORDERS_FOR_BUNDLES",
    "MIN_ORDERS_FOR_PERFORMANCE",
    "CatalogSnapshot",
    "build_snapshot",
    "bundle_opportunities",
    "catalog_health",
    "content_gaps",
    "get_product_by_id",
    "list_catalog_products",
    "low_stock_risk",
    "order_rows",
    "pricing_opportunities",
    "product_opportunities",
    "product_performance",
    "underperforming_products",
]