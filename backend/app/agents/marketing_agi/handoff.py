"""Agent-to-agent handoff interface — collaboration boundary for future agents.

The MarketingAGI can REQUEST specialist analysis (customer intelligence,
product strategy, creative review, technical feasibility) through a
structured handoff. Today NO other agent is upgraded or invoked; the
handoff is recorded as PENDING with the full request package (request,
context, evidence, question, required output) so a future specialist can
pick it up and respond. The MarketingAGI proceeds only with its own
verified evidence — it never fabricates a specialist response.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.marketing_agi import MarketingAGIHandoff

SUPPORTED_SPECIALISTS = [
    "customer_intelligence",
    "product_strategist",
    "creative_ux",
    "technical_feasibility",
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HandoffInterface:
    """Create and inspect collaboration handoffs (merchant-scoped)."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def request(
        self,
        merchant_id: uuid.UUID,
        *,
        specialist: str,
        question: str,
        context: dict[str, Any],
        evidence: list[dict[str, Any]],
        required_output: str,
        run_id: uuid.UUID | None = None,
    ) -> MarketingAGIHandoff:
        if specialist not in SUPPORTED_SPECIALISTS:
            raise ValueError(
                f"Unsupported specialist: {specialist}. Supported: {SUPPORTED_SPECIALISTS}"
            )
        row = MarketingAGIHandoff(
            merchant_id=merchant_id,
            run_id=run_id,
            specialist=specialist,
            status="pending",
            request={
                "question": question,
                "context": context,
                "evidence": evidence,
                "required_output": required_output,
            },
        )
        self._db.add(row)
        self._db.flush()
        return row

    def attach_response(
        self,
        handoff: MarketingAGIHandoff,
        *,
        response: dict[str, Any],
        responder: str,
    ) -> MarketingAGIHandoff:
        """Future specialists respond here. The MarketingAGI never writes this itself."""
        handoff.response = {**response, "responder": responder}
        handoff.status = "responded"
        handoff.responded_at = utcnow()
        self._db.flush()
        return handoff

    def list_handoffs(
        self, merchant_id: uuid.UUID, *, limit: int = 20
    ) -> list[MarketingAGIHandoff]:
        stmt = (
            select(MarketingAGIHandoff)
            .where(MarketingAGIHandoff.merchant_id == merchant_id)
            .order_by(MarketingAGIHandoff.created_at.desc())
            .limit(limit)
        )
        return list(self._db.scalars(stmt).all())


def serialize_handoff(h: MarketingAGIHandoff) -> dict[str, Any]:
    return {
        "id": str(h.id),
        "run_id": str(h.run_id) if h.run_id else None,
        "specialist": h.specialist,
        "status": h.status,
        "request": h.request,
        "response": h.response,
        "responded_at": str(h.responded_at) if h.responded_at else None,
        "created_at": str(h.created_at),
    }
