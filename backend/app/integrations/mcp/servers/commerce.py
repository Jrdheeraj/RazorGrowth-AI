"""MCP commerce server — the real catalog, inventory and order primitives.

This is the ``commerce`` capability domain the Product Agent is granted.
Every handler is a thin adapter over
``services.product_intelligence`` (and the platform's own repositories),
so there is exactly ONE implementation of each query and the Product
Agent reaches it only through the shared MCP client.

All tools are READ-ONLY and tenant-scoped: the merchant id always comes
from the injected ``context``, never from tool arguments, and every query
filters by it in SQL.

The snapshot read is the expensive one, so ``get_inventory`` /
``get_low_stock_products`` / ``get_product_sales`` all project from a
single cached snapshot rather than re-querying per tool. The cache lives
in the MCP execution context, which is cleared at the start of every run,
so nothing survives across tenants or runs.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from backend.app.integrations.mcp.schemas import MCPToolSpec
from backend.app.services import product_intelligence as pi

MCP_SERVER = "commerce"


def _ctx_or_default(context: Any, db: Session, merchant_id: uuid.UUID) -> Any:
    """Context for a direct handler call that bypassed the client.

    The MCP client always injects a real context; this exists so the
    handlers stay callable from tests and server-side code with the same
    tenant binding.
    """
    if context is not None:
        return context
    from backend.app.integrations.mcp.context import MCPExecutionContext

    return MCPExecutionContext(db=db, merchant_id=merchant_id)


def _snapshot(
    db: Session,
    merchant_id: uuid.UUID,
    window_days: int,
    threshold: int,
    context: Any = None,
) -> pi.CatalogSnapshot:
    """One snapshot per (window, threshold) per run, in the MCP run cache.

    The cache object belongs to ``MCPExecutionContext``, which the agent
    clears at the start of every run and whose keys are tenant-bound. So
    this reuse can never serve one merchant's rows to another, and never
    survives a run boundary.
    """
    ctx = _ctx_or_default(context, db, merchant_id)
    key = ctx.cache_key("commerce.snapshot", {"w": window_days, "t": threshold})
    cached = ctx.cache.get(key)
    if cached is None:
        cached = pi.build_snapshot(
            db,
            merchant_id,
            window_days=window_days,
            low_stock_threshold=threshold,
        )
        ctx.cache[key] = cached
    return cached


def _list_products(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
    limit: int = 50,
    offset: int = 0,
    include_inactive: bool = False,
) -> dict[str, Any]:
    """Real catalog rows with price, stock and content completeness."""
    products = pi.list_catalog_products(
        db,
        merchant_id,
        active_only=not bool(include_inactive),
        limit=int(limit),
        offset=int(offset),
    )
    return {
        "product_count": len(products),
        "include_inactive": bool(include_inactive),
        "products": [
            {
                "product_id": str(p.id),
                "name": p.name,
                "sku": p.sku,
                "category": p.category,
                "price_inr": float(p.price or 0),
                "stock_quantity": int(p.stock_quantity or 0),
                "active": bool(p.active),
                "has_description": bool((p.description or "").strip()),
                "description_chars": len((p.description or "").strip()),
            }
            for p in products
        ],
        "source": "products_table",
    }


def _get_product(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
    product_id: str = "",
) -> dict[str, Any]:
    """One catalog row. Tenant-checked; a foreign id is not found."""
    product = pi.get_product_by_id(db, merchant_id, product_id)
    if product is None:
        return {
            "found": False,
            "product_id": product_id,
            "note": "No product with that id exists in this workspace.",
        }
    return {
        "found": True,
        "product": {
            "product_id": str(product.id),
            "name": product.name,
            "sku": product.sku,
            "category": product.category,
            "price_inr": float(product.price or 0),
            "currency": product.currency,
            "stock_quantity": int(product.stock_quantity or 0),
            "active": bool(product.active),
            "description": product.description,
        },
        "source": "products_table",
    }


def _get_inventory(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
    window_days: int = 90,
    low_stock_threshold: int = pi.DEFAULT_LOW_STOCK_THRESHOLD,
) -> dict[str, Any]:
    """Catalog-wide inventory picture: units, value, coverage."""
    snap = _snapshot(
        db, merchant_id, int(window_days), int(low_stock_threshold), context
    )
    return {
        **snap.summary(),
        "products": [
            {
                "product_id": r["product_id"],
                "name": r["name"],
                "category": r["category"],
                "stock_quantity": r["stock_quantity"],
                "price_inr": r["price_inr"],
                "stock_value_inr": r["stock_value_inr"],
                "units_sold": r["units_sold"],
                "low_stock": r["low_stock"],
            }
            for r in snap.products
        ],
    }


def _get_low_stock_products(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
    window_days: int = 90,
    low_stock_threshold: int = pi.DEFAULT_LOW_STOCK_THRESHOLD,
    projection_days: int = pi.DEFAULT_PROJECTION_DAYS,
) -> dict[str, Any]:
    """Products at risk of running out, from real stock + real velocity."""
    snap = _snapshot(
        db, merchant_id, int(window_days), int(low_stock_threshold), context
    )
    result = pi.low_stock_risk(snap, projection_days=int(projection_days))
    return {"window_days": int(window_days), **result}


def _get_product_sales(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
    product_id: str = "",
    window_days: int = 90,
) -> dict[str, Any]:
    """Real units and revenue for ONE product, plus its catalog context.

    When ``product_id`` is omitted every product's sales are returned, so
    the caller gets the whole demand picture in one call instead of N.
    """
    snap = _snapshot(
        db,
        merchant_id,
        int(window_days),
        pi.DEFAULT_LOW_STOCK_THRESHOLD,
        context,
    )
    if product_id:
        row = next(
            (r for r in snap.products if r["product_id"] == str(product_id)), None
        )
        if row is None:
            return {
                "found": False,
                "product_id": product_id,
                "note": "No product with that id exists in this workspace.",
            }
        return {"found": True, "window_days": int(window_days), "sales": [row]}
    return {
        "found": True,
        "window_days": int(window_days),
        "settled_orders": snap.order_count,
        "total_units_sold": snap.total_units_sold,
        "total_revenue_inr": snap.total_revenue_inr,
        "sales": [
            {
                "product_id": r["product_id"],
                "name": r["name"],
                "category": r["category"],
                "units_sold": r["units_sold"],
                "revenue_inr": r["revenue_inr"],
                "orders": r["orders"],
                "trend_pct": r["trend_pct"],
            }
            for r in snap.products
        ],
    }


def _get_orders(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
    limit: int = 50,
    window_days: int | None = None,
) -> dict[str, Any]:
    """Real order rows with line items for this workspace."""
    rows = pi.order_rows(
        db, merchant_id, limit=int(limit), window_days=window_days
    )
    return {
        "count": len(rows),
        "window_days": window_days,
        "orders": rows,
        "source": "orders_and_order_items",
    }


# ── schema helpers ─────────────────────────────────────────────────────


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": required or [],
        "additionalProperties": False,
    }


_WINDOW = {
    "type": "integer",
    "minimum": 1,
    "maximum": 365,
    "default": 90,
    "description": "Lookback window in days for demand measurement.",
}
_THRESHOLD = {
    "type": "integer",
    "minimum": 0,
    "maximum": 10000,
    "default": pi.DEFAULT_LOW_STOCK_THRESHOLD,
    "description": "Low-stock threshold in units.",
}


def TOOLS() -> list[MCPToolSpec]:  # noqa: N802 - registry-facing factory
    """Declarations for the commerce (catalog / inventory) MCP server."""
    return [
        MCPToolSpec(
            name="commerce.list_products",
            description=(
                "This workspace's real product catalog: name, SKU, category, "
                "list price, stock on hand and whether a description exists."
            ),
            provider="internal",
            handler=_list_products,
            phase="observe",
            input_schema=_schema(
                {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
                    "offset": {"type": "integer", "minimum": 0, "default": 0},
                    "include_inactive": {"type": "boolean", "default": False},
                }
            ),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="commerce.get_product",
            description="One real catalog row by product id. Tenant-scoped.",
            provider="internal",
            handler=_get_product,
            phase="observe",
            input_schema=_schema(
                {"product_id": {"type": "string", "minLength": 1, "maxLength": 64}},
                required=["product_id"],
            ),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="commerce.get_inventory",
            description=(
                "Inventory picture for the whole catalog: units on hand, stock "
                "value at list price, category coverage and low-stock count."
            ),
            provider="internal",
            handler=_get_inventory,
            phase="observe",
            input_schema=_schema(
                {"window_days": _WINDOW, "low_stock_threshold": _THRESHOLD}
            ),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="commerce.get_low_stock_products",
            description=(
                "Products at risk of running out, from the configured stock "
                "threshold OR projected demand exceeding available stock."
            ),
            provider="internal",
            handler=_get_low_stock_products,
            phase="observe",
            input_schema=_schema(
                {
                    "window_days": _WINDOW,
                    "low_stock_threshold": _THRESHOLD,
                    "projection_days": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 365,
                        "default": pi.DEFAULT_PROJECTION_DAYS,
                    },
                }
            ),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="commerce.get_product_sales",
            description=(
                "Real units sold and revenue per product over a window, summed "
                "from order line quantities. Omit product_id for the full "
                "catalog demand picture."
            ),
            provider="internal",
            handler=_get_product_sales,
            phase="observe",
            input_schema=_schema(
                {"product_id": {"type": "string", "maxLength": 64}, "window_days": _WINDOW}
            ),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="commerce.get_orders",
            description=(
                "Real order rows with their line items for this workspace, "
                "newest first."
            ),
            provider="internal",
            handler=_get_orders,
            phase="observe",
            input_schema=_schema(
                {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                    "window_days": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 365,
                    },
                }
            ),
            output_schema={"type": "object"},
        ),
    ]


__all__ = ["MCP_SERVER", "TOOLS", "clear_snapshot_cache"]