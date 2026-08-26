"""
What-If Simulation Engine — Phase 5 Feature 8.

DETERMINISTIC scenario arithmetic. Every output is an ESTIMATE, labelled
as such everywhere it appears (is_estimate=True, "estimated_" prefixes,
explicit assumption list). Simulated values never masquerade as measured
revenue.

Formulas (documented, reproducible):

    buyers            = round(target_customers × expected_conversion)
    gross_revenue     = buyers × avg_order_value
    discount_cost     = gross_revenue × discount_percentage / 100
    campaign_cost     = target_customers × cost_per_target
    estimated_revenue = gross_revenue − discount_cost   (discount scenario)
                      | gross_revenue                    (campaign scenario)
                      | recoverable × recovery_rate      (payment_recovery)
    estimated_profit  = estimated_revenue − total_cost
    expected_roi      = estimated_profit / total_cost   (None when cost 0)
    confidence_range  = ±20% around estimated_revenue
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from backend.app.models.experiment import Simulation

log = logging.getLogger(__name__)

CONFIDENCE_RANGE_PCT = Decimal("20")
VALID_SCENARIO_TYPES = {"discount", "campaign", "payment_recovery"}
MAX_CONVERSION = Decimal("1")


def _dec(value: Any, default: Decimal | None = None) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        if default is None:
            raise ValueError(f"invalid numeric value: {value!r}")
        return default


def _q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class SimulationResult:
    scenario_type: str
    estimated_revenue: float
    estimated_cost: float
    estimated_profit: float
    expected_conversion: float
    expected_roi: float | None
    confidence_low: float | None
    confidence_high: float | None
    assumptions: list[str] = field(default_factory=list)
    is_estimate: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SimulationValidationError(ValueError):
    """Raised when a scenario's inputs are outside documented bounds."""


class SimulationEngine:
    def __init__(self, db: Session | None = None) -> None:
        self.db = db

    # ── shared math ──────────────────────────────────────────────────────

    @staticmethod
    def _validate_common(
        *, target_customers: int, expected_conversion: Any, avg_order_value: Any
    ) -> tuple[Decimal, Decimal, Decimal]:
        if target_customers < 0:
            raise SimulationValidationError("target_customers cannot be negative")
        conversion = _dec(expected_conversion)
        if not (0 <= conversion <= MAX_CONVERSION):
            raise SimulationValidationError(
                f"expected_conversion must be within [0, 1], got {conversion}"
            )
        aov = _dec(avg_order_value)
        if aov < 0:
            raise SimulationValidationError("avg_order_value cannot be negative")
        return Decimal(target_customers), conversion, aov

    def _finish(
        self,
        *,
        scenario_type: str,
        estimated_revenue: Decimal,
        total_cost: Decimal,
        conversion: Decimal,
        assumptions: list[str],
    ) -> SimulationResult:
        profit = estimated_revenue - total_cost
        roi = (_q2(profit / total_cost) if total_cost > 0 else None)
        spread = estimated_revenue * CONFIDENCE_RANGE_PCT / Decimal("100")
        return SimulationResult(
            scenario_type=scenario_type,
            estimated_revenue=float(_q2(estimated_revenue)),
            estimated_cost=float(_q2(total_cost)),
            estimated_profit=float(_q2(profit)),
            expected_conversion=float(conversion),
            expected_roi=float(roi) if roi is not None else None,
            confidence_low=float(_q2(estimated_revenue - spread)),
            confidence_high=float(_q2(estimated_revenue + spread)),
            assumptions=assumptions,
            is_estimate=True,
        )

    # ── scenarios ────────────────────────────────────────────────────────

    def simulate_discount(
        self,
        *,
        discount_percentage: Any,
        target_customers: int,
        expected_conversion: Any,
        avg_order_value: Any,
    ) -> SimulationResult:
        pct = _dec(discount_percentage)
        if not (0 <= pct <= 100):
            raise SimulationValidationError("discount_percentage must be 0–100")
        targets, conversion, aov = self._validate_common(
            target_customers=target_customers,
            expected_conversion=expected_conversion,
            avg_order_value=avg_order_value,
        )
        buyers = _q2(targets * conversion)
        gross = buyers * aov
        discount_cost = gross * pct / Decimal("100")
        assumptions = [
            f"{pct}% discount applied to gross revenue",
            f"{targets:.0f} targeted customers × {conversion} expected conversion "
            f"= {buyers:.0f} expected buyers",
            f"average order value ₹{aov}",
            "no halo effect on non-discounted items assumed",
        ]
        result = self._finish(
            scenario_type="discount",
            estimated_revenue=gross - discount_cost,
            total_cost=discount_cost,
            conversion=conversion,
            assumptions=assumptions,
        )
        return result

    def simulate_campaign(
        self,
        *,
        target_customers: int,
        expected_conversion: Any,
        avg_order_value: Any,
        cost_per_target: Any = "0",
    ) -> SimulationResult:
        targets, conversion, aov = self._validate_common(
            target_customers=target_customers,
            expected_conversion=expected_conversion,
            avg_order_value=avg_order_value,
        )
        cpt = _dec(cost_per_target, Decimal("0"))
        if cpt < 0:
            raise SimulationValidationError("cost_per_target cannot be negative")
        buyers = _q2(targets * conversion)
        gross = buyers * aov
        cost = targets * cpt
        assumptions = [
            f"{targets:.0f} customers contacted once",
            f"expected conversion {conversion} ⇒ {buyers:.0f} buyers",
            f"average order value ₹{aov}",
            f"campaign delivery cost ₹{cpt}/target",
        ]
        return self._finish(
            scenario_type="campaign",
            estimated_revenue=gross,
            total_cost=cost,
            conversion=conversion,
            assumptions=assumptions,
        )

    def simulate_payment_recovery(
        self,
        *,
        failed_payment_value: Any,
        recovery_rate: Any,
        cost_per_contact: Any = "0",
        contacts: int = 0,
    ) -> SimulationResult:
        value = _dec(failed_payment_value)
        if value < 0:
            raise SimulationValidationError("failed_payment_value cannot be negative")
        rate = _dec(recovery_rate)
        if not (0 <= rate <= MAX_CONVERSION):
            raise SimulationValidationError("recovery_rate must be within [0, 1]")
        cpc = _dec(cost_per_contact, Decimal("0"))
        contacts_dec = Decimal(max(contacts, 0))
        recovered = value * rate
        cost = cpc * contacts_dec
        assumptions = [
            f"₹{value} of failed payments is addressable",
            f"{rate} of contacted customers are assumed to complete retry",
            (
                f"{contacts:.0f} contacts at ₹{cpc} each"
                if contacts
                else "no contact cost modelled"
            ),
        ]
        return self._finish(
            scenario_type="payment_recovery",
            estimated_revenue=recovered,
            total_cost=cost,
            conversion=rate,
            assumptions=assumptions,
        )

    def simulate(self, scenario_type: str, **kwargs: Any) -> SimulationResult:
        """Dispatcher used by the API layer and agents."""
        dispatch = {
            "discount": self.simulate_discount,
            "campaign": self.simulate_campaign,
            "payment_recovery": self.simulate_payment_recovery,
        }
        fn = dispatch.get(scenario_type)
        if fn is None:
            raise SimulationValidationError(
                f"unknown scenario type {scenario_type!r}; valid: {sorted(dispatch)}"
            )
        return fn(**kwargs)

    # ── persistence ──────────────────────────────────────────────────────

    def persist(
        self,
        result: SimulationResult,
        *,
        merchant_id: uuid.UUID,
        opportunity_id: uuid.UUID | None = None,
        created_by_agent: str | None = None,
        inputs: dict[str, Any] | None = None,
    ) -> Simulation:
        if self.db is None:
            raise RuntimeError("persist() requires a database session")
        row = Simulation(
            merchant_id=merchant_id,
            opportunity_id=opportunity_id,
            created_by_agent=created_by_agent,
            scenario_type=result.scenario_type,
            inputs=inputs or {},
            estimated_revenue=_dec(result.estimated_revenue),
            estimated_cost=_dec(result.estimated_cost),
            estimated_profit=_dec(result.estimated_profit),
            expected_conversion=_dec(result.expected_conversion).quantize(
                Decimal("0.0001")
            ),
            expected_roi=(
                _dec(result.expected_roi)
                if result.expected_roi is not None
                else None
            ),
            confidence_low=(
                _dec(result.confidence_low)
                if result.confidence_low is not None
                else None
            ),
            confidence_high=(
                _dec(result.confidence_high)
                if result.confidence_high is not None
                else None
            ),
            assumptions=result.assumptions,
            is_estimate=True,  # ALWAYS — simulations are never real outcomes
        )
        self.db.add(row)
        self.db.flush()
        return row
