"""
Per-customer next-best-action decisions.

Why a dedicated table
---------------------
The repository already computes rich per-customer facts — lifetime value,
recency, churn risk, payment success rate, segment
(``services/customer_intelligence.py``) — and catalog-level affinity
(``services/product_intelligence.py``). What did not exist anywhere was the
*decision* layer: a persisted, per-customer, explainable recommendation with
a cohort assignment so its effect can be measured honestly.

This table holds that decision. It deliberately does NOT duplicate the
upstream metrics: it stores the decision plus a frozen copy of the evidence
that produced it, so a decision stays explainable even after the underlying
metrics move.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PersonalizationDecision(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    One next-best-action decision for one customer.

    ``cohort`` is the honest-measurement lever: half the eligible population
    is assigned to ``control`` and receives no intervention, which is what
    makes a later uplift comparison attributable rather than a guess.
    """

    __tablename__ = "personalization_decisions"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Stable per-customer action vocabulary (see services.personalization).
    recommended_action: Mapped[str] = mapped_column(
        String(40), nullable=False, index=True
    )
    #: ``treatment`` (act) or ``control`` (hold) — the measurement lever.
    cohort: Mapped[str] = mapped_column(
        String(12), nullable=False, default="treatment", server_default="treatment"
    )
    score: Mapped[float] = mapped_column(Numeric(8, 5), nullable=False, default=0.0)
    #: Frozen evidence: the metrics and signals that produced this decision.
    rationale: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: Affinity-linked product ids, from REAL basket co-occurrence.
    recommended_product_ids: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    #: Deterministic partition key, so the same customer always lands in the
    #: same cohort across runs (otherwise the control group churns and any
    #: comparison is meaningless).
    assignment_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: Stable id for the same (customer, action) pair so re-runs update rather
    #: than accumulate duplicates.
    decision_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    #: ``proposed`` until an outcome is observed.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="proposed", server_default="proposed"
    )
    #: Set only when an ACTUAL subsequent order/payment is observed.
    observed_revenue: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    measured_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "ix_personalization_decisions_merchant_status",
            "merchant_id",
            "status",
        ),
        # One live decision per (merchant, customer, action).
        Index(
            "uq_personalization_decision_key",
            "merchant_id",
            "decision_key",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<PersonalizationDecision customer={self.customer_id} "
            f"action={self.recommended_action} cohort={self.cohort}>"
        )