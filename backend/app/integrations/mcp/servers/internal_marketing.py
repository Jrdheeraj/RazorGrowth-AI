"""MCP internal server — CRM, analytics, product and marketing-history reads.

Every tool delegates to the EXISTING MarketingAGI tool implementation through
its own registry (``servers.base.legacy_call``), so there is exactly ONE
implementation of each query and the existing per-tool allowlist,
tenant-filtered SQL and defaults all keep applying. MCP standardizes the
contract above them (stable name, JSON schema, guardrail policy, per-run
cache, retries, normalization, observability) and never re-implements the
SQL.

All tools here are READ-ONLY and tenant-scoped: the merchant id comes from
the execution context, and each underlying query already filters by it.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from backend.app.integrations.mcp.schemas import MCPToolSpec
from backend.app.integrations.mcp.servers.base import legacy_call

MCP_SERVER = "internal"


# ── handlers (thin adapters over the existing tool registry) ────────────
#
# Every handler takes ``db``/``merchant_id`` plus the client-injected
# ``context``/``approved_action_id`` plumbing and its declared arguments as
# keywords. Merchant identity is ALWAYS the injected context value, so a
# handler cannot be pointed at another tenant.


def _delegate(legacy_tool: str) -> Any:
    """Build a handler that runs one existing MarketingAGI tool via MCP."""

    def _handler(
        db: Session,
        merchant_id: uuid.UUID,
        *,
        context: Any = None,
        approved_action_id: Any = None,
        **arguments: Any,
    ) -> dict[str, Any]:
        ctx = context if context is not None else _fallback_ctx(db, merchant_id)
        return legacy_call(ctx, legacy_tool, arguments)

    _handler.__name__ = f"mcp_{legacy_tool}"
    _handler.__doc__ = f"MCP adapter for the existing '{legacy_tool}' tool."
    return _handler


def _fallback_ctx(db: Session, merchant_id: uuid.UUID) -> Any:
    """Context for a direct handler call that bypassed the client.

    The MCP client always injects a real context; this exists only so the
    handlers remain callable from tests/server-side code with the same
    tenant binding.
    """
    from backend.app.integrations.mcp.context import MCPExecutionContext

    return MCPExecutionContext(db=db, merchant_id=merchant_id)


def _orders(
    db: Session,
    merchant_id: uuid.UUID,
    *,
    context: Any = None,
    approved_action_id: Any = None,
    window_days: int = 30,
) -> dict[str, Any]:
    """Order volume / AOV view.

    Derived from the EXISTING revenue-trend tool (one implementation, one
    query): it already returns current-vs-previous order counts and revenue
    from captured payments, so the order view is that payload projected
    into an order-shaped result. No second query is introduced.
    """
    ctx = context if context is not None else _fallback_ctx(db, merchant_id)
    trend = legacy_call(ctx, "get_revenue_trend", {"window_days": window_days})
    current = trend.get("current") or {}
    orders = current.get("orders") or 0
    revenue = current.get("revenue_inr") or 0
    return {
        "window_days": window_days,
        "current": current,
        "previous": trend.get("previous") or {},
        "order_change_pct": trend.get("order_change_pct"),
        "revenue_change_pct": trend.get("revenue_change_pct"),
        "average_order_value_inr": round(float(revenue) / int(orders), 2)
        if orders
        else None,
        "trend": trend.get("trend"),
        "source": "captured_payments",
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
    "default": 30,
    "description": "Lookback window in days.",
}
_LIMIT_50 = {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}
_LIMIT_10 = {"type": "integer", "minimum": 1, "maximum": 100, "default": 10}
_LIMIT_30 = {"type": "integer", "minimum": 1, "maximum": 200, "default": 30}


def TOOLS() -> list[MCPToolSpec]:  # noqa: N802 - registry-facing factory
    """Declarations for the internal (platform-database) MCP server."""
    return [
        # ── CRM ────────────────────────────────────────────────────────
        MCPToolSpec(
            name="marketing.crm.search_customers",
            description=(
                "Search this workspace's customers by behaviour (min orders, "
                "min spend, inactive days, stored segment). Tenant-scoped."
            ),
            provider="internal",
            handler=_delegate("find_customers"),
            phase="research",
            input_schema=_schema(
                {
                    "min_orders": {"type": "integer", "minimum": 0, "maximum": 100, "default": 0},
                    "min_spend_inr": {"type": "number", "minimum": 0, "default": 0},
                    "inactive_days": {"type": "integer", "minimum": 1, "maximum": 3650},
                    "segment": {"type": "string", "maxLength": 40},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 200},
                }
            ),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="marketing.crm.get_customer",
            description="Real profile facts for one customer of this workspace.",
            provider="internal",
            handler=_delegate("get_customer_profile"),
            phase="research",
            input_schema=_schema(
                {"customer_id": {"type": "string", "minLength": 1, "maxLength": 64}},
                required=["customer_id"],
            ),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="marketing.crm.get_segment",
            description="Aggregate customers by stored segment with counts and spend.",
            provider="internal",
            handler=_delegate("get_customer_segments"),
            phase="observe",
            input_schema=_schema({}),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="marketing.crm.get_campaign_history",
            description="Previous campaigns with status and measured revenue.",
            provider="internal",
            handler=_delegate("get_campaign_history"),
            phase="research",
            input_schema=_schema({"limit": _LIMIT_30}),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="marketing.crm.get_action_history",
            description=(
                "Previously proposed / approved / rejected agent actions so the "
                "agent learns what this merchant accepts."
            ),
            provider="internal",
            handler=_delegate("get_action_history"),
            phase="research",
            input_schema=_schema({"limit": _LIMIT_30}),
            output_schema={"type": "object"},
        ),
        # ── Analytics ───────────────────────────────────────────────────
        MCPToolSpec(
            name="marketing.analytics.get_revenue",
            description=(
                "Revenue, orders and AOV for this workspace over a window, "
                "from real captured payments."
            ),
            provider="internal",
            handler=_delegate("get_business_overview"),
            phase="observe",
            input_schema=_schema(
                {"window_days": {"type": "integer", "minimum": 1, "maximum": 365, "default": 90}}
            ),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="marketing.analytics.get_revenue_trend",
            description="Current vs previous window revenue to detect growth or decline.",
            provider="internal",
            handler=_delegate("get_revenue_trend"),
            phase="research",
            input_schema=_schema({"window_days": _WINDOW}),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="marketing.analytics.get_orders",
            description="Order volume, change percentage and average order value.",
            provider="internal",
            handler=_orders,
            phase="observe",
            input_schema=_schema({"window_days": _WINDOW}),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="marketing.analytics.get_failed_payments",
            description=(
                "Failed payments with amounts, failure codes and recoverable "
                "value for this workspace."
            ),
            provider="internal",
            handler=_delegate("get_failed_payment_analytics"),
            phase="observe",
            input_schema=_schema({"limit": _LIMIT_50}),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="marketing.analytics.get_customer_retention",
            description=(
                "Active vs inactive purchasing customers and the value that has "
                "gone quiet."
            ),
            provider="internal",
            handler=_delegate("get_customer_activity_trend"),
            phase="observe",
            input_schema=_schema({"window_days": _WINDOW}),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="marketing.analytics.get_product_affinities",
            description="Products genuinely bought together in the same order.",
            provider="internal",
            handler=_delegate("get_product_affinities"),
            phase="research",
            input_schema=_schema({"limit": _LIMIT_10}),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="marketing.analytics.get_product_performance",
            description="Best and worst selling products by real order-item data.",
            provider="internal",
            handler=_delegate("get_product_performance"),
            phase="research",
            input_schema=_schema({"limit": _LIMIT_10}),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="marketing.analytics.get_product_catalog",
            description="This workspace's active product catalog with price and stock.",
            provider="internal",
            handler=_delegate("get_product_catalog"),
            phase="research",
            input_schema=_schema(
                {"limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50}}
            ),
            output_schema={"type": "object"},
        ),
        # ── Knowledge / memory (RAG evidence sources over MCP) ───────────
        MCPToolSpec(
            name="marketing.knowledge.recall_memory",
            description=(
                "Recall prior growth memories relevant to a question — what was "
                "tried, what worked, what the merchant prefers."
            ),
            provider="internal",
            handler=_delegate("recall_memory"),
            phase="research",
            input_schema=_schema(
                {
                    "query": {"type": "string", "minLength": 2, "maxLength": 300},
                    "k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                },
                required=["query"],
            ),
            output_schema={"type": "object"},
        ),
        MCPToolSpec(
            name="marketing.knowledge.search_knowledge_store",
            description=(
                "Semantic search over this workspace's ingested knowledge "
                "(products, customers, orders, payments)."
            ),
            provider="internal",
            handler=_delegate("search_knowledge_store"),
            phase="research",
            input_schema=_schema(
                {
                    "query": {"type": "string", "minLength": 2, "maxLength": 300},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 8},
                },
                required=["query"],
            ),
            output_schema={"type": "object"},
        ),
    ]


#: Legacy MarketingAGI tool name -> MCP tool name. Keeps the existing
#: registry and the MCP catalog reconciled while the agent migrates.
ALIASES: dict[str, str] = {
    "find_customers": "marketing.crm.search_customers",
    "get_customer_profile": "marketing.crm.get_customer",
    "get_customer_segments": "marketing.crm.get_segment",
    "get_campaign_history": "marketing.crm.get_campaign_history",
    "get_action_history": "marketing.crm.get_action_history",
    "get_business_overview": "marketing.analytics.get_revenue",
    "get_revenue_trend": "marketing.analytics.get_revenue_trend",
    "get_failed_payment_analytics": "marketing.analytics.get_failed_payments",
    "get_customer_activity_trend": "marketing.analytics.get_customer_retention",
    "get_product_affinities": "marketing.analytics.get_product_affinities",
    "get_product_performance": "marketing.analytics.get_product_performance",
    "get_product_catalog": "marketing.analytics.get_product_catalog",
    "recall_memory": "marketing.knowledge.recall_memory",
    "search_knowledge_store": "marketing.knowledge.search_knowledge_store",
}


__all__ = ["ALIASES", "MCP_SERVER", "TOOLS"]