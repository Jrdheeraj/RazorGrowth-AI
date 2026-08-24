"""
KnowledgeIngestionService — converts merchant DB records into retrievable
knowledge documents with embeddings.

Pipeline per entity:
    DB record  →  text chunk  →  SHA-256 checksum  →  embedding  →  KnowledgeChunk

Idempotency:
    If a document's checksum matches the stored checksum, its chunks are
    skipped entirely. Only changed or new content is re-embedded.

This service is READ-ONLY against commerce tables. It only writes to the
knowledge_documents and knowledge_chunks tables.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ai.embeddings.base import BaseEmbeddingProvider, EmbeddingError
from backend.app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from backend.app.repositories.customer import CustomerRepository
from backend.app.repositories.merchant import MerchantRepository
from backend.app.repositories.order import OrderRepository
from backend.app.repositories.payment import PaymentRepository
from backend.app.repositories.product import ProductRepository

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Chunking helpers
# ─────────────────────────────────────────────────────────────────────────────

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _chunk_product(product: Any) -> tuple[str, str, dict]:
    """Convert a Product ORM object to a knowledge text chunk."""
    lines = [
        f"Product: {product.name}",
        f"Category: {product.category}",
        f"Price: {product.currency} {product.price}",
        f"Stock: {product.stock_quantity} units",
        f"SKU: {product.sku or 'N/A'}",
        f"Active: {'Yes' if product.active else 'No'}",
    ]
    if product.description:
        lines.append(f"Description: {product.description}")
    content = "\n".join(lines)
    title = f"Product: {product.name}"
    metadata = {
        "entity_type": "product",
        "entity_id": str(product.id),
        "category": product.category,
        "price": float(product.price),
        "source": "merchant_catalog",
    }
    return title, content, metadata


def _chunk_customer(customer: Any) -> tuple[str, str, dict]:
    """Convert a Customer ORM object to a knowledge text chunk."""
    lines = [
        f"Customer segment: {customer.segment}",
        f"Total orders: {customer.total_orders}",
        f"Total spend: INR {customer.total_spend}",
    ]
    content = "\n".join(lines)
    title = f"Customer: {customer.segment.value if hasattr(customer.segment, 'value') else customer.segment} segment, {customer.total_orders} orders"
    metadata = {
        "entity_type": "customer",
        "entity_id": str(customer.id),
        "segment": str(customer.segment.value if hasattr(customer.segment, "value") else customer.segment),
        "total_orders": customer.total_orders,
        "total_spend": float(customer.total_spend),
        "source": "customer_records",
    }
    return title, content, metadata


def _chunk_order(order: Any, product_names: dict[str, str]) -> tuple[str, str, dict]:
    """Convert an Order ORM object to a knowledge text chunk."""
    item_descriptions = []
    for item in getattr(order, "items", []):
        name = product_names.get(str(item.product_id), "Unknown product")
        item_descriptions.append(f"  - {name} × {item.quantity} @ INR {item.unit_price}")

    lines = [
        f"Order: {order.order_number}",
        f"Status: {order.status.value if hasattr(order.status, 'value') else order.status}",
        f"Order total: INR {order.total}",
        f"Date: {order.created_at.strftime('%Y-%m-%d') if order.created_at else 'unknown'}",
    ]
    if item_descriptions:
        lines.append("Items:")
        lines.extend(item_descriptions)
    content = "\n".join(lines)
    title = f"Order {order.order_number}: INR {order.total}"
    metadata = {
        "entity_type": "order",
        "entity_id": str(order.id),
        "customer_id": str(order.customer_id),
        "status": str(order.status.value if hasattr(order.status, "value") else order.status),
        "total": float(order.total),
        "product_ids": [str(item.product_id) for item in getattr(order, "items", [])],
        "source": "order_history",
    }
    return title, content, metadata


def _chunk_payment(payment: Any) -> tuple[str, str, dict]:
    """Convert a Payment ORM object to a knowledge text chunk."""
    status = payment.status.value if hasattr(payment.status, "value") else str(payment.status)
    lines = [
        f"Payment status: {status}",
        f"Amount: INR {payment.amount}",
        f"Provider: {payment.provider.value if hasattr(payment.provider, 'value') else payment.provider}",
    ]
    if payment.failure_code:
        lines.append(f"Failure code: {payment.failure_code}")
    if payment.failure_reason:
        lines.append(f"Failure reason: {payment.failure_reason}")
    content = "\n".join(lines)
    title = f"Payment {status.upper()}: INR {payment.amount}"
    metadata = {
        "entity_type": "payment",
        "entity_id": str(payment.id),
        "order_id": str(payment.order_id),
        "status": status,
        "amount": float(payment.amount),
        "failure_code": payment.failure_code,
        "source": "payment_records",
    }
    return title, content, metadata


def _chunk_merchant(merchant: Any, stats: dict) -> tuple[str, str, dict]:
    """Convert a Merchant + stats dict to a knowledge text chunk."""
    lines = [
        f"Merchant: {merchant.name}",
        f"Currency: {merchant.currency.value if hasattr(merchant.currency, 'value') else merchant.currency}",
        f"Status: {merchant.status.value if hasattr(merchant.status, 'value') else merchant.status}",
        f"Total products: {stats.get('product_count', 0)}",
        f"Total customers: {stats.get('customer_count', 0)}",
        f"Total orders: {stats.get('order_count', 0)}",
        f"Total revenue: INR {stats.get('total_revenue', 0)}",
        f"Failed payments: {stats.get('failed_payment_count', 0)}",
    ]
    content = "\n".join(lines)
    title = f"Merchant overview: {merchant.name}"
    metadata = {
        "entity_type": "merchant",
        "entity_id": str(merchant.id),
        "source": "merchant_overview",
        **stats,
    }
    return title, content, metadata


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────

class KnowledgeIngestionService:
    """
    Converts merchant commerce data into knowledge chunks with embeddings.

    Each source entity produces exactly one KnowledgeDocument. Chunks are
    rebuilt only when the document's content checksum changes.
    """

    def __init__(
        self,
        db: Session,
        embedding_provider: BaseEmbeddingProvider,
    ) -> None:
        self._db = db
        self._embedder = embedding_provider
        self._merchant_repo = MerchantRepository(db)
        self._product_repo = ProductRepository(db)
        self._customer_repo = CustomerRepository(db)
        self._order_repo = OrderRepository(db)
        self._payment_repo = PaymentRepository(db)

    # ------------------------------------------------------------------ #
    # Public
    # ------------------------------------------------------------------ #

    def ingest_merchant(self, merchant_id: uuid.UUID) -> dict[str, int]:
        """
        Ingest all knowledge for a merchant.

        Returns a dict of counts: {source_type: documents_processed}.
        Caller is responsible for commit().
        """
        counts: dict[str, int] = {}
        counts["merchant"] = self._ingest_merchant_overview(merchant_id)
        counts["product"] = self._ingest_products(merchant_id)
        counts["customer"] = self._ingest_customers(merchant_id)
        counts["order"] = self._ingest_orders(merchant_id)
        counts["payment"] = self._ingest_payments(merchant_id)
        log.info("Knowledge ingestion complete for merchant %s: %s", merchant_id, counts)
        return counts

    # ------------------------------------------------------------------ #
    # Private ingestion methods
    # ------------------------------------------------------------------ #

    def _upsert_document(
        self,
        merchant_id: uuid.UUID,
        source_type: str,
        source_id: str,
        title: str,
        content: str,
        metadata: dict,
    ) -> tuple[KnowledgeDocument, bool]:
        """
        Get-or-create a KnowledgeDocument.

        Returns (document, is_new_or_changed).
        If checksum matches existing document, returns (doc, False) — skip re-embedding.
        """
        checksum = _sha256(content)
        stmt = (
            select(KnowledgeDocument)
            .where(
                KnowledgeDocument.merchant_id == merchant_id,
                KnowledgeDocument.source_type == source_type,
                KnowledgeDocument.source_id == source_id,
            )
        )
        existing = self._db.scalars(stmt).first()
        if existing:
            if existing.checksum == checksum:
                return existing, False
            # Content changed — update
            existing.content = content
            existing.title = title
            existing.doc_metadata = metadata
            existing.checksum = checksum
            # Delete old chunks so they get rebuilt
            for chunk in list(existing.chunks):
                self._db.delete(chunk)
            self._db.flush()
            return existing, True

        doc = KnowledgeDocument(
            merchant_id=merchant_id,
            source_type=source_type,
            source_id=source_id,
            title=title,
            content=content,
            doc_metadata=metadata,
            checksum=checksum,
        )
        self._db.add(doc)
        self._db.flush()
        return doc, True

    def _create_chunk_with_embedding(
        self,
        doc: KnowledgeDocument,
        chunk_index: int,
        content: str,
        metadata: dict,
        embedding: list[float] | None,
    ) -> KnowledgeChunk:
        chunk = KnowledgeChunk(
            document_id=doc.id,
            merchant_id=doc.merchant_id,
            chunk_index=chunk_index,
            content=content,
            chunk_metadata=metadata,
            embedding=embedding,
        )
        self._db.add(chunk)
        return chunk

    def _embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        """Embed a batch of texts, returning None for failures."""
        if not texts:
            return []
        try:
            return self._embedder.embed_documents(texts)
        except EmbeddingError as exc:
            log.warning("Embedding batch failed, storing null embeddings: %s", exc)
            return [None] * len(texts)

    def _ingest_merchant_overview(self, merchant_id: uuid.UUID) -> int:
        merchant = self._merchant_repo.get_by_id(merchant_id)
        if not merchant:
            return 0

        # Compute stats via repositories
        from sqlalchemy import func
        from backend.app.models.order import Order
        from backend.app.models.payment import Payment
        from backend.app.models.enums import PaymentStatus

        product_count = len(self._product_repo.list_by_merchant(merchant_id, active_only=False, limit=10000))
        customer_count = len(self._customer_repo.list_by_merchant(merchant_id, limit=10000))

        order_result = self._db.execute(
            select(
                func.count(Order.id).label("cnt"),
                func.coalesce(func.sum(Order.total), 0).label("revenue"),
            ).where(Order.merchant_id == merchant_id)
        ).first()
        order_count = order_result.cnt if order_result else 0
        total_revenue = float(order_result.revenue) if order_result else 0.0

        failed_count = self._db.scalar(
            select(func.count(Payment.id)).where(
                Payment.merchant_id == merchant_id,
                Payment.status == PaymentStatus.failed,
            )
        ) or 0

        stats = {
            "product_count": product_count,
            "customer_count": customer_count,
            "order_count": order_count,
            "total_revenue": total_revenue,
            "failed_payment_count": failed_count,
        }

        title, content, metadata = _chunk_merchant(merchant, stats)
        doc, changed = self._upsert_document(
            merchant_id, "merchant", str(merchant_id), title, content, metadata
        )
        if changed:
            embeddings = self._embed_batch([content])
            self._create_chunk_with_embedding(doc, 0, content, metadata, embeddings[0] if embeddings else None)
            self._db.flush()
        return 1

    def _ingest_products(self, merchant_id: uuid.UUID) -> int:
        products = self._product_repo.list_by_merchant(merchant_id, active_only=False, limit=10000)
        to_embed: list[tuple[KnowledgeDocument, str, dict]] = []

        for product in products:
            title, content, metadata = _chunk_product(product)
            doc, changed = self._upsert_document(
                merchant_id, "product", str(product.id), title, content, metadata
            )
            if changed:
                to_embed.append((doc, content, metadata))

        if to_embed:
            texts = [t[1] for t in to_embed]
            embeddings = self._embed_batch(texts)
            for (doc, content, metadata), emb in zip(to_embed, embeddings):
                self._create_chunk_with_embedding(doc, 0, content, metadata, emb)
            self._db.flush()

        log.info("Products ingested: %d total, %d re-embedded", len(products), len(to_embed))
        return len(products)

    def _ingest_customers(self, merchant_id: uuid.UUID) -> int:
        customers = self._customer_repo.list_by_merchant(merchant_id, limit=10000)
        to_embed: list[tuple[KnowledgeDocument, str, dict]] = []

        for customer in customers:
            title, content, metadata = _chunk_customer(customer)
            doc, changed = self._upsert_document(
                merchant_id, "customer", str(customer.id), title, content, metadata
            )
            if changed:
                to_embed.append((doc, content, metadata))

        if to_embed:
            texts = [t[1] for t in to_embed]
            embeddings = self._embed_batch(texts)
            for (doc, content, metadata), emb in zip(to_embed, embeddings):
                self._create_chunk_with_embedding(doc, 0, content, metadata, emb)
            self._db.flush()

        log.info("Customers ingested: %d total, %d re-embedded", len(customers), len(to_embed))
        return len(customers)

    def _ingest_orders(self, merchant_id: uuid.UUID) -> int:
        orders = self._order_repo.list_by_merchant(merchant_id, limit=10000)
        # Build product_id → name map to avoid N+1 in chunk text
        products = self._product_repo.list_by_merchant(merchant_id, active_only=False, limit=10000)
        product_names = {str(p.id): p.name for p in products}

        to_embed: list[tuple[KnowledgeDocument, str, dict]] = []
        for order in orders:
            title, content, metadata = _chunk_order(order, product_names)
            doc, changed = self._upsert_document(
                merchant_id, "order", str(order.id), title, content, metadata
            )
            if changed:
                to_embed.append((doc, content, metadata))

        if to_embed:
            # Batch embed in chunks of 100 to avoid large API calls
            batch_size = 100
            for i in range(0, len(to_embed), batch_size):
                batch = to_embed[i:i + batch_size]
                texts = [t[1] for t in batch]
                embeddings = self._embed_batch(texts)
                for (doc, content, metadata), emb in zip(batch, embeddings):
                    self._create_chunk_with_embedding(doc, 0, content, metadata, emb)
            self._db.flush()

        log.info("Orders ingested: %d total, %d re-embedded", len(orders), len(to_embed))
        return len(orders)

    def _ingest_payments(self, merchant_id: uuid.UUID) -> int:
        payments = self._payment_repo.list_by_merchant(merchant_id, limit=10000)
        to_embed: list[tuple[KnowledgeDocument, str, dict]] = []

        for payment in payments:
            title, content, metadata = _chunk_payment(payment)
            doc, changed = self._upsert_document(
                merchant_id, "payment", str(payment.id), title, content, metadata
            )
            if changed:
                to_embed.append((doc, content, metadata))

        if to_embed:
            batch_size = 100
            for i in range(0, len(to_embed), batch_size):
                batch = to_embed[i:i + batch_size]
                texts = [t[1] for t in batch]
                embeddings = self._embed_batch(texts)
                for (doc, content, metadata), emb in zip(batch, embeddings):
                    self._create_chunk_with_embedding(doc, 0, content, metadata, emb)
            self._db.flush()

        log.info("Payments ingested: %d total, %d re-embedded", len(payments), len(to_embed))
        return len(payments)
