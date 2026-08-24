"""
AIAnalysisService — production entry point for AI-powered growth analysis.

Orchestrates:
  1. Validate merchant exists
  2. Audit: analysis_started
  3. Build agent toolkit (read-only tools)
  4. Run agentic RAG pipeline
  5. Audit: analysis_completed / analysis_failed
  6. Return structured AgentState (caller commits)

Money safety:
  - Never executes financial actions.
  - Every analysis is audit-logged with WHO / WHAT / WHEN / RESULT.
  - Insights always start as pending_approval.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.app.ai.agents.state import AgentState
from backend.app.ai.agents.tools import AgentToolkit
from backend.app.ai.embeddings.base import BaseEmbeddingProvider
from backend.app.ai.llm.base import BaseLLMProvider
from backend.app.ai.rag.pipeline import AgenticRAGPipeline
from backend.app.models.enums import ActorType, AuditEventType
from backend.app.repositories.merchant import MerchantRepository

log = logging.getLogger(__name__)


def _write_audit_event(
    db: Session,
    merchant_id: uuid.UUID,
    event_type: AuditEventType,
    entity_id: str,
    payload: dict,
) -> None:
    """
    Append an immutable audit event.

    Never raises — a logging failure must never crash an analysis run.
    Does NOT store: API keys, passwords, customer PII, raw LLM reasoning.
    """
    try:
        from backend.app.models.audit_event import AuditEvent
        evt = AuditEvent(
            merchant_id=merchant_id,
            actor_type=ActorType.ai_agent,
            actor_id="growth_analysis_agent",
            event_type=event_type,
            entity_type="analysis",
            entity_id=entity_id,
            payload=payload,
        )
        db.add(evt)
        db.flush()
    except Exception as exc:
        log.warning("Failed to write audit event %s: %s", event_type, exc)


class AIAnalysisService:
    """
    High-level service for AI growth analysis.

    Wires together the agentic pipeline, audit trail, and safe error
    handling.  All insights produced default to status=pending_approval.
    """

    def __init__(
        self,
        db: Session,
        llm: BaseLLMProvider,
        embedding_provider: BaseEmbeddingProvider,
    ) -> None:
        self._db = db
        self._llm = llm
        self._embedder = embedding_provider
        self._merchant_repo = MerchantRepository(db)

    def analyse(
        self,
        goal: str,
        merchant_id: uuid.UUID,
    ) -> AgentState:
        """
        Run a full agentic growth analysis for the merchant.

        Audit trail:
          analysis_started  → analysis running
          analysis_completed → insights produced
          analysis_failed   → pipeline error
          (insufficient evidence handled as analysis_completed with flag)

        Returns:
          AgentState — caller is responsible for db.commit()
        """
        merchant = self._merchant_repo.get_by_id(merchant_id)
        if not merchant:
            state = AgentState(goal=goal, merchant_id=str(merchant_id))
            state.fail(f"Merchant {merchant_id} not found.")
            return state

        log.info(
            "AI analysis started. merchant=%s name=%r goal=%r",
            merchant_id, merchant.name, goal[:80],
        )

        # Audit: started
        _write_audit_event(
            self._db, merchant_id,
            AuditEventType.analysis_started,
            "pending",
            {
                "goal": goal[:500],
                "merchant_name": merchant.name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        # Build and run agentic pipeline
        toolkit = AgentToolkit(
            db=self._db,
            merchant_id=merchant_id,
            embedding_provider=self._embedder,
        )
        pipeline = AgenticRAGPipeline(llm=self._llm, toolkit=toolkit)
        state = pipeline.run(goal=goal, merchant_id=merchant_id)

        # Audit: completion (covers all terminal states)
        if state.status == "completed":
            _write_audit_event(
                self._db, merchant_id,
                AuditEventType.analysis_completed,
                state.run_id,
                {
                    "insights_count": len(state.insights),
                    "retrieval_steps": state.retrieval_steps_used,
                    "evidence_summary": state.evidence_summary[:500],
                    "tool_calls": [tc.tool_name for tc in state.tool_calls],
                },
            )
        elif state.status == "failed":
            _write_audit_event(
                self._db, merchant_id,
                AuditEventType.analysis_failed,
                state.run_id,
                {"error": state.error},
            )
        else:
            # insufficient_evidence
            _write_audit_event(
                self._db, merchant_id,
                AuditEventType.analysis_completed,
                state.run_id,
                {
                    "status": state.status,
                    "evidence_summary": state.evidence_summary[:500],
                    "retrieval_steps": state.retrieval_steps_used,
                },
            )

        log.info(
            "AI analysis done. run_id=%s status=%s insights=%d steps=%d",
            state.run_id, state.status,
            len(state.insights), state.retrieval_steps_used,
        )
        return state
