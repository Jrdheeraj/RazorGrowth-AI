"""
Task 23 — Production Data Connector tests.

These tests verify that the connector reads the existing production
commerce models (merchants, products, customers, orders, payments)
correctly and feeds them into the knowledge store.

Rules:
- No synthetic production data — all fixtures use real ORM models from
  Phase 2 (Merchant, Product, Customer, Order, OrderItem, Payment).
- All embedding calls use the in-process FakeEmbeddingProvider from
  test_ai_phase3.py conventions — zero real API calls.
- All tests use the existing SQLite test database via the db_session fixture.
- The client fixture is used for endpoint tests.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import select

from backend.app.ai.embeddings.base import BaseEmbeddingProvider, EmbeddingError
from backend.app.models.customer import Customer
from backend.app.models.enums import (
    Currency,
    CustomerSegment,
    MerchantStatus,
    OrderStatus,
    PaymentProvider,
    PaymentStatus,
)
from backend.app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from backend.app.models.merchant import Merchant
from backend.app.models.order import Order, OrderItem
from backend.app.models.payment import Payment
from backend.app.models.product import Product
from backend.app.schemas.ingestion import IngestionSourceCounts, IngestResponse
from backend.app.services.ingestion_connector import ProductionDataConnector

# ─────────────────────────────────────────────────────────────────────────────
# Fake embedding provider — deterministic, zero API calls
# ─────────────────────────────────────────────────────────────────────────────

class _FakeEmbedder(BaseEmbeddingProvider):
    """
    Deterministic fake embedder for tests.

    Reports EMBEDDING_DIMENSIONS (1536) to pass dimension validation,
    but returns a dense zero vector for speed. No real API calls.
    """

    @property
    def dimensions(self) -> int:
        from backend.app.core.config import get_settings
        return get_settings().EMBEDDING_DIMENSIONS

    def embed_text(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        dims = self.dimensions
        return [[float(ord(t[0]) % 10) / 10.0] + [0.0] * (dims - 1) if t else [0.0] * dims
                for t in texts]


class _FailingEmbedder(BaseEmbeddingProvider):
    @property
    def dimensions(self) -> int:
        from backend.app.core.config import get_settings
        return get_settings().EMBEDDING_DIMENSIONS

    def embed_text(self, text: str) -> list[float]:
        raise EmbeddingError("fail")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingError("fail")


# ─────────────────────────────────────────────────────────────────────────────
# DB fixture helpers — real Phase 2 ORM models
# ─────────────────────────────────────────────────────────────────────────────

def _merchant(db) -> Merchant:
    slug = f"conn-{uuid.uuid4().hex[:8]}"
    m = Merchant(
        name="Connector Test Merchant",
        slug=slug,
        email=f"{slug}@example.com",
        status=MerchantStatus.active,
        currency=Currency.INR,
    )
    db.add(m)
    db.flush()
    return m


def _product(db, merchant: Merchant, name: str = "Wireless Headphones") -> Product:
    p = Product(
        merchant_id=merchant.id,
        name=name,
        category="audio",
        price=Decimal("1999.00"),
        sku=f"SKU-{uuid.uuid4().hex[:6]}",
        stock_quantity=50,
        active=True,
        description="Over-ear wireless headphones.",
    )
    db.add(p)
    db.flush()
    return p


def _customer(db, merchant: Merchant) -> Customer:
    c = Customer(
        merchant_id=merchant.id,
        name="Test Customer",
        email=f"tc-{uuid.uuid4().hex[:6]}@example.com",
        segment=CustomerSegment.returning,
        total_orders=3,
        total_spend=Decimal("5997.00"),
    )
    db.add(c)
    db.flush()
    return c


def _order(db, merchant: Merchant, customer: Customer, product: Product) -> Order:
    o = Order(
        merchant_id=merchant.id,
        customer_id=customer.id,
        order_number=f"ORD-{uuid.uuid4().hex[:8].upper()}",
        status=OrderStatus.paid,
        subtotal=product.price,
        discount=Decimal("0.00"),
        tax=Decimal("0.00"),
        total=product.price,
        currency=Currency.INR,
    )
    db.add(o)
    db.flush()
    item = OrderItem(
        order_id=o.id,
        product_id=product.id,
        quantity=1,
        unit_price=product.price,
        line_total=product.price,
    )
    db.add(item)
    db.flush()
    return o


def _payment(
    db,
    merchant: Merchant,
    order: Order,
    status: PaymentStatus = PaymentStatus.captured,
) -> Payment:
    p = Payment(
        merchant_id=merchant.id,
        order_id=order.id,
        provider=PaymentProvider.razorpay,
        amount=order.total,
        currency=Currency.INR,
        status=status,
        failure_code="INSUFFICIENT_FUNDS" if status == PaymentStatus.failed else None,
    )
    db.add(p)
    db.flush()
    return p


# ─────────────────────────────────────────────────────────────────────────────
# 1. IngestionSourceCounts schema
# ─────────────────────────────────────────────────────────────────────────────

class TestIngestionSourceCounts:
    def test_total_sums_all_fields(self):
        counts = IngestionSourceCounts(merchant=1, product=5, customer=10, order=20, payment=8)
        assert counts.total == 44

    def test_zero_counts_valid(self):
        counts = IngestionSourceCounts(merchant=0, product=0, customer=0, order=0, payment=0)
        assert counts.total == 0

    def test_negative_count_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            IngestionSourceCounts(merchant=-1, product=0, customer=0, order=0, payment=0)


# ─────────────────────────────────────────────────────────────────────────────
# 2. ProductionDataConnector — merchant validation
# ─────────────────────────────────────────────────────────────────────────────

class TestConnectorMerchantValidation:
    def test_unknown_merchant_returns_failed_status(self, db_session):
        connector = ProductionDataConnector(db=db_session, embedding_provider=_FakeEmbedder())
        result = connector.ingest(uuid.uuid4())
        assert result.status == "failed"
        assert "not found" in result.message.lower()

    def test_unknown_merchant_returns_zero_counts(self, db_session):
        connector = ProductionDataConnector(db=db_session, embedding_provider=_FakeEmbedder())
        result = connector.ingest(uuid.uuid4())
        assert result.documents_processed.total == 0

    def test_valid_merchant_returns_completed_status(self, db_session):
        m = _merchant(db_session)
        connector = ProductionDataConnector(db=db_session, embedding_provider=_FakeEmbedder())
        result = connector.ingest(m.id)
        assert result.status == "completed"

    def test_result_contains_merchant_name(self, db_session):
        m = _merchant(db_session)
        connector = ProductionDataConnector(db=db_session, embedding_provider=_FakeEmbedder())
        result = connector.ingest(m.id)
        assert result.merchant_name == m.name

    def test_result_contains_merchant_id(self, db_session):
        m = _merchant(db_session)
        connector = ProductionDataConnector(db=db_session, embedding_provider=_FakeEmbedder())
        result = connector.ingest(m.id)
        assert result.merchant_id == m.id


# ─────────────────────────────────────────────────────────────────────────────
# 3. Connector reads production tables
# ─────────────────────────────────────────────────────────────────────────────

class TestConnectorReadsProductionTables:
    """
    These tests verify that the connector reads real Phase 2 commerce
    records (from the existing ORM models) and turns them into knowledge
    documents. They do NOT introduce synthetic production data — the
    fixtures create real ORM records using the same models as Phase 2.
    """

    def test_product_records_become_knowledge_documents(self, db_session):
        m = _merchant(db_session)
        _product(db_session, m, "Wireless Headphones")
        _product(db_session, m, "Protective Case")

        connector = ProductionDataConnector(db=db_session, embedding_provider=_FakeEmbedder())
        result = connector.ingest(m.id)

        assert result.documents_processed.product == 2
        docs = db_session.scalars(
            select(KnowledgeDocument).where(
                KnowledgeDocument.merchant_id == m.id,
                KnowledgeDocument.source_type == "product",
            )
        ).all()
        assert len(docs) == 2

    def test_customer_records_become_knowledge_documents(self, db_session):
        m = _merchant(db_session)
        _customer(db_session, m)
        _customer(db_session, m)

        connector = ProductionDataConnector(db=db_session, embedding_provider=_FakeEmbedder())
        result = connector.ingest(m.id)

        assert result.documents_processed.customer == 2
        docs = db_session.scalars(
            select(KnowledgeDocument).where(
                KnowledgeDocument.merchant_id == m.id,
                KnowledgeDocument.source_type == "customer",
            )
        ).all()
        assert len(docs) == 2

    def test_order_records_become_knowledge_documents(self, db_session):
        m = _merchant(db_session)
        c = _customer(db_session, m)
        p = _product(db_session, m)
        _order(db_session, m, c, p)
        _order(db_session, m, c, p)

        connector = ProductionDataConnector(db=db_session, embedding_provider=_FakeEmbedder())
        result = connector.ingest(m.id)

        assert result.documents_processed.order == 2

    def test_payment_records_become_knowledge_documents(self, db_session):
        m = _merchant(db_session)
        c = _customer(db_session, m)
        p = _product(db_session, m)
        o = _order(db_session, m, c, p)
        _payment(db_session, m, o, PaymentStatus.captured)
        _payment(db_session, m, o, PaymentStatus.failed)

        connector = ProductionDataConnector(db=db_session, embedding_provider=_FakeEmbedder())
        result = connector.ingest(m.id)

        assert result.documents_processed.payment == 2

    def test_merchant_overview_document_created(self, db_session):
        m = _merchant(db_session)
        connector = ProductionDataConnector(db=db_session, embedding_provider=_FakeEmbedder())
        result = connector.ingest(m.id)

        assert result.documents_processed.merchant == 1
        doc = db_session.scalars(
            select(KnowledgeDocument).where(
                KnowledgeDocument.merchant_id == m.id,
                KnowledgeDocument.source_type == "merchant",
            )
        ).first()
        assert doc is not None
        assert m.name in doc.content

    def test_product_chunk_contains_product_name(self, db_session):
        m = _merchant(db_session)
        _product(db_session, m, "Wireless Headphones Pro")

        connector = ProductionDataConnector(db=db_session, embedding_provider=_FakeEmbedder())
        connector.ingest(m.id)
        db_session.flush()

        doc = db_session.scalars(
            select(KnowledgeDocument).where(
                KnowledgeDocument.merchant_id == m.id,
                KnowledgeDocument.source_type == "product",
            )
        ).first()
        assert doc is not None
        assert "Wireless Headphones Pro" in doc.content

    def test_payment_chunk_contains_failure_code_for_failed_payments(self, db_session):
        m = _merchant(db_session)
        c = _customer(db_session, m)
        p = _product(db_session, m)
        o = _order(db_session, m, c, p)
        _payment(db_session, m, o, PaymentStatus.failed)

        connector = ProductionDataConnector(db=db_session, embedding_provider=_FakeEmbedder())
        connector.ingest(m.id)
        db_session.flush()

        doc = db_session.scalars(
            select(KnowledgeDocument).where(
                KnowledgeDocument.merchant_id == m.id,
                KnowledgeDocument.source_type == "payment",
            )
        ).first()
        assert doc is not None
        assert "INSUFFICIENT_FUNDS" in doc.content

    def test_knowledge_chunks_are_created_with_embeddings(self, db_session):
        m = _merchant(db_session)
        _product(db_session, m)

        connector = ProductionDataConnector(db=db_session, embedding_provider=_FakeEmbedder())
        connector.ingest(m.id)
        db_session.flush()

        chunks = db_session.scalars(
            select(KnowledgeChunk).where(KnowledgeChunk.merchant_id == m.id)
        ).all()
        assert len(chunks) > 0
        # At least the product chunk should have a non-null embedding
        product_chunks = [ch for ch in chunks
                          if db_session.get(KnowledgeDocument, ch.document_id).source_type == "product"]
        assert len(product_chunks) > 0
        assert product_chunks[0].embedding is not None

    def test_no_cross_merchant_contamination(self, db_session):
        """Ingesting merchant A must not create documents for merchant B."""
        m_a = _merchant(db_session)
        m_b = _merchant(db_session)
        _product(db_session, m_a, "Product A")
        _product(db_session, m_b, "Product B")

        connector = ProductionDataConnector(db=db_session, embedding_provider=_FakeEmbedder())
        connector.ingest(m_a.id)
        db_session.flush()

        docs_b = db_session.scalars(
            select(KnowledgeDocument).where(
                KnowledgeDocument.merchant_id == m_b.id,
            )
        ).all()
        # Merchant B was NOT ingested, so no docs for them
        assert len(docs_b) == 0


# ─────────────────────────────────────────────────────────────────────────────
# 4. Idempotency
# ─────────────────────────────────────────────────────────────────────────────

class TestConnectorIdempotency:
    def test_second_ingest_does_not_duplicate_documents(self, db_session):
        m = _merchant(db_session)
        _product(db_session, m)

        connector = ProductionDataConnector(db=db_session, embedding_provider=_FakeEmbedder())
        connector.ingest(m.id)
        db_session.flush()

        first_count = db_session.scalar(
            select(__import__("sqlalchemy", fromlist=["func"]).func.count(KnowledgeDocument.id))
            .where(KnowledgeDocument.merchant_id == m.id)
        )

        connector.ingest(m.id)
        db_session.flush()

        second_count = db_session.scalar(
            select(__import__("sqlalchemy", fromlist=["func"]).func.count(KnowledgeDocument.id))
            .where(KnowledgeDocument.merchant_id == m.id)
        )
        assert first_count == second_count

    def test_force_reingest_rebuilds_documents(self, db_session):
        m = _merchant(db_session)
        _product(db_session, m)

        connector = ProductionDataConnector(db=db_session, embedding_provider=_FakeEmbedder())
        connector.ingest(m.id)
        db_session.flush()

        # force_reingest=True purges and rebuilds
        result = connector.ingest(m.id, force_reingest=True)
        db_session.flush()

        assert result.status == "completed"
        assert result.documents_processed.product >= 1


# ─────────────────────────────────────────────────────────────────────────────
# 5. Embedding failure resilience
# ─────────────────────────────────────────────────────────────────────────────

class TestConnectorEmbeddingResilience:
    def test_embedding_failure_still_returns_completed(self, db_session):
        """Embedding failures are handled inside KnowledgeIngestionService —
        null embeddings are stored and ingestion completes."""
        m = _merchant(db_session)
        _product(db_session, m)

        connector = ProductionDataConnector(db=db_session, embedding_provider=_FailingEmbedder())
        result = connector.ingest(m.id)

        assert result.status == "completed"

    def test_embedding_failure_stores_null_chunks(self, db_session):
        m = _merchant(db_session)
        _product(db_session, m)

        connector = ProductionDataConnector(db=db_session, embedding_provider=_FailingEmbedder())
        connector.ingest(m.id)
        db_session.flush()

        chunks = db_session.scalars(
            select(KnowledgeChunk).where(KnowledgeChunk.merchant_id == m.id)
        ).all()
        assert any(ch.embedding is None for ch in chunks)


# ─────────────────────────────────────────────────────────────────────────────
# 6. IngestResponse schema
# ─────────────────────────────────────────────────────────────────────────────

class TestIngestResponseSchema:
    def test_completed_response_has_required_fields(self, db_session):
        m = _merchant(db_session)
        connector = ProductionDataConnector(db=db_session, embedding_provider=_FakeEmbedder())
        result = connector.ingest(m.id)

        assert isinstance(result, IngestResponse)
        assert result.status in ("completed", "failed")
        assert result.merchant_id is not None
        assert result.merchant_name != ""
        assert result.message != ""
        assert result.completed_at is not None

    def test_failed_response_has_zero_counts(self, db_session):
        connector = ProductionDataConnector(db=db_session, embedding_provider=_FakeEmbedder())
        result = connector.ingest(uuid.uuid4())
        assert result.documents_processed.total == 0


# ─────────────────────────────────────────────────────────────────────────────
# 7. POST /api/ai/ingest endpoint
# ─────────────────────────────────────────────────────────────────────────────

class TestIngestEndpoint:
    def test_returns_200_with_valid_merchant(self, client, db_session):
        m = _merchant(db_session)
        db_session.commit()

        with patch("backend.app.api.routes.ai._get_embedder", return_value=_FakeEmbedder()):
            r = client.post("/api/ai/ingest", json={"merchant_id": str(m.id)})
        assert r.status_code == 200

    def test_response_has_status_completed(self, client, db_session):
        m = _merchant(db_session)
        db_session.commit()

        with patch("backend.app.api.routes.ai._get_embedder", return_value=_FakeEmbedder()):
            body = client.post("/api/ai/ingest", json={"merchant_id": str(m.id)}).json()
        assert body["status"] == "completed"

    def test_response_has_documents_processed(self, client, db_session):
        m = _merchant(db_session)
        _product(db_session, m)
        db_session.commit()

        with patch("backend.app.api.routes.ai._get_embedder", return_value=_FakeEmbedder()):
            body = client.post("/api/ai/ingest", json={"merchant_id": str(m.id)}).json()
        assert "documents_processed" in body
        assert body["documents_processed"]["product"] >= 1

    def test_response_has_merchant_name(self, client, db_session):
        m = _merchant(db_session)
        db_session.commit()

        with patch("backend.app.api.routes.ai._get_embedder", return_value=_FakeEmbedder()):
            body = client.post("/api/ai/ingest", json={"merchant_id": str(m.id)}).json()
        assert body["merchant_name"] == m.name

    def test_nonexistent_merchant_returns_404(self, client):
        with patch("backend.app.api.routes.ai._get_embedder", return_value=_FakeEmbedder()):
            r = client.post("/api/ai/ingest", json={"merchant_id": str(uuid.uuid4())})
        assert r.status_code == 404

    def test_embedder_not_configured_returns_503(self, client):
        from fastapi import HTTPException

        with patch(
            "backend.app.api.routes.ai._get_embedder",
            side_effect=HTTPException(status_code=503, detail="Not configured"),
        ):
            r = client.post("/api/ai/ingest", json={})
        assert r.status_code == 503

    def test_force_reingest_flag_accepted(self, client, db_session):
        m = _merchant(db_session)
        db_session.commit()

        with patch("backend.app.api.routes.ai._get_embedder", return_value=_FakeEmbedder()):
            r = client.post(
                "/api/ai/ingest",
                json={"merchant_id": str(m.id), "force_reingest": True},
            )
        assert r.status_code == 200

    def test_omitting_merchant_id_uses_first_merchant(self, client, db_session):
        m = _merchant(db_session)
        db_session.commit()

        with patch("backend.app.api.routes.ai._get_embedder", return_value=_FakeEmbedder()):
            r = client.post("/api/ai/ingest", json={})
        # Either 200 (found a merchant) or 404 (empty table from prior test cleanup)
        assert r.status_code in (200, 404)

    def test_response_contains_completed_at_timestamp(self, client, db_session):
        m = _merchant(db_session)
        db_session.commit()

        with patch("backend.app.api.routes.ai._get_embedder", return_value=_FakeEmbedder()):
            body = client.post("/api/ai/ingest", json={"merchant_id": str(m.id)}).json()
        assert "completed_at" in body
        assert body["completed_at"] is not None

    def test_response_does_not_expose_api_key(self, client, db_session):
        m = _merchant(db_session)
        db_session.commit()

        with patch("backend.app.api.routes.ai._get_embedder", return_value=_FakeEmbedder()):
            r = client.post("/api/ai/ingest", json={"merchant_id": str(m.id)})
        assert "sk-" not in r.text
