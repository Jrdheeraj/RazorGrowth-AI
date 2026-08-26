"""Simulation and Experiment models — Phase 5 what-if engine + A/B proposals.

All simulated values are ESTIMATES. `is_estimate` is always True on rows
created by the simulation engine — simulated revenue must never be
confusable with measured revenue.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.app.models.enums import ExperimentStatus

if TYPE_CHECKING:
    from backend.app.models.merchant import Merchant


class Simulation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A deterministic what-if scenario result (never real outcomes)."""

    __tablename__ = "simulations"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("growth_opportunities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_agent: Mapped[str | None] = mapped_column(String(80), nullable=True)
    scenario_type: Mapped[str] = mapped_column(String(60), nullable=False)
    inputs: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    estimated_revenue: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    estimated_cost: Mapped[Decimal] = mapped_column(
        Numeric(16, 2), nullable=False, default=0
    )
    estimated_profit: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    expected_conversion: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), nullable=False
    )
    expected_roi: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    confidence_low: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    confidence_high: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    assumptions: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    is_estimate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    merchant: Mapped["Merchant"] = relationship(
        "Merchant", foreign_keys=[merchant_id], back_populates="simulations"
    )

    def __repr__(self) -> str:
        return f"<Simulation {self.scenario_type} est={self.estimated_revenue}>"


class Experiment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A proposed A/B experiment. Statistics are only claimed when earned."""

    __tablename__ = "experiments"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("growth_opportunities.id", ondelete="SET NULL"),
        nullable=True,
    )
    experiment_key: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hypothesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ExperimentStatus] = mapped_column(
        String(30),
        nullable=False,
        default=ExperimentStatus.proposed,
        server_default=ExperimentStatus.proposed.value,
        index=True,
    )

    control_group: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    treatment_group: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    target_population_size: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    estimated_metric: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    merchant: Mapped["Merchant"] = relationship(
        "Merchant", foreign_keys=[merchant_id], back_populates="experiments"
    )
    results: Mapped[list["ExperimentResult"]] = relationship(
        "ExperimentResult", back_populates="experiment", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_experiments_merchant_key", "merchant_id", "experiment_key", unique=True),
    )


class ExperimentResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Measured experiment outcome.

    uplift / confidence are populated ONLY from real recorded conversions.
    When sample sizes are below the minimum threshold the service reports
    measurement_pending instead of inventing significance.
    """

    __tablename__ = "experiment_results"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    control_conversions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    control_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    treatment_conversions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    treatment_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actual_metric: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    uplift_percentage: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    statistical_status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="measurement_pending",
        server_default="measurement_pending",
    )

    experiment: Mapped[Experiment] = relationship("Experiment", back_populates="results")

    def __repr__(self) -> str:
        return f"<ExperimentResult experiment={self.experiment_id}>"
