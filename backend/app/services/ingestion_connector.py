"""
ProductionDataConnector — Task 23/24.

Bridges the existing production commerce database (merchants, products,
customers, orders, payments) to the Phase 3 knowledge-ingestion pipeline.

This connector is the *only* production-data entry point for Phase 3.

Design:
- Reads exclusively from the five existing Phase 2 production tables via
  the existing repositories. No new data sources are introduced.
- Delegates all embedding / document upsert logic to KnowledgeIngestionService.
- Validates merchant existence before starting work.
- Validates embedding dimension matches the configured dimension.
- Writes audit events for ingestion lifecycle.
- Returns structured counts so callers know what was ingested.
- Caller is responsible for commit(); this service only flushes.
- API keys are never logged.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.app.ai.embeddings.base import BaseEmbeddingProvider
from backend.app.core.config import get_settings
from backend.app.models.enums import ActorType, AuditEventType
from backend.app.repositories.merchant import MerchantRepository
from backend.app.schemas.ingestion import IngestionSourceCounts, IngestResponse
from backend.app.services.knowledge_service import KnowledgeIngestionService

log = logging.getLogger(__name__)


def _write_audit(
    db: Session,
    merchant_id: uuid.UUID,
    event_type: AuditEventType,
    payload: dict,
) -> None:
    """Write an ingestion audit event. Never raises."""
    try:
        from backend.app.models.audit_event import AuditEvent
        evt = AuditEvent(
            merchant_id=merchant_id,
            actor_type=ActorType.system,
            actor_id="ingestion_connector",
            event_type=event_type,
            entity_type="knowledge_ingestion",
            entity_id=str(merchant_id),
            payload=payload,
        )
        db.add(evt)
        db.flush()
    except Exception as exc:
        log.warning("Failed to write ingestion audit event %s: %s", event_type, exc)


class ProductionDataConnector:
    """
    Reads production commerce records and feeds them into the knowledge store.

    Production tables consumed (read-only):
      - merchants          (via MerchantRepository)
      - products           (via ProductRepository)
      - customers          (via CustomerRepository)
      - orders + items     (via OrderRepository with selectinload)
      - payments           (via PaymentRepository)

    Writes:
      - knowledge_documents   (upsert, idempotent by checksum)
      - knowledge_chunks      (rebuilt only when content changes)
      - audit_events          (ingestion lifecycle)
    """

    def __init__(
        self,
        db: Session,
        embedding_provider: BaseEmbeddingProvider,
    ) -> None:
        self._db = db
        self._embedder = embedding_provider
        self._merchant_repo = MerchantRepository(db)

    def ingest(
        self,
        merchant_id: uuid.UUID,
        *,
        force_reingest: bool = False,
    ) -> IngestResponse:
        """
        Run full knowledge ingestion for one merchant.

        Validates:
        - merchant exists
        - embedding dimension matches configured EMBEDDING_DIMENSIONS

        Returns IngestResponse. Caller must call db.commit().
        """
        merchant = self._merchant_repo.get_by_id(merchant_id)
        if not merchant:
            log.error("Ingestion aborted: merchant %s not found.", merchant_id)
            return IngestResponse(
                status="failed",
                merchant_id=merchant_id,
                merchant_name="unknown",
                documents_processed=IngestionSourceCounts(
                    merchant=0, product=0, customer=0, order=0, payment=0
                ),
                message=f"Merchant {merchant_id} not found in database.",
                completed_at=datetime.now(timezone.utc),
            )

        # Validate embedding dimensions match configuration
        settings = get_settings()
        if self._embedder.dimensions != settings.EMBEDDING_DIMENSIONS:
            msg = (
                f"Embedding dimension mismatch: provider returns {self._embedder.dimensions} "
                f"but EMBEDDING_DIMENSIONS={settings.EMBEDDING_DIMENSIONS}. "
                f"Ingestion aborted to prevent corrupt vector store."
            )
            log.error(msg)
            return IngestResponse(
                status="failed",
                merchant_id=merchant_id,
                merchant_name=merchant.name,
                documents_processed=IngestionSourceCounts(
                    merchant=0, product=0, customer=0, order=0, payment=0
                ),
                message=msg,
                completed_at=datetime.now(timezone.utc),
            )

        log.info(
            "Production data ingestion started. merchant=%s (%s) force_reingest=%s dims=%d",
            merchant_id, merchant.name, force_reingest, self._embedder.dimensions,
        )

        _write_audit(self._db, merchant_id, AuditEventType.ingestion_started, {
            "force_reingest": force_reingest,
            "embedding_model": settings.EMBEDDING_MODEL,
            "embedding_dimensions": settings.EMBEDDING_DIMENSIONS,
        })

        if force_reingest:
            self._purge_existing_knowledge(merchant_id)

        ingestion_svc = KnowledgeIngestionService(
            db=self._db,
            embedding_provider=self._embedder,
        )

        try:
            counts = ingestion_svc.ingest_merchant(merchant_id)
        except Exception as exc:
            log.exception(
                "Ingestion failed for merchant %s: %s",
                merchant_id, type(exc).__name__,
            )
            _write_audit(self._db, merchant_id, AuditEventType.ingestion_failed, {
                "error": type(exc).__name__,
                "detail": str(exc)[:500],
            })
            return IngestResponse(
                status="failed",
                merchant_id=merchant_id,
                merchant_name=merchant.name,
                documents_processed=IngestionSourceCounts(
                    merchant=0, product=0, customer=0, order=0, payment=0
                ),
                message=f"Ingestion failed: {type(exc).__name__}",
                completed_at=datetime.now(timezone.utc),
            )

        source_counts = IngestionSourceCounts(
            merchant=counts.get("merchant", 0),
            product=counts.get("product", 0),
            customer=counts.get("customer", 0),
            order=counts.get("order", 0),
            payment=counts.get("payment", 0),
        )
        total = source_counts.total

        _write_audit(self._db, merchant_id, AuditEventType.ingestion_completed, {
            "total_documents": total,
            "by_type": {
                "merchant": source_counts.merchant,
                "product": source_counts.product,
                "customer": source_counts.customer,
                "order": source_counts.order,
                "payment": source_counts.payment,
            },
        })

        log.info(
            "Ingestion complete. merchant=%s name=%r total=%d "
            "product=%d customer=%d order=%d payment=%d",
            merchant_id, merchant.name, total,
            source_counts.product, source_counts.customer,
            source_counts.order, source_counts.payment,
        )

        return IngestResponse(
            status="completed",
            merchant_id=merchant_id,
            merchant_name=merchant.name,
            documents_processed=source_counts,
            message=(
                f"Successfully ingested {total} documents "
                f"({source_counts.product} products, "
                f"{source_counts.customer} customers, "
                f"{source_counts.order} orders, "
                f"{source_counts.payment} payments)."
            ),
            completed_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _purge_existing_knowledge(self, merchant_id: uuid.UUID) -> None:
        """
        Delete existing knowledge documents for the merchant.

        Used only for force_reingest=True. Does NOT touch commerce data.
        """
        from sqlalchemy import delete
        from backend.app.models.knowledge import KnowledgeDocument

        result = self._db.execute(
            delete(KnowledgeDocument).where(
                KnowledgeDocument.merchant_id == merchant_id
            )
        )
        self._db.flush()
        log.info(
            "Force reingest: purged %d knowledge documents for merchant %s.",
            result.rowcount, merchant_id,
        )
