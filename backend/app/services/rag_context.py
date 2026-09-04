"""Build tenant-scoped, evidence-grounded context for downstream agents."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from backend.app.ai.embeddings.base import BaseEmbeddingProvider
from backend.app.ai.rag.context import RetrievedItem
from backend.app.ai.rag.retriever import KnowledgeRetriever
from backend.app.services.radar import GrowthRadarService


class RAGContextService:
    """Combines verified radar facts with existing knowledge retrieval."""

    def __init__(
        self, db: Session, embedding_provider: BaseEmbeddingProvider | None = None
    ) -> None:
        self.db = db
        self.embedding_provider = embedding_provider

    def build(
        self, merchant_id: uuid.UUID, query: str, *, window_days: int = 30
    ) -> dict[str, Any]:
        radar = GrowthRadarService(self.db).build_real_data_radar(
            merchant_id, window_days=window_days
        )
        metrics = radar["metrics"]
        verified_facts = [
            {"fact": "captured_revenue", "value": metrics["captured_revenue"], "verified": True, "source": "payments"},
            {"fact": "captured_transactions", "value": metrics["captured_transactions"], "verified": True, "source": "payments"},
            {"fact": "successful_payments", "value": metrics["successful_payments"], "verified": True, "source": "payments"},
            {"fact": "failed_payments", "value": metrics["failed_payments"], "verified": True, "source": "payments"},
            {"fact": "total_customers", "value": metrics["total_customers"], "verified": True, "source": "customers"},
            {"fact": "total_orders", "value": metrics["total_orders"], "verified": True, "source": "orders"},
        ]
        radar_item = RetrievedItem(
            content=(
                f"Captured revenue INR {metrics['captured_revenue']:.2f}; "
                f"captured transactions {metrics['captured_transactions']}; "
                f"customers {metrics['total_customers']}; orders {metrics['total_orders']}."
            ),
            source_type="growth_radar",
            source_id=str(merchant_id),
            document_id=str(merchant_id),
            chunk_id=f"radar-{window_days}",
            similarity=None,
            metadata={"verified": True, "window_days": window_days, "signals": radar["signals"]},
        )
        context_items = [radar_item]

        # Knowledge retrieval is optional here; absence of an embedding provider
        # must not block the verified database context used by downstream agents.
        if self.embedding_provider is not None:
            context = KnowledgeRetriever(self.db, self.embedding_provider).retrieve(
                query, merchant_id, limit=5
            )
            context_items.extend(
                RetrievedItem(
                    content=item.content,
                    source_type=item.source_type,
                    source_id=item.source_id,
                    document_id=item.document_id,
                    chunk_id=item.chunk_id,
                    similarity=item.similarity,
                    metadata={**item.metadata, "verified": True, "source": "knowledge_store"},
                )
                for item in context.items
            )

        sufficient = radar["data_sufficiency"]["status"] == "sufficient"
        return {
            "merchant_id": str(merchant_id),
            "query": query,
            "status": "ready" if sufficient else "insufficient_data",
            "data_sufficiency": radar["data_sufficiency"],
            "verified_facts": verified_facts,
            "derived_metrics": {"average_order_value": metrics["average_order_value"], "signals": radar["signals"]},
            "retrieved_context": [item.to_evidence_dict() for item in context_items],
            "inference_allowed": sufficient,
        }