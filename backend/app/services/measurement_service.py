"""
Measurement service — Phase 4 campaign revenue measurement.

Responsibilities:
  - Compare estimated_revenue vs actual_revenue for completed campaigns
  - Calculate absolute variance and percentage variance
  - Persist actual_revenue for completed campaigns (idempotent)
  - Return clearly marked "measurement_pending" state when real data is
    unavailable — revenue is NEVER fabricated
  - Derive actual revenue ONLY from real DB commerce/payment data

All revenue is in INR (Indian Rupees) per the merchant's currency setting.
"""

from __future__ import annotations

import enum
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.models.campaign import Campaign
from backend.app.models.enums import CampaignStatus
from backend.app.models.payment import Payment
from backend.app.models.order import Order

log = logging.getLogger(__name__)


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------


def _safe_decimal(value: Any) -> Decimal | None:
    """Convert a value to Decimal safely; return None on failure."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _to_float(value: Decimal | None) -> float | None:
    """Decimal → float, preserving exact zeros (0 stays 0.0, not None)."""
    if value is None:
        return None
    return float(value)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pending_result(
    estimated: Decimal | None,
    status: str,
) -> dict[str, Any]:
    return {
        "estimated_revenue": _to_float(estimated),
        "actual_revenue": None,
        "variance": None,
        "variance_percentage": None,
        "status": status,
        "measurement_date": _utcnow_iso(),
    }


# -------------------------------------------------------------------------
# Core measurement logic
# -------------------------------------------------------------------------


def measure_campaign_revenue(db: Session, campaign_id: uuid.UUID) -> dict[str, Any]:
    """
    Measure revenue for a completed campaign.

    Workflow:
      1. Retrieve the campaign (unknown id → campaign_not_found)
      2. Not completed yet → measurement_pending
      3. actual_revenue = sum of captured payments linked to paid orders for
         this merchant — derived strictly from real DB commerce data.
         If no real revenue exists and MEASUREMENT_REQUIRE_REAL_DATA is true
         (the default), report measurement_pending instead of inventing a 0.
      4. Compute variance = actual − estimated and
         variance_percentage = variance / estimated × 100
         (None when estimated revenue is zero or missing — division-safe).
      5. Persist actual_revenue on the campaign. Repeated measurement of the
         same underlying data yields the same persisted value (idempotent).

    Returns:
        dict with keys: estimated_revenue, actual_revenue, variance,
        variance_percentage, status, measurement_date
    """
    try:
        campaign = db.get(Campaign, campaign_id)
        if not campaign:
            return _pending_result(None, "campaign_not_found")

        # If campaign is not in a terminal measured state → pending
        if campaign.status != CampaignStatus.completed:
            return _pending_result(
                _safe_decimal(campaign.estimated_revenue), "measurement_pending"
            )

        # ─── Actual revenue from REAL commerce data ──────────────────────
        stmt = (
            select(Payment)
            .join(Order, Payment.order_id == Order.id)
            .where(Payment.merchant_id == campaign.merchant_id)
            .where(Payment.status == "captured")
            .where(Order.status == "paid")
        )
        result = db.execute(stmt)
        actual_revenue = Decimal("0")
        actual_found = False
        for p in result.scalars().all():
            amt = _safe_decimal(p.amount)
            if amt is not None:
                actual_revenue += amt
                actual_found = True

        estimated = _safe_decimal(campaign.estimated_revenue)

        # Never fabricate revenue: with real-data enforcement on, a completed
        # campaign without any captured payment data stays "pending".
        if not actual_found and get_settings().MEASUREMENT_REQUIRE_REAL_DATA:
            return _pending_result(estimated, "measurement_pending")

        # ─── Persist (idempotent — same input data ⇒ same stored value) ──
        campaign.actual_revenue = actual_revenue if actual_found else Decimal("0")
        db.flush()

        # ─── Variance (mathematically correct, zero/None-safe) ───────────
        if estimated is None:
            variance = None
            variance_percentage = None
        else:
            variance = actual_revenue - estimated
            # Percentage undefined when estimated revenue is zero → None
            variance_percentage = (
                (variance / estimated * Decimal("100")) if estimated != 0 else None
            )

        return {
            "estimated_revenue": _to_float(estimated),
            "actual_revenue": _to_float(actual_revenue),
            "variance": _to_float(variance),
            "variance_percentage": _to_float(variance_percentage),
            "status": "completed",
            "measurement_date": _utcnow_iso(),
        }

    except Exception as exc:
        log.error("Measurement failed for campaign %s: %s", campaign_id, exc, exc_info=True)
        return _pending_result(None, "measurement_error")
