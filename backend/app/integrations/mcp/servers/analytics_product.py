"""MCP analytics server — product-facing views the platform was missing.

Scope discipline: this server declares ONLY capabilities that do not
already exist in the shared catalog. Revenue, order volume, AOV,
retention, campaign performance and failed payments are all served by the
existing ``marketing.analytics.*`` tools in the ``analytics`` domain, and
the Product Agent is granted that domain — so it already has them and
nothing is duplicated here.

What exists here and why:

  * ``analytics.get_product_performance`` — the existing
    ``marketing.analytics.get_product_performance`` groups by product NAME,
    counts order-item ROWS instead of summing quantity, drops every
    never-sold SKU via an inner join, and carries no product id. It cannot
    support product-level diagnosis. This tool is the correct version:
    quantity-summed, id-carrying, and it reports zero-demand SKUs. Both
    project from the SAME cached snapshot (see ``commerce``), so there is
    still exactly one demand query per run.

  * ``analytics.get_top_products`` — the top-N projection of that same
    snapshot. One implementation, two views.

  * ``analytics.get_conversion`` — declared precisely so the platform can
    ANSWER honestly that it has no traffic/session model. It always
    returns ``available: false`` with the reason. A tool that truthfully
    reports a missing capability is the difference between "insufficient
    data" and an invented conversion rate.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from backend.app.integrations.mcp.schemas import MCPToolSpec
from backend.app.services import product_intelligence as pi
from backend.app.integrations.mcp.servers.commerce import _snapshot

MCP_SERVER = "analytics"


def _get_product_performance(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
    window_days: int = 90,
    limit: int = 10,
) -> dict[str, Any]:
    """Ranked per-product performance including never-sold products."""
    snap = _snapshot(
        db,
        merchant_id,
        int(window_days),
        pi.DEFAULT_LOW_STOCK_THRESHOLD,
        context,
    )
    result = pi.product_performance(snap, limit=int(limit))
    # ``all_products`` is only needed when the caller asked for the full
    # picture; the LLM-facing default keeps the ranked head.
    all_rows = result.pop("all_products", [])
    return {**result, "all_products": all_rows if len(all_rows) <= 25 else []}


def _get_top_products(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
    window_days: int = 90,
    limit: int = 5,
) -> dict[str, Any]:
    """The best-performing products by real revenue, with never-sold SKUs
    called out separately so a zero-demand catalogue is never hidden."""
    snap = _snapshot(
        db,
        merchant_id,
        int(window_days),
        pi.DEFAULT_LOW_STOCK_THRESHOLD,
        context,
    )
    result = pi.product_performance(snap, limit=int(limit))
    result.pop("all_products", None)
    return {
        "window_days": int(window_days),
        "top_count": len(result["top_products"]),
        "never_sold_count": result["never_sold_count"],
        "never_sold": [
            {
                "product_id": r["product_id"],
                "name": r["name"],
                "category": r["category"],
                "price_inr": r["price_inr"],
                "stock_quantity": r["stock_quantity"],
                "stock_value_inr": round(
                    float(r["price_inr"]) * int(r["stock_quantity"]), 2
                ),
            }
            for r in result["bottom_products"]
            if r["never_sold"]
        ],
        "top_products": result["top_products"],
        "total_revenue_inr": result["total_revenue_inr"],
        "settled_orders": result["settled_orders"],
    }


def _get_conversion(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
    window_days: int = 90,
) -> dict[str, Any]:
    """Conversion is NOT computable on this platform — reported honestly.

    Declared as a tool so the agent can ask, get a truthful negative, and
    record a knowledge gap — rather than silently reasoning over a number
    the platform never measured.
    """
    return {
        "available": False,
        "window_days": int(window_days),
        "conversion_rate_pct": None,
        "sessions": None,
        "reason": (
            "This platform stores no sessions, visits or traffic events, so a "
            "conversion rate cannot be computed. Orders, revenue and average "
            "order value are available; conversion is not."
        ),
        "available_alternatives": [
            "analytics.get_product_performance",
            "commerce.get_orders",
            "marketing.analytics.get_orders",
        ],
    }


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
    "description": "Lookback window in days.",
}


def TOOLS() -> list[MCPToolSpec]:  # noqa: N802 - registry-facing factory
    """Declarations for the product-facing analytics MCP server."""
    return [
        MCPToolSpec(
            name="analytics.get_product_performance",
            description=(
                "Ranked performance for every catalog product: units sold, "
                "revenue, order count, trend and revenue share, including "
                "products with zero demand."
            ),
            provider="internal",
            handler=_get_product_performance,
            phase="observe",
            input_schema=_schema(
                {
                    "window_days": _WINDOW,
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
                }
            ),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="analytics.get_top_products",
            description=(
                "Highest and lowest performing products by real revenue, plus "
                "an explicit list of products that have never sold."
            ),
            provider="internal",
            handler=_get_top_products,
            phase="observe",
            input_schema=_schema(
                {
                    "window_days": _WINDOW,
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 5},
                }
            ),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="analytics.get_conversion",
            description=(
                "Always reports that conversion rate is unavailable: this "
                "platform stores no traffic or session data. Use it to record "
                "the gap honestly instead of assuming a rate."
            ),
            provider="internal",
            handler=_get_conversion,
            phase="research",
            input_schema=_schema({"window_days": _WINDOW}),
            output_schema={"type": "object"},
        ),
    ]


__all__ = ["MCP_SERVER", "TOOLS"]