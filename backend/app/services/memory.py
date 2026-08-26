"""
GrowthMemoryService — Phase 5 Features 10 & 11.

Structured memory for exactly one merchant at a time:
  - record() stores recommendations, outcomes, preferences, campaign history
  - retrieve() ranks by semantic similarity (when an embedding provider is
    configured) + recency + importance; falls back to deterministic keyword
    overlap when no provider exists — retrieval is ALWAYS merchant-scoped,
    so one merchant's memory can never surface for another.

Feature 11 (learning from results): record_action_outcome() stores what was
expected versus what was actually measured, including the variance — plain
evidence-based memory, NOT reinforcement learning.
"""
from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.agent_memory import AgentMemory
from backend.app.models.enums import MemoryType

log = logging.getLogger(__name__)

RECENCY_HALF_LIFE_DAYS = 30.0
RECENCY_WEIGHT = 0.25
IMPORTANCE_WEIGHT = 0.15


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _safe_dec(v: Any) -> Decimal | None:
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


class GrowthMemoryService:
    def __init__(
        self, db: Session, embedding_provider: Any = None
    ) -> None:
        self.db = db
        self.embedding_provider = embedding_provider

    # ── write path ───────────────────────────────────────────────────────

    def record(
        self,
        *,
        merchant_id: uuid.UUID,
        memory_type: MemoryType | str,
        content: str,
        summary: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        importance: float = 0.5,
        memory_metadata: dict[str, Any] | None = None,
        outcome_variance_pct: float | None = None,
    ) -> AgentMemory:
        if not content or not content.strip():
            raise ValueError("memory content is required")
        mt = (
            memory_type
            if isinstance(memory_type, MemoryType)
            else MemoryType(memory_type)
        )
        embedding: list[float] | None = None
        if self.embedding_provider is not None:
            try:
                embedding = self.embedding_provider.embed_text(content[:2000])
            except Exception as exc:  # embedding failure must never block memory
                log.warning("Embedding failed for memory: %s", exc)

        row = AgentMemory(
            merchant_id=merchant_id,
            memory_type=mt,
            content=content.strip(),
            summary=(summary or content.strip()[:200]),
            embedding=embedding,
            source_type=source_type,
            source_id=source_id,
            importance=Decimal(str(min(max(importance, 0.0), 1.0))).quantize(
                Decimal("0.01")
            ),
            memory_metadata=memory_metadata or {},
            outcome_variance_pct=(
                _safe_dec(outcome_variance_pct) if outcome_variance_pct is not None else None
            ),
            occurred_at=_utcnow(),
        )
        self.db.add(row)
        self.db.flush()
        return row

    def record_action_outcome(
        self,
        *,
        merchant_id: uuid.UUID,
        action_type: str,
        strategy_summary: str,
        expected_revenue: float | None,
        actual_revenue: float | None,
        action_id: str | None = None,
    ) -> AgentMemory | None:
        """
        Feature 11 — close the measure→learn loop.

        Stores a factual memory of expected vs actual. When real measured
        revenue is unavailable (None / measurement_pending), records the
        absence explicitly instead of inventing an outcome.
        """
        variance_pct: float | None = None
        if expected_revenue and actual_revenue is not None and expected_revenue > 0:
            variance_pct = round(
                (actual_revenue - expected_revenue) / expected_revenue * 100, 2
            )
            interpretation = (
                "performed better than expected"
                if variance_pct > 0
                else "underperformed expectations" if variance_pct < 0
                else "matched expectations"
            )
            content = (
                f"Action '{action_type}': {strategy_summary}. "
                f"Expected ₹{expected_revenue:.2f}, actual ₹{actual_revenue:.2f} "
                f"({variance_pct:+.2f}% — {interpretation})."
            )
        else:
            content = (
                f"Action '{action_type}': {strategy_summary}. "
                f"Expected revenue ₹{expected_revenue or 0:.2f}; actual revenue "
                f"not yet available (measurement pending). No outcome claim made."
            )
        return self.record(
            merchant_id=merchant_id,
            memory_type=MemoryType.action_result,
            content=content,
            summary=f"{action_type}: {strategy_summary[:120]}",
            source_type="agent_action",
            source_id=action_id,
            importance=0.8 if variance_pct is not None else 0.4,
            outcome_variance_pct=variance_pct,
            memory_metadata={
                "action_type": action_type,
                "expected_revenue": expected_revenue,
                "actual_revenue": actual_revenue,
                "measurement_complete": actual_revenue is not None,
            },
        )

    # ── read path ────────────────────────────────────────────────────────

    def retrieve(
        self,
        merchant_id: uuid.UUID,
        query: str,
        *,
        k: int = 5,
        memory_type: MemoryType | str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Merchant-scoped retrieval ranked by:

            score = semantic_similarity          (if embeddings available)
                  + RECENCY_WEIGHT × recency_decay
                  + IMPORTANCE_WEIGHT × importance

        Without embeddings (or query embedding failure), similarity falls
        back to case-insensitive keyword-overlap fraction. Cross-merchant
        rows are filtered out in SQL — never merely re-ranked away.
        """
        stmt = select(AgentMemory).where(AgentMemory.merchant_id == merchant_id)
        if memory_type is not None:
            mt = (
                memory_type
                if isinstance(memory_type, MemoryType)
                else MemoryType(memory_type)
            )
            stmt = stmt.where(AgentMemory.memory_type == mt.value)
        stmt = stmt.order_by(AgentMemory.created_at.desc()).limit(500)
        memories = list(self.db.scalars(stmt).all())
        if not memories:
            return []

        query_embedding: list[float] | None = None
        if self.embedding_provider is not None and query.strip():
            try:
                query_embedding = self.embedding_provider.embed_text(query[:2000])
            except Exception as exc:
                log.warning("Query embedding failed: %s", exc)

        now = _utcnow()
        scored: list[tuple[float, AgentMemory]] = []
        for mem in memories:
            similarity = self._similarity(mem, query, query_embedding)
            recency = self._recency_decay(mem, now)
            importance = float(mem.importance or 0)
            scored.append((similarity + recency * RECENCY_WEIGHT + importance * IMPORTANCE_WEIGHT, mem))
        scored.sort(key=lambda pair: pair[0], reverse=True)

        return [
            {
                "id": str(mem.id),
                "memory_type": str(getattr(mem.memory_type, "value", mem.memory_type)),
                "content": mem.content,
                "summary": mem.summary,
                "score": round(score, 4),
                "importance": float(mem.importance or 0),
                "outcome_variance_pct": (
                    float(mem.outcome_variance_pct)
                    if mem.outcome_variance_pct is not None
                    else None
                ),
                "created_at": str(mem.created_at),
            }
            for score, mem in scored[: max(k, 1)]
        ]

    @staticmethod
    def _recency_decay(mem: AgentMemory, now: datetime) -> float:
        occurred = mem.occurred_at or mem.created_at
        if occurred is None:
            return 0.0
        if occurred.tzinfo is None:
            from datetime import timezone

            occurred = occurred.replace(tzinfo=timezone.utc)
        days = max((now - occurred).total_seconds() / 86400.0, 0.0)
        return math.pow(0.5, days / RECENCY_HALF_LIFE_DAYS)

    def _similarity(
        self,
        mem: AgentMemory,
        query: str,
        query_embedding: list[float] | None,
    ) -> float:
        if query_embedding and mem.embedding:
            cos = _cosine(query_embedding, mem.embedding)
            if cos is not None:
                return max(0.0, cos)  # cosine ∈ [-1,1]; only positive side ranks
        return self._keyword_overlap(query, mem.content)

    @staticmethod
    def _keyword_overlap(query: str, content: str) -> float:
        q_terms = {t for t in query.lower().split() if len(t) > 2}
        if not q_terms:
            return 0.0
        c_terms = set(content.lower().split())
        return len(q_terms & c_terms) / len(q_terms)


def _cosine(a: list[float], b: list[float]) -> float | None:
    if not a or not b or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return None
    return dot / (na * nb)
