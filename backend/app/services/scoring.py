"""
OpportunityScoringEngine — Phase 5 Feature 2.

DETERMINISTIC scoring. The LLM may supply reasoning and estimates as
inputs, but it NEVER computes the final score — this module does, with a
fully transparent, reproducible formula:

    opportunity_score =
        revenue_potential
        * confidence_score
        * urgency_score
        * evidence_strength
        / implementation_cost_adjustment

Every factor is normalised to [0, 1] first; the product is scaled to a
predictable 0–100 range. All factors are returned alongside the score so
the UI can answer "Why did the AI rank this opportunity #1?".

risk_score is calculated and REPORTED but deliberately NOT folded into
the headline number — risk handling belongs to the guardrail chain, not
to a hidden multiplier. This keeps the score explainable and honest.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from decimal import Decimal, InvalidOperation
from typing import Any

# ── Normalisation ceilings (documented, tunable, deterministic) ─────────────
REVENUE_NORMALIZER_INR = Decimal("500000")     # ₹5L expected revenue ⇒ factor 1.0
CUSTOMER_IMPACT_NORMALIZER = Decimal("500")    # 500 target customers ⇒ factor 1.0
EVIDENCE_STRENGTH_ITEMS = 5                    # 5+ distinct evidence items ⇒ 1.0
MIN_EVIDENCE_STRENGTH = Decimal("0.20")        # never zero — absence ≠ impossibility
DEFAULT_URGENCY = Decimal("0.50")              # unknown urgency ⇒ neutral 0.5
SCORE_SCALE = Decimal("100")                   # final range 0–100


@dataclass
class ScoreBreakdown:
    """All factors behind one opportunity score (persisted for explainability)."""

    revenue_potential: float
    confidence_score: float
    urgency_score: float
    customer_impact: float
    implementation_cost: float
    implementation_cost_adjustment: float
    risk_score: float
    evidence_strength: float
    expected_roi: float | None
    opportunity_score: float
    formula: str = (
        "opportunity_score = 100 * revenue_potential * confidence_score "
        "* urgency_score * evidence_strength / implementation_cost_adjustment"
    )
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _dec(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _clamp01(value: Decimal) -> Decimal:
    if value < 0:
        return Decimal("0")
    if value > 1:
        return Decimal("1")
    return value


class OpportunityScoringEngine:
    """
    Deterministic scorer. `score()` is pure: same inputs ⇒ same output,
    no LLM involvement, no randomness.
    """

    def score(
        self,
        *,
        expected_revenue: Any,
        confidence: Any,
        target_customer_count: int = 0,
        evidence_items: int = 0,
        urgency_score: Any | None = None,
        implementation_cost: Any = 0.2,
        estimated_cost: Any | None = None,
        risk_score: Any = 0.0,
    ) -> ScoreBreakdown:
        revenue_potential = _clamp01(
            _dec(expected_revenue) / REVENUE_NORMALIZER_INR
            if _dec(expected_revenue) <= REVENUE_NORMALIZER_INR
            else Decimal("1")
        )
        confidence_score = _clamp01(_dec(confidence))
        urgency = (
            _clamp01(_dec(urgency_score, DEFAULT_URGENCY))
            if urgency_score is not None
            else DEFAULT_URGENCY
        )
        customer_impact = _clamp01(
            _dec(target_customer_count) / CUSTOMER_IMPACT_NORMALIZER
            if _dec(target_customer_count) <= CUSTOMER_IMPACT_NORMALIZER
            else Decimal("1")
        )

        cost = _dec(implementation_cost)
        if cost < 0:
            cost = Decimal("0")
        # adjustment ≥ 1 so division can only dampen, never inflate
        cost_adjustment = Decimal("1") + cost

        raw_evidence_strength = _dec(evidence_items) / Decimal(EVIDENCE_STRENGTH_ITEMS)
        evidence_strength = max(
            _clamp01(raw_evidence_strength), MIN_EVIDENCE_STRENGTH
        )

        expected_roi: Decimal | None = None
        est_cost_dec = _dec(estimated_cost) if estimated_cost is not None else None
        if est_cost_dec is not None and est_cost_dec > 0:
            expected_roi = (_dec(expected_revenue) / est_cost_dec).quantize(Decimal("0.01"))

        opportunity_score = (
            SCORE_SCALE
            * revenue_potential
            * confidence_score
            * urgency
            * evidence_strength
            / cost_adjustment
        ).quantize(Decimal("0.01"))

        notes: list[str] = []
        if _dec(expected_revenue) > REVENUE_NORMALIZER_INR:
            notes.append(
                f"revenue_potential capped at 1.0 (expected_revenue exceeds "
                f"normaliser ₹{REVENUE_NORMALIZER_INR})"
            )
        if evidence_items == 0:
            notes.append(
                f"no structured evidence supplied — evidence_strength floored "
                f"at {MIN_EVIDENCE_STRENGTH}"
            )

        return ScoreBreakdown(
            revenue_potential=float(revenue_potential),
            confidence_score=float(confidence_score),
            urgency_score=float(urgency),
            customer_impact=float(customer_impact),
            implementation_cost=float(cost),
            implementation_cost_adjustment=float(cost_adjustment),
            risk_score=float(_clamp01(_dec(risk_score))),
            evidence_strength=float(evidence_strength),
            expected_roi=float(expected_roi) if expected_roi is not None else None,
            opportunity_score=float(opportunity_score),
            notes=notes,
        )


# Guardrail high-risk action types map onto an explicit risk input so
# callers stay consistent with Phase 4 risk semantics.
HIGH_RISK_DEFAULT_SCORE = 0.8
MEDIUM_RISK_DEFAULT_SCORE = 0.5


def default_risk_for_action_type(action_type: str) -> float:
    """Deterministic risk input derived from the Phase 4 risk classes."""
    from backend.app.guardrails.policy import HIGH_RISK_ACTIONS

    if action_type in HIGH_RISK_ACTIONS:
        return HIGH_RISK_DEFAULT_SCORE
    if action_type == "send_campaign":
        return MEDIUM_RISK_DEFAULT_SCORE
    return 0.1
