"""
Experiment / A-B Test Engine — Phase 5 Feature 9.

Proposes experiments with control/treatment definitions and evaluates
them HONESTLY:

  - uplift is reported ONLY when both groups have recorded conversions,
  - "statistically significant" is NEVER claimed unless both arms meet
    MIN_DETECTABLE_SAMPLE (deterministic threshold) AND the uplift
    exceeds the minimum relative difference,
  - otherwise results stay `measurement_pending` — absence of evidence
    is reported as such, never dressed up.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.enums import ExperimentStatus
from backend.app.models.experiment import Experiment, ExperimentResult

log = logging.getLogger(__name__)

# Deterministic honesty thresholds — below these, no claim is possible.
MIN_DETECTABLE_SAMPLE = 30        # conversions+non-conversions per arm
MIN_RELATIVE_UPLIFT_PCT = Decimal("5")  # noise band for "directional" claims


def _dec(v: Any) -> Decimal:
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


class ExperimentValidationError(ValueError):
    pass


class ExperimentService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── creation ─────────────────────────────────────────────────────────

    def create_experiment(
        self,
        *,
        merchant_id: uuid.UUID,
        name: str,
        hypothesis: str | None = None,
        opportunity_id: uuid.UUID | None = None,
        control_group: dict[str, Any] | None = None,
        treatment_group: dict[str, Any] | None = None,
        target_population_size: int = 0,
        estimated_metric: dict[str, Any] | None = None,
    ) -> Experiment:
        if not name or not name.strip():
            raise ExperimentValidationError("experiment name is required")
        if target_population_size < 0:
            raise ExperimentValidationError("target_population_size cannot be negative")
        control_group = control_group or {}
        treatment_group = treatment_group or {}

        experiment_key = hashlib.sha256(
            f"{merchant_id}:{name.strip().lower()}".encode()
        ).hexdigest()[:32]

        existing = self.get_by_key(merchant_id, experiment_key)
        if existing is not None:
            return existing  # idempotent proposal

        experiment = Experiment(
            merchant_id=merchant_id,
            opportunity_id=opportunity_id,
            experiment_key=experiment_key,
            name=name.strip(),
            hypothesis=hypothesis,
            status=ExperimentStatus.proposed,
            control_group=control_group,
            treatment_group=treatment_group,
            target_population_size=target_population_size,
            estimated_metric=estimated_metric or {},
        )
        self.db.add(experiment)
        self.db.flush()
        return experiment

    def get_by_key(
        self, merchant_id: uuid.UUID, experiment_key: str
    ) -> Experiment | None:
        return self.db.scalars(
            select(Experiment).where(
                Experiment.merchant_id == merchant_id,
                Experiment.experiment_key == experiment_key,
            )
        ).first()

    def list_experiments(
        self, merchant_id: uuid.UUID, *, limit: int = 100
    ) -> list[Experiment]:
        stmt = (
            select(Experiment)
            .where(Experiment.merchant_id == merchant_id)
            .order_by(Experiment.created_at.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())

    def get_experiment(
        self, merchant_id: uuid.UUID, experiment_id: uuid.UUID
    ) -> Experiment | None:
        """Merchant-scoped fetch — cross-tenant ids return None."""
        return self.db.scalars(
            select(Experiment).where(
                Experiment.merchant_id == merchant_id,
                Experiment.id == experiment_id,
            )
        ).first()

    # ── evaluation ───────────────────────────────────────────────────────

    def record_result(
        self,
        *,
        experiment: Experiment,
        control_size: int,
        control_conversions: int,
        treatment_size: int,
        treatment_conversions: int,
    ) -> ExperimentResult:
        """
        Record measured outcomes. Uplift is computed only from real counts;
        the statistical status is decided by deterministic thresholds.
        """
        for label, size, conv in (
            ("control", control_size, control_conversions),
            ("treatment", treatment_size, treatment_conversions),
        ):
            if size < 0 or conv < 0 or conv > size:
                raise ExperimentValidationError(
                    f"{label}: conversions must be within [0, size]"
                )

        control_cr = (
            Decimal(control_conversions) / Decimal(control_size)
            if control_size > 0
            else None
        )
        treatment_cr = (
            Decimal(treatment_conversions) / Decimal(treatment_size)
            if treatment_size > 0
            else None
        )

        uplift: Decimal | None = None
        status = "measurement_pending"
        actual_metric: dict[str, Any] = {
            "control_conversion_rate": float(control_cr) if control_cr is not None else None,
            "treatment_conversion_rate": float(treatment_cr) if treatment_cr is not None else None,
            "min_detectable_sample": MIN_DETECTABLE_SAMPLE,
        }

        enough_data = (
            control_size >= MIN_DETECTABLE_SAMPLE
            and treatment_size >= MIN_DETECTABLE_SAMPLE
            and control_cr is not None
            and treatment_cr is not None
        )
        if enough_data and control_cr > 0:
            uplift = ((treatment_cr - control_cr) / control_cr * 100).quantize(
                Decimal("0.01")
            )
            if abs(uplift) >= MIN_RELATIVE_UPLIFT_PCT:
                status = "directional_uplift"   # honest wording: NOT significance
            else:
                status = "no_material_difference"
        elif enough_data and control_cr == 0 and treatment_cr > 0:
            status = "insufficient_baseline"    # cannot divide by zero CR honestly

        result = ExperimentResult(
            merchant_id=experiment.merchant_id,
            experiment_id=experiment.id,
            control_conversions=control_conversions,
            control_size=control_size,
            treatment_conversions=treatment_conversions,
            treatment_size=treatment_size,
            actual_metric=actual_metric,
            uplift_percentage=uplift,
            statistical_status=status,
        )
        self.db.add(result)

        experiment.status = (
            ExperimentStatus.completed
            if status != "measurement_pending"
            else ExperimentStatus.measurement_pending
        )
        self.db.flush()
        return result

    def latest_result(self, experiment: Experiment) -> ExperimentResult | None:
        stmt = (
            select(ExperimentResult)
            .where(ExperimentResult.experiment_id == experiment.id)
            .order_by(ExperimentResult.created_at.desc())
            .limit(1)
        )
        return self.db.scalars(stmt).first()
