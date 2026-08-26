"""
Opportunity upsert — Phase 5 Feature 12 (deterministic deduplication).

The same opportunity must not repeatedly appear across agent runs.
Deterministic keys:

    opportunity_key = sha256(
        merchant_id : opportunity_type : target_segment : time_window_bucket
    ) truncated to 32 hex chars (fits the existing String(100) column).

Repeated detection REINFORCES the existing row (confidence raised toward
the new value, stronger revenue kept, evidence appended) instead of
creating duplicates. Keys are merchant-scoped by construction.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from backend.app.models.enums import OpportunityStatus, OpportunityType
from backend.app.models.opportunity import GrowthOpportunity
from backend.app.repositories.opportunity import GrowthOpportunityRepository

log = logging.getLogger(__name__)

MAX_REASONING_ITEMS = 40


def build_opportunity_key(
    merchant_id: uuid.UUID,
    opportunity_type: str,
    target_segment: str,
    window_days: int = 30,
) -> str:
    """
    Stable, deterministic key. Same logical opportunity ⇒ same key on
    every run, independent of insertion order or timestamps.
    """
    raw = f"{merchant_id}:{opportunity_type}:{target_segment}:{window_days}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def upsert_opportunity(
    db: Session,
    *,
    merchant_id: uuid.UUID,
    opportunity_key: str,
    type_: OpportunityType,
    title: str,
    description: str | None = None,
    confidence: Decimal,
    expected_revenue: Decimal,
    target_customer_count: int = 0,
    reasoning: list[Any] | None = None,
    status: OpportunityStatus = OpportunityStatus.pending_approval,
) -> tuple[GrowthOpportunity, bool]:
    """
    Create the opportunity if absent, otherwise reinforce the existing row.

    Returns (opportunity, created).
    Reinforcement rules (deterministic):
      - confidence := max(existing, incoming)
      - expected_revenue := max(existing, incoming)
      - target_customer_count := max(existing, incoming)
      - reasoning := existing + new items (deduped, capped)
      - status is NEVER changed by reinforcement — lifecycle transitions
        belong to the Phase 4 state machine.
    """
    repo = GrowthOpportunityRepository(db)
    existing = repo.get_by_key(merchant_id, opportunity_key)

    new_reasoning = [r for r in (reasoning or []) if r]

    if existing is not None:
        existing.confidence = max(
            Decimal(str(existing.confidence)), Decimal(str(confidence))
        )
        existing.expected_revenue = max(
            Decimal(str(existing.expected_revenue)), Decimal(str(expected_revenue))
        )
        if target_customer_count > (existing.target_customer_count or 0):
            existing.target_customer_count = target_customer_count
        merged: list[Any] = list(existing.reasoning or [])
        seen = {str(item) for item in merged}
        for item in new_reasoning:
            s = str(item)
            if s not in seen:
                merged.append(item)
                seen.add(s)
        existing.reasoning = merged[:MAX_REASONING_ITEMS]
        db.flush()
        log.info(
            "Opportunity reinforced (not duplicated). key=%s merchant=%s",
            opportunity_key[:12], merchant_id,
        )
        return existing, False

    opp = repo.create(
        merchant_id=merchant_id,
        opportunity_key=opportunity_key,
        type=type_,
        title=title,
        description=description,
        confidence=Decimal(str(confidence)),
        expected_revenue=Decimal(str(expected_revenue)),
        target_customer_count=target_customer_count,
        reasoning=new_reasoning[:MAX_REASONING_ITEMS],
        status=status,
    )
    return opp, True
