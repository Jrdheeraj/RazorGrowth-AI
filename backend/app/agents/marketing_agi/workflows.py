"""MarketingAGI workflows — dynamically selected marketing interventions.

Each workflow declares:
  - the signals that justify invoking it
  - the investigation steps it wants (tool calls) — a PREFERENCE, not a
    fixed script: the reasoning loop still selects tools dynamically
  - how it builds its audience
  - how its campaign is shaped

The loop picks AT MOST the workflows justified by evidence — never all
workflows for every merchant.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import Session


@dataclass
class WorkflowSpec:
    key: str
    name: str
    description: str
    channel: str = "email"
    # Evidence predicates over analytics results. All take the analytics
    # dict and return True when this workflow is worth investigating.
    relevant_when: Callable[[dict[str, Any]], bool] = lambda a: False
    # Preferred tool sequence for the research phase (guidance only).
    investigation_tools: list[str] = field(default_factory=list)
    # Audience criteria builder from analytics.
    audience_criteria: Callable[[dict[str, Any]], dict[str, Any]] = lambda a: {}


# ---------------------------------------------------------------------------
# Signal predicates
# ---------------------------------------------------------------------------


def _overview(a: dict[str, Any]) -> dict[str, Any]:
    return a.get("get_business_overview", {}) or {}


def _activity(a: dict[str, Any]) -> dict[str, Any]:
    return a.get("get_customer_activity_trend", {}) or {}


def _failed(a: dict[str, Any]) -> dict[str, Any]:
    return a.get("get_failed_payment_analytics", {}) or {}


def _affinities(a: dict[str, Any]) -> dict[str, Any]:
    return a.get("get_product_affinities", {}) or {}


def _segments(a: dict[str, Any]) -> dict[str, Any]:
    return a.get("get_customer_segments", {}) or {}


# ---------------------------------------------------------------------------
# Workflow catalog
# ---------------------------------------------------------------------------


WIN_BACK = WorkflowSpec(
    key="customer_win_back",
    name="Customer Win-Back",
    description="Reactivate inactive customers with real purchase history.",
    relevant_when=lambda a: _activity(a).get("inactive_with_purchase_history", 0) >= 3,
    investigation_tools=[
        "get_customer_activity_trend",
        "find_customers",
        "get_campaign_history",
        "recall_memory",
    ],
    audience_criteria=lambda a: {
        "min_orders": 1,
        "inactive_days": a.get("_inactive_days", 30),
    },
)

RETENTION = WorkflowSpec(
    key="customer_retention",
    name="Customer Retention",
    description="Protect repeat-purchase behaviour before it decays.",
    relevant_when=lambda a: (
        _overview(a).get("repeat_purchase_rate", 0) > 0
        and _activity(a).get("inactivity_signal") == "meaningful"
    ),
    investigation_tools=["get_customer_activity_trend", "find_customers", "recall_memory"],
    audience_criteria=lambda a: {"min_orders": 2, "inactive_days": 45},
)

FAILED_PAYMENT_RECOVERY = WorkflowSpec(
    key="failed_payment_recovery",
    name="Failed Payment Recovery",
    description="Recover value stuck in genuinely failed payments.",
    relevant_when=lambda a: _failed(a).get("failed_payment_count", 0) >= 1,
    investigation_tools=["get_failed_payment_analytics", "find_customers", "recall_memory"],
    audience_criteria=lambda a: {"min_orders": 0},
)

VIP_LOYALTY = WorkflowSpec(
    key="vip_loyalty",
    name="VIP / Loyalty",
    description="Recognise and grow the highest-value customer relationships.",
    relevant_when=lambda a: any(
        s.get("segment") == "vip" and s.get("customers", 0) >= 2
        for s in _segments(a).get("segments", [])
    ),
    investigation_tools=["get_customer_segments", "find_customers", "get_product_performance"],
    audience_criteria=lambda a: {"segment": "vip"},
)

CROSS_SELL = WorkflowSpec(
    key="cross_sell",
    name="Cross-Sell",
    description="Offer genuinely co-purchased products to customers of their counterparts.",
    relevant_when=lambda a: _affinities(a).get("multi_item_order_count", 0) >= 2,
    investigation_tools=["get_product_affinities", "get_product_performance", "find_customers"],
    audience_criteria=lambda a: {"min_orders": 1},
)

EMAIL_CAMPAIGN = WorkflowSpec(
    key="email_campaign",
    name="Email Campaign",
    description="A general email campaign when a specific audience justifies contact.",
    relevant_when=lambda a: _overview(a).get("total_customers", 0) >= 5
    and not _failed(a).get("failed_payment_count"),
    investigation_tools=["get_business_overview", "get_email_campaigns", "find_customers"],
    audience_criteria=lambda a: {"min_orders": 1},
)


WORKFLOWS: list[WorkflowSpec] = [WIN_BACK, RETENTION, FAILED_PAYMENT_RECOVERY, VIP_LOYALTY, CROSS_SELL, EMAIL_CAMPAIGN]


def select_workflows(analytics: dict[str, Any]) -> list[WorkflowSpec]:
    """Evidence-based workflow selection (bounded, priority ordered)."""
    selected: list[WorkflowSpec] = []
    for wf in WORKFLOWS:
        try:
            if wf.relevant_when(analytics):
                selected.append(wf)
        except Exception:
            continue
    return selected


def workflow_catalog() -> list[dict[str, Any]]:
    return [
        {
            "key": w.key,
            "name": w.name,
            "description": w.description,
            "channel": w.channel,
        }
        for w in WORKFLOWS
    ]
