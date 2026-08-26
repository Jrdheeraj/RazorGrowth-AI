"""
Growth Brief — Phase 5 Feature 19.

A daily decision brief built ONLY from real database aggregates:
  - revenue this window vs previous window (captured payments),
  - top opportunity (deterministic score),
  - top risk (churn / payment-failure intelligence),
  - recommended action + expected impact range (labelled estimate).

Empty data produces explicit "no data yet" fields — never fabricated
numbers, and never an emoji-laden fiction.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.customer_insight import CustomerInsight
from backend.app.models.opportunity import GrowthOpportunity
from backend.app.models.payment import Payment
from backend.app.services.radar import GrowthRadarService
from backend.app.services.scoring import OpportunityScoringEngine

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GrowthBriefService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self._radar = GrowthRadarService(db)

    def build(
        self, merchant_id: uuid.UUID, *, window_days: int = 30
    ) -> dict[str, Any]:
        now = _utcnow()
        cur_rev, cur_count = self._radar.revenue_for_window(
            merchant_id, now - timedelta(days=window_days), now
        )
        prev_rev, prev_count = self._radar.revenue_for_window(
            merchant_id,
            now - timedelta(days=2 * window_days),
            now - timedelta(days=window_days),
        )

        change_pct: float | None = None
        if prev_rev > 0:
            change_pct = float(
                ((cur_rev - prev_rev) / prev_rev * Decimal("100")).quantize(
                    Decimal("0.01")
                )
            )
        elif cur_rev > 0:
            change_pct = None  # no prior baseline — refuse to invent one

        brief: dict[str, Any] = {
            "merchant_id": str(merchant_id),
            "window_days": window_days,
            "generated_at": now.isoformat(),
            "revenue": {
                "current_period": float(cur_rev),
                "previous_period": float(prev_rev),
                "change_percentage": change_pct,
                "has_prior_baseline": prev_rev > 0 or prev_count > 0,
                "basis": f"captured payments on paid orders, last {window_days} days",
            },
        }

        # ── top opportunity ──────────────────────────────────────────────
        opportunities = list(
            self.db.scalars(
                select(GrowthOpportunity)
                .where(
                    GrowthOpportunity.merchant_id == merchant_id,
                    GrowthOpportunity.status.in_(["pending_approval", "approved"]),
                )
                .limit(50)
            ).all()
        )
        engine = OpportunityScoringEngine()
        best: tuple[float, GrowthOpportunity] | None = None
        for opp in opportunities:
            bd = engine.score(
                expected_revenue=float(opp.expected_revenue),
                confidence=float(opp.confidence),
                target_customer_count=int(opp.target_customer_count or 0),
                evidence_items=max(1, len(opp.reasoning or [])),
            )
            if best is None or bd.opportunity_score > best[0]:
                best = (bd.opportunity_score, opp)
        if best is None:
            brief["top_opportunity"] = None
            brief["recommended_action"] = {
                "title": "No open opportunities — run the growth agents",
                "expected_impact_estimate": None,
                "is_estimate": False,
            }
        else:
            _, opp = best
            low = float(opp.expected_revenue) * 0.8
            high = float(opp.expected_revenue) * 1.2
            brief["top_opportunity"] = {
                "id": str(opp.id),
                "title": opp.title,
                "type": str(getattr(opp.type, "value", opp.type)),
                "confidence": float(opp.confidence),
                "expected_revenue_estimate": {
                    "point": float(opp.expected_revenue),
                    "range_low": round(low, 2),
                    "range_high": round(high, 2),
                    "is_estimate": True,
                    "method": "±20% band around opportunity expected_revenue",
                },
            }
            brief["recommended_action"] = {
                "title": f"Review and approve: {opp.title}",
                "expected_impact_estimate": {
                    "range_low": round(low, 2),
                    "range_high": round(high, 2),
                    "is_estimate": True,
                },
                "confidence": float(opp.confidence),
                "requires_human_approval": True,
            }

        # ── top risk ─────────────────────────────────────────────────────
        worst = self.db.scalars(
            select(CustomerInsight)
            .where(CustomerInsight.merchant_id == merchant_id)
            .order_by(CustomerInsight.churn_risk_score.desc())
            .limit(1)
        ).first()

        failed_stmt = (
            select(func.count(Payment.id), func.coalesce(func.sum(Payment.amount), 0))
            .where(Payment.merchant_id == merchant_id)
            .where(Payment.status == "failed")
        )
        fail_count, fail_value = self.db.execute(failed_stmt).one()

        risks: list[dict[str, Any]] = []
        if worst is not None and int(worst.churn_risk_score) >= 55:
            risks.append(
                {
                    "type": "customer_churn",
                    "detail": (
                        f"{int(worst.churn_risk_score)} churn-risk score "
                        f"({worst.churn_risk_level}) for a customer with "
                        f"{worst.order_count} lifetime orders"
                    ),
                }
            )
        if int(fail_count) > 0:
            risks.append(
                {
                    "type": "payment_failures",
                    "detail": (
                        f"{int(fail_count)} failed payments worth "
                        f"₹{Decimal(str(fail_value))} awaiting recovery"
                    ),
                }
            )
        brief["top_risk"] = risks[0] if risks else None
        brief["risks"] = risks
        return brief
