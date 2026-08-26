"""
Explainability + Do-Nothing Baseline — Phase 5 Features 16 & 17.

Every recommendation can answer:
  WHY · WHAT EVIDENCE · EXPECTED IMPACT · RISK · ASSUMPTIONS ·
  DO NOTHING vs TAKE ACTION.

Rules enforced here:
  - every number originates in a database row, a persisted simulation,
    or a PROJECTION that is explicitly labelled `is_projection`,
  - "do nothing" projects the measured trend forward (no invention),
  - "take action" figures come from the deterministic simulation engine
    and are labelled estimates,
  - the LLM is not involved anywhere in this module.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.experiment import Simulation
from backend.app.models.opportunity import GrowthOpportunity
from backend.app.services.radar import GrowthRadarService
from backend.app.services.scoring import OpportunityScoringEngine

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _extract_reasoning(reasoning: list[Any] | None) -> tuple[list[dict], list[dict], list[str]]:
    """Split stored reasoning into evidence entries, scoring blocks, and notes."""
    evidence: list[dict] = []
    scorings: list[dict] = []
    notes: list[str] = []
    for item in reasoning or []:
        if isinstance(item, dict):
            if "scoring" in item:
                scorings.append(item["scoring"])
            else:
                evidence.append(item)
        elif isinstance(item, str):
            notes.append(item)
    return evidence, scorings, notes


class ExplainabilityService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Feature 17: DO NOTHING baseline ──────────────────────────────────

    def do_nothing_baseline(
        self,
        merchant_id: uuid.UUID,
        opportunity: GrowthOpportunity,
        *,
        window_days: int = 30,
    ) -> dict[str, Any]:
        """
        Project what happens if no action is taken, from the measured
        trend behind the opportunity's strongest evidence entry.
        """
        evidence_items, _, _ = _extract_reasoning(opportunity.reasoning)

        projection: Decimal | None = None
        basis = "insufficient trend data — no projection attempted"
        change_pct: float | None = None

        for item in evidence_items:
            signal_type = str(item.get("source_signal", ""))
            if signal_type == "revenue_drop":
                radar = GrowthRadarService(self.db)
                now = _utcnow()
                cur_rev, _ = radar.revenue_for_window(
                    merchant_id, now - timedelta(days=window_days), now
                )
                prev_rev, _ = radar.revenue_for_window(
                    merchant_id,
                    now - timedelta(days=2 * window_days),
                    now - timedelta(days=window_days),
                )
                if prev_rev > 0:
                    change = (cur_rev - prev_rev) / prev_rev  # e.g. -0.18
                    projection = (cur_rev * (Decimal("1") + change)).quantize(
                        Decimal("0.01")
                    )
                    change_pct = float(round(change * 100, 2))
                    basis = (
                        f"continuation of measured {change_pct:+.2f}% "
                        f"{window_days}-day revenue trend"
                    )
                break

        return {
            "scenario": "do_nothing",
            "projected_next_window_revenue": float(projection)
            if projection is not None
            else None,
            "basis": basis,
            "is_projection": projection is not None,
            "measured_change_percentage": change_pct,
            "expected_cost": 0.0,
            "risk": (
                "continued decline if the measured trend persists"
                if projection is not None and change_pct is not None and change_pct < 0
                else "unknown without trend data"
            ),
        }

    def take_action_outlook(
        self,
        merchant_id: uuid.UUID,
        opportunity: GrowthOpportunity,
    ) -> dict[str, Any]:
        """Expected outcome WITH action — from the latest persisted simulation."""
        sim = self.db.scalars(
            select(Simulation)
            .where(
                Simulation.merchant_id == merchant_id,
                Simulation.opportunity_id == opportunity.id,
            )
            .order_by(Simulation.created_at.desc())
            .limit(1)
        ).first()
        if sim is None:
            return {
                "scenario": "take_action",
                "estimated_revenue": float(opportunity.expected_revenue),
                "is_estimate": True,
                "basis": "opportunity expected_revenue (no simulation run yet)",
                "confidence_range": None,
            }
        return {
            "scenario": "take_action",
            "estimated_revenue": float(sim.estimated_revenue),
            "estimated_cost": float(sim.estimated_cost),
            "estimated_profit": float(sim.estimated_profit),
            "is_estimate": True,
            "basis": f"persisted '{sim.scenario_type}' simulation with explicit assumptions",
            "confidence_range": [
                float(sim.confidence_low) if sim.confidence_low is not None else None,
                float(sim.confidence_high) if sim.confidence_high is not None else None,
            ],
        }

    # ── Feature 16: full explanation ─────────────────────────────────────

    def explain_opportunity(
        self,
        merchant_id: uuid.UUID,
        opportunity: GrowthOpportunity,
        *,
        window_days: int = 30,
    ) -> dict[str, Any]:
        engine = OpportunityScoringEngine()
        breakdown = engine.score(
            expected_revenue=float(opportunity.expected_revenue),
            confidence=float(opportunity.confidence),
            target_customer_count=int(opportunity.target_customer_count or 0),
            evidence_items=max(1, len(opportunity.reasoning or [])),
        )

        evidence_items, stored_scorings, notes = _extract_reasoning(
            opportunity.reasoning
        )
        assumptions = [
            f"{item.get('assumed_response_rate', item.get('assumed_recovery_rate'))}"
            for item in evidence_items
            if isinstance(item, dict)
            and (
                item.get("assumed_response_rate") is not None
                or item.get("assumed_recovery_rate") is not None
            )
        ]

        return {
            "opportunity_id": str(opportunity.id),
            "title": opportunity.title,
            "status": str(getattr(opportunity.status, "value", opportunity.status)),
            "why": self._build_why(opportunity, evidence_items),
            "evidence": evidence_items if evidence_items else [
                {"note": "structured evidence attached to this opportunity"}
            ],
            "expected_impact": self.take_action_outlook(merchant_id, opportunity),
            "risk": {
                "risk_score_input": breakdown.risk_score,
                "narrative": (
                    "Money-touching proposals additionally face the Phase 4 "
                    "guardrail chain and mandatory human approval."
                ),
            },
            "assumptions": assumptions,
            "score_breakdown": breakdown.to_dict(),
            "do_nothing": self.do_nothing_baseline(
                merchant_id, opportunity, window_days=window_days
            ),
            "take_action": self.take_action_outlook(merchant_id, opportunity),
            "notes": notes,
        }

    @staticmethod
    def _build_why(
        opportunity: GrowthOpportunity, evidence_items: list[dict]
    ) -> str:
        parts: list[str] = [f"'{opportunity.title}' was raised because"]
        reasons = [
            str(item.get("basis"))
            for item in evidence_items
            if isinstance(item, dict) and item.get("basis")
        ]
        if reasons:
            parts.append(", ".join(dict.fromkeys(reasons)) + ".")
        else:
            parts.append("of the detected growth signals it was created from.")
        parts.append(
            f"It currently carries confidence {float(opportunity.confidence):.2f} "
            f"and estimated impact ₹{float(opportunity.expected_revenue):,.0f}."
        )
        return " ".join(parts)
