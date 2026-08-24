"""
Deterministic growth intelligence engine.

This is the rule-based baseline layer. It analyses the synthetic commerce
dataset and produces structured growth opportunities. No LLM is involved at
this stage — all logic is explicit and reproducible.
"""
from __future__ import annotations

from typing import Any

from backend.app.data.synthetic import CUSTOMERS, ORDERS, PRODUCTS


def generate_opportunities() -> list[dict[str, Any]]:
    """Return a deterministic list of growth opportunity objects."""
    opportunities: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ #
    # Opportunity 1 — cross-sell protective case to headphone buyers
    # ------------------------------------------------------------------ #
    headphone_buyer_ids: set[str] = {
        o["customer_id"] for o in ORDERS if o["product_id"] == "prod_headphones"
    }
    case_buyer_ids: set[str] = {
        o["customer_id"] for o in ORDERS if o["product_id"] == "prod_case"
    }
    eligible_count = len(headphone_buyer_ids - case_buyer_ids)

    case_price: int = next(
        p["price"] for p in PRODUCTS if p["id"] == "prod_case"
    )
    estimated_conversion = 0.12
    expected_revenue = round(eligible_count * estimated_conversion * case_price, 2)

    opportunities.append(
        {
            "id": "opp_headphone_case",
            "type": "cross_sell",
            "title": "Cross-sell protective case to headphone buyers",
            "target_product": "prod_case",
            "target_customers": eligible_count,
            "confidence": 0.87,
            "expected_revenue": expected_revenue,
            "reasoning": [
                "Headphone buyers are a high-intent segment.",
                "Accessory attachment is currently below the modelled target.",
                "The proposed action has a bounded price and requires merchant approval.",
            ],
            "status": "pending_approval",
        }
    )

    return opportunities
