"""MarketingAGI memory + learning loop.

Long-term memory is stored through the platform's GrowthMemoryService
(AgentMemory rows, merchant-scoped) with a MarketingAGI-specific source
tag so the agent's memories are identifiable but still retrievable by
the existing memory infrastructure. Learnings about campaign outcomes
are ALSO persisted as MarketingAGILearning rows so the agent has its
own structured outcome record.

The learning loop: after an approved action executes, the agent observes
results, compares against expectation, records a verdict, and updates
future decision context via memory. NO fabricated outcomes — when real
results are unavailable, the learning row stays `measurement_pending`.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.marketing_agi import MarketingAGICampaign, MarketingAGILearning
from backend.app.services.memory import GrowthMemoryService

log = logging.getLogger(__name__)

MAGI_SOURCE = "marketing_agi"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MarketingAGIMemory:
    """Thin, isolated memory facade for the MarketingAGI."""

    def __init__(self, db: Session, embedding_provider=None) -> None:
        self._db = db
        self._service = GrowthMemoryService(db, embedding_provider)

    # ── write path ───────────────────────────────────────────────────────

    def record_investigation(
        self, merchant_id: uuid.UUID, *, statement: str, importance: float = 0.5
    ) -> None:
        self._service.record(
            merchant_id=merchant_id,
            memory_type="recommendation",
            content=f"[MarketingAGI investigation] {statement}",
            source_type=MAGI_SOURCE,
            source_id="investigation",
            importance=importance,
        )

    def record_outcome(
        self,
        merchant_id: uuid.UUID,
        *,
        action_type: str,
        strategy_summary: str,
        expected_revenue: float | None,
        actual_revenue: float | None,
        action_id: str | None = None,
    ) -> None:
        """Close the measure→learn loop with honest numbers."""
        self._service.record_action_outcome(
            merchant_id=merchant_id,
            action_type=action_type,
            strategy_summary=strategy_summary,
            expected_revenue=expected_revenue,
            actual_revenue=actual_revenue,
            action_id=action_id,
        )

    def record_preference(
        self, merchant_id: uuid.UUID, *, preference: str
    ) -> None:
        self._service.record(
            merchant_id=merchant_id,
            memory_type="merchant_preference",
            content=f"[MarketingAGI] {preference}",
            source_type=MAGI_SOURCE,
            source_id="preference",
            importance=0.6,
        )

    # ── read path ────────────────────────────────────────────────────────

    def recall(self, merchant_id: uuid.UUID, query: str, k: int = 5) -> list[dict[str, Any]]:
        return self._service.retrieve(merchant_id, query, k=k)


class MarketingAGILearningStore:
    """Structured learning rows for executed campaigns."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def open_learning(
        self,
        merchant_id: uuid.UUID,
        *,
        campaign_id: uuid.UUID,
        action_id: uuid.UUID,
        expected: dict[str, Any],
    ) -> MarketingAGILearning:
        row = MarketingAGILearning(
            merchant_id=merchant_id,
            campaign_id=campaign_id,
            action_id=action_id,
            status="measuring",
            expected=expected,
        )
        self._db.add(row)
        self._db.flush()
        return row

    def record_measurement(
        self,
        learning: MarketingAGILearning,
        *,
        actual: dict[str, Any],
        verdict: str,
        insights: str,
    ) -> MarketingAGILearning:
        learning.actual = actual
        learning.verdict = verdict
        learning.insights = insights
        learning.status = "learned"
        learning.learned_at = utcnow()
        self._db.flush()
        return learning

    def record_measurement_pending(
        self, learning: MarketingAGILearning, *, reason: str
    ) -> MarketingAGILearning:
        learning.status = "measurement_pending"
        learning.insights = reason
        self._db.flush()
        return learning

    def list_learnings(
        self, merchant_id: uuid.UUID, *, limit: int = 20
    ) -> list[MarketingAGILearning]:
        stmt = (
            select(MarketingAGILearning)
            .where(MarketingAGILearning.merchant_id == merchant_id)
            .order_by(MarketingAGILearning.created_at.desc())
            .limit(limit)
        )
        return list(self._db.scalars(stmt).all())


def evaluate_outcome(
    expected_revenue: float | None, actual_revenue: float | None
) -> tuple[str, str]:
    """Verdict + insight text from real numbers only."""
    if actual_revenue is None or expected_revenue in (None, 0):
        return (
            "measurement_pending",
            "Actual results not yet available; no outcome claim made.",
        )
    ratio = actual_revenue / expected_revenue
    if ratio >= 0.9:
        return (
            "met_expectation",
            f"Delivered {ratio:.0%} of expected revenue — strategy worked as designed.",
        )
    if ratio >= 0.5:
        return (
            "partially_met",
            f"Delivered {ratio:.0%} of expected revenue — worth refining the audience or offer.",
        )
    return (
        "underperformed",
        f"Delivered only {ratio:.0%} of expected revenue — reconsider this strategy for this audience.",
    )
