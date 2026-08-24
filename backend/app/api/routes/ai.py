"""
AI routes.

POST /api/ai/ingest  — ingest production commerce data into the knowledge store.
POST /api/ai/analyze — run agentic growth analysis for a merchant.

Merchant is resolved from the first available merchant in the DB when
merchant_id is omitted (single-tenant mode; will use auth tokens in Phase 4).
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db.session import get_db
from backend.app.schemas.analysis import AnalysisResponse, AnalysisInsight, AnalysisToolCallSummary
from backend.app.schemas.ingestion import IngestRequest, IngestResponse
from backend.app.services.ai_analysis_service import AIAnalysisService
from backend.app.services.ingestion_connector import ProductionDataConnector

log = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["ai"])


# ─────────────────────────────────────────────────────────────────────────────
# Request schemas
# ─────────────────────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    goal: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="Natural language growth analysis goal",
        examples=["Find opportunities to increase merchant revenue"],
    )
    merchant_id: uuid.UUID | None = Field(
        default=None,
        description="Merchant UUID. Omit to use the first available merchant.",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Provider factories
# ─────────────────────────────────────────────────────────────────────────────

def _get_llm():
    """Build the LLM provider from settings. Raises HTTP 503 if not configured."""
    settings = get_settings()
    if settings.LLM_PROVIDER.lower() == "groq":
        api_key, model = settings.GROQ_API_KEY, settings.GROQ_MODEL
        missing_key_detail = (
            "LLM provider not configured. Set GROQ_API_KEY in environment."
        )
    else:
        api_key, model = settings.LLM_API_KEY, settings.LLM_MODEL
        missing_key_detail = (
            "LLM provider not configured. Set LLM_API_KEY in environment."
        )
    if not api_key:
        raise HTTPException(status_code=503, detail=missing_key_detail)
    from backend.app.ai.llm.provider import build_llm_provider
    return build_llm_provider(
        provider=settings.LLM_PROVIDER,
        api_key=api_key,
        model=model,
        timeout=settings.LLM_REQUEST_TIMEOUT,
        max_retries=settings.LLM_MAX_RETRIES,
        max_tokens=settings.LLM_MAX_TOKENS,
    )


def _get_embedder():
    """Build the embedding provider from settings. Raises HTTP 503 if not configured."""
    settings = get_settings()
    if not settings.LLM_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Embedding provider not configured. Set LLM_API_KEY in environment.",
        )
    from backend.app.ai.embeddings.provider import build_embedding_provider
    return build_embedding_provider(
        provider=settings.EMBEDDING_PROVIDER,
        api_key=settings.LLM_API_KEY,
        model=settings.EMBEDDING_MODEL,
    )


def _resolve_merchant(db: Session, merchant_id: uuid.UUID | None) -> uuid.UUID:
    """Return a valid merchant UUID or raise HTTP 404."""
    if merchant_id is not None:
        return merchant_id
    from backend.app.repositories.merchant import MerchantRepository
    merchants = MerchantRepository(db).list_all(limit=1)
    if not merchants:
        raise HTTPException(
            status_code=404,
            detail="No merchants found. Run: python -m backend.app.data.seed",
        )
    return merchants[0].id


# ─────────────────────────────────────────────────────────────────────────────
# /analyze endpoint
# ─────────────────────────────────────────────────────────────────────────────

def _state_to_response(state, merchant_id: uuid.UUID) -> AnalysisResponse:
    """Convert AgentState to the public AnalysisResponse schema."""
    insights = []
    for raw in state.insights:
        try:
            insights.append(AnalysisInsight(**raw))
        except Exception:
            pass  # skip malformed insights — never crash the response

    tool_calls = [
        AnalysisToolCallSummary(
            step=tc["step"],
            tool=tc["tool"],
            result_summary=tc["result_summary"],
            items_retrieved=tc["items_retrieved"],
        )
        for tc in state.to_api_response().get("tool_calls", [])
    ]

    return AnalysisResponse(
        analysis_id=state.run_id,
        status=state.status,
        goal=state.goal,
        merchant_id=str(merchant_id),
        insights=insights,
        retrieval_steps=state.retrieval_steps_used,
        tool_calls=tool_calls,
        evidence_summary=state.evidence_summary,
        insufficient_evidence=state.insufficient_evidence,
        error=state.error,
    )


@router.post("/analyze", response_model=AnalysisResponse)
def analyze(
    request: AnalyzeRequest,
    db: Session = Depends(get_db),
) -> AnalysisResponse:
    """
    Run an agentic growth analysis for a merchant.

    The agent:
      1. Selects appropriate retrieval tools (max 3 steps)
      2. Retrieves evidence from the production knowledge store
      3. Synthesises structured, evidence-grounded growth insights
      4. Applies guardrails (every insight starts as pending_approval)
      5. Records an audit trail
      6. Returns a deterministic AnalysisResponse

    Returns:
      200 — analysis completed (or insufficient evidence)
      404 — merchant not found
      503 — LLM/embedding provider not configured
    """
    merchant_id = _resolve_merchant(db, request.merchant_id)
    llm = _get_llm()
    embedder = _get_embedder()

    svc = AIAnalysisService(db=db, llm=llm, embedding_provider=embedder)
    state = svc.analyse(goal=request.goal, merchant_id=merchant_id)

    try:
        db.commit()
    except Exception as exc:
        log.warning("Failed to commit audit events: %s", exc)
        db.rollback()

    return _state_to_response(state, merchant_id)


# ─────────────────────────────────────────────────────────────────────────────
# /ingest endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/ingest", response_model=IngestResponse)
def ingest(
    request: IngestRequest,
    db: Session = Depends(get_db),
) -> IngestResponse:
    """
    Ingest production commerce data into the knowledge store.

    Reads real records from Phase 2 production tables:
      merchants · products · customers · orders · payments

    Converts each record into a knowledge document + pgvector embedding.
    Idempotent: unchanged records are skipped via SHA-256 checksum.

    Returns:
      200 — ingestion completed
      404 — merchant not found
      503 — embedding provider not configured
    """
    merchant_id = _resolve_merchant(db, request.merchant_id)
    embedder = _get_embedder()

    connector = ProductionDataConnector(db=db, embedding_provider=embedder)
    response = connector.ingest(merchant_id, force_reingest=request.force_reingest)

    if response.status == "failed":
        status_code = 404 if "not found" in response.message.lower() else 500
        raise HTTPException(status_code=status_code, detail=response.message)

    try:
        db.commit()
    except Exception as exc:
        log.warning("Failed to commit ingestion: %s", exc)
        db.rollback()
        raise HTTPException(status_code=500, detail="Ingestion commit failed.")

    return response
