"""MCP product-intelligence server — deterministic diagnosis and opportunity.

These tools are the Product Agent's analytical core. They are pure
functions of the real catalog and order rows: no model runs inside them,
no figure is estimated, and every payload carries a ``method``/``basis``
string describing the computation that produced it plus a ``status`` of
``available`` or ``insufficient_data``.

The model reasons OVER these results (in ``agents/product_agi``). It never
substitutes for them, which is what keeps "underperforming" and "bundle"
from becoming adjectives.

Domain note: the first name segment is ``product_intelligence``, so
``capability_domain`` maps every tool here into the capability domain of
the same name and ``AGENT_CAPABILITIES["product_agent"]`` grants it. No
Marketing Agent or Growth Radar domain gains access to these tools unless
it is explicitly granted this domain later.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from backend.app.integrations.mcp.schemas import MCPToolSpec
from backend.app.integrations.mcp.servers.commerce import _snapshot
from backend.app.services import product_intelligence as pi

MCP_SERVER = "product_intelligence"


def _snap(
    db: Session,
    merchant_id: uuid.UUID,
    window_days: int,
    threshold: int,
    context: Any,
) -> pi.CatalogSnapshot:
    return _snapshot(db, merchant_id, int(window_days), int(threshold), context)


def _get_catalog_health(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
    window_days: int = 90,
    low_stock_threshold: int = pi.DEFAULT_LOW_STOCK_THRESHOLD,
) -> dict[str, Any]:
    """Composite catalog-health score from measured completeness, inventory
    and demand coverage."""
    snap = _snap(db, merchant_id, window_days, low_stock_threshold, context)
    content = pi.content_gaps(snap)
    inventory = pi.low_stock_risk(snap)
    health = pi.catalog_health(snap, content=content, inventory=inventory)
    return {"window_days": int(window_days), **health, "catalog": snap.summary()}


def _get_underperforming_products(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
    window_days: int = 90,
    limit: int = 10,
) -> dict[str, Any]:
    """Products below their category AND catalog revenue benchmarks."""
    snap = _snap(
        db, merchant_id, window_days, pi.DEFAULT_LOW_STOCK_THRESHOLD, context
    )
    return pi.underperforming_products(snap, limit=int(limit))


def _get_low_stock_risk(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
    window_days: int = 90,
    low_stock_threshold: int = pi.DEFAULT_LOW_STOCK_THRESHOLD,
    projection_days: int = pi.DEFAULT_PROJECTION_DAYS,
) -> dict[str, Any]:
    """Stockout risk from the configured floor or projected demand."""
    snap = _snap(db, merchant_id, window_days, low_stock_threshold, context)
    result = pi.low_stock_risk(snap, projection_days=int(projection_days))
    return {"window_days": int(window_days), **result}


def _get_content_gaps(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
    window_days: int = 90,
) -> dict[str, Any]:
    """Missing or thin product content, measured from the real record."""
    snap = _snap(
        db, merchant_id, window_days, pi.DEFAULT_LOW_STOCK_THRESHOLD, context
    )
    return pi.content_gaps(snap)


def _get_pricing_opportunities(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
    window_days: int = 90,
) -> dict[str, Any]:
    """Internal price-position signals; competitor pricing reported absent."""
    snap = _snap(
        db, merchant_id, window_days, pi.DEFAULT_LOW_STOCK_THRESHOLD, context
    )
    return pi.pricing_opportunities(snap)


def _get_bundle_opportunities(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
    window_days: int = 90,
    limit: int = 10,
) -> dict[str, Any]:
    """Real co-purchase affinity with lift, or an honest insufficiency."""
    snap = _snap(
        db, merchant_id, window_days, pi.DEFAULT_LOW_STOCK_THRESHOLD, context
    )
    return pi.bundle_opportunities(
        db, merchant_id, snap, window_days=int(window_days), limit=int(limit)
    )


def _get_product_opportunities(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
    window_days: int = 90,
    limit: int = 25,
    low_stock_threshold: int = pi.DEFAULT_LOW_STOCK_THRESHOLD,
) -> dict[str, Any]:
    """Every deterministic opportunity in one structured payload."""
    snap = _snap(db, merchant_id, window_days, low_stock_threshold, context)
    return pi.product_opportunities(db, merchant_id, snap, limit=int(limit))


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
_THRESHOLD = {
    "type": "integer",
    "minimum": 0,
    "maximum": 10000,
    "default": pi.DEFAULT_LOW_STOCK_THRESHOLD,
    "description": "Low-stock threshold in units.",
}
_LIMIT = {"type": "integer", "minimum": 1, "maximum": 100, "default": 10}


def TOOLS() -> list[MCPToolSpec]:  # noqa: N802 - registry-facing factory
    """Declarations for the product-intelligence MCP server."""
    return [
        MCPToolSpec(
            name="product_intelligence.get_catalog_health",
            description=(
                "Catalog health score with its components, computed from real "
                "content completeness, inventory coverage and demand coverage."
            ),
            provider="internal",
            handler=_get_catalog_health,
            phase="observe",
            input_schema=_schema(
                {"window_days": _WINDOW, "low_stock_threshold": _THRESHOLD}
            ),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="product_intelligence.get_underperforming_products",
            description=(
                "Products materially below their category and catalog revenue "
                "benchmarks, including never-sold products. Reports "
                "insufficient_data when there is too little demand to compare."
            ),
            provider="internal",
            handler=_get_underperforming_products,
            phase="observe",
            input_schema=_schema({"window_days": _WINDOW, "limit": _LIMIT}),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="product_intelligence.get_low_stock_risk",
            description=(
                "Products at risk of running out, triggered by the configured "
                "stock threshold or by projected demand exceeding stock."
            ),
            provider="internal",
            handler=_get_low_stock_risk,
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
            name="product_intelligence.get_content_gaps",
            description=(
                "Products with missing or thin description, SKU or category, "
                "ranked by the revenue they are currently losing."
            ),
            provider="internal",
            handler=_get_content_gaps,
            phase="observe",
            input_schema=_schema({"window_days": _WINDOW}),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="product_intelligence.get_pricing_opportunities",
            description=(
                "Products priced far from their own category median in a way "
                "that conflicts with observed demand. Competitor pricing is "
                "reported as unavailable, never estimated."
            ),
            provider="internal",
            handler=_get_pricing_opportunities,
            phase="observe",
            input_schema=_schema({"window_days": _WINDOW}),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="product_intelligence.get_bundle_opportunities",
            description=(
                "Product pairs that genuinely appear in the same order, with "
                "support, confidence and lift. Reports insufficient_data when "
                "too few multi-product orders exist to measure affinity."
            ),
            provider="internal",
            handler=_get_bundle_opportunities,
            phase="observe",
            input_schema=_schema({"window_days": _WINDOW, "limit": _LIMIT}),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="product_intelligence.get_product_opportunities",
            description=(
                "Every deterministic product opportunity in one payload: "
                "stock risk, underperformance, content gaps, pricing and "
                "bundles, each with the computation that produced it."
            ),
            provider="internal",
            handler=_get_product_opportunities,
            phase="observe",
            input_schema=_schema(
                {
                    "window_days": _WINDOW,
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
                    "low_stock_threshold": _THRESHOLD,
                }
            ),
            output_schema={"type": "object"},
        ),
    ]


__all__ = ["MCP_SERVER", "TOOLS"]