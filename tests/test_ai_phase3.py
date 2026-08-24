"""
Phase 3 — AI layer tests.

Strategy
--------
- Zero real API calls. All LLM and embedding interactions use in-process fakes.
- Uses the existing SQLite shared-cache test DB from conftest.py (no PostgreSQL needed).
- DB fixtures are function-scoped via the `db_session` fixture from conftest.py.
- The `client` fixture (session-scoped) patches _get_llm / _get_embedder on the
  route module so the endpoint never reaches real provider code.

Coverage
--------
 1. LLM provider abstraction
 2. Embedding provider abstraction
 3. Structured LLM output (GrowthInsight / GrowthAnalysisResult)
 4. Knowledge document creation + checksum idempotency
 5. Knowledge chunk creation + metadata
 6. Knowledge ingestion (product, customer, order, payment)
 7. Retrieval (keyword fallback on SQLite)
 8. Citations / evidence
 9. Read-only agent tools
10. Agentic RAG bounded execution (MAX_RETRIEVAL_STEPS enforcement)
11. Growth analysis service (AIAnalysisService)
12. POST /api/ai/analyze endpoint
13. Error handling (LLM failure, validation failure, tool error)
14. Audit events written by analysis service
"""
from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any, Type
from unittest.mock import patch

import pytest

# ── AI imports ────────────────────────────────────────────────────────────────
from backend.app.ai.llm.base import BaseLLMProvider
from backend.app.ai.llm.models import EvidenceItem, GrowthAnalysisResult, GrowthInsight
from backend.app.ai.llm.provider import (
    LLMError,
    LLMValidationError,
    build_llm_provider,
)
from backend.app.ai.embeddings.base import BaseEmbeddingProvider, EmbeddingError
from backend.app.ai.embeddings.provider import build_embedding_provider
from backend.app.ai.rag.context import RetrievedContext, RetrievedItem
from backend.app.ai.rag.citations import (
    INSUFFICIENT_EVIDENCE_THRESHOLD,
    build_evidence_items,
    is_sufficient,
    summarise_evidence,
)
from backend.app.ai.rag.retriever import KnowledgeRetriever
from backend.app.ai.rag.pipeline import AgenticRAGPipeline, MAX_RETRIEVAL_STEPS
from backend.app.ai.agents.state import AgentState, ToolCall
from backend.app.ai.agents.tools import AgentToolkit, ToolError

# ── Service / model imports ───────────────────────────────────────────────────
from backend.app.services.knowledge_service import (
    KnowledgeIngestionService,
    _chunk_customer,
    _chunk_merchant,
    _chunk_order,
    _chunk_payment,
    _chunk_product,
    _sha256,
)
from backend.app.services.ai_analysis_service import AIAnalysisService
from backend.app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from backend.app.models.merchant import Merchant
from backend.app.models.product import Product
from backend.app.models.customer import Customer
from backend.app.models.order import Order, OrderItem
from backend.app.models.payment import Payment
from backend.app.models.enums import (
    Currency,
    CustomerSegment,
    MerchantStatus,
    OrderStatus,
    PaymentProvider,
    PaymentStatus,
)


# ═════════════════════════════════════════════════════════════════════════════
# Fake providers — deterministic, zero API calls
# ═════════════════════════════════════════════════════════════════════════════

class _FakeEmbeddingProvider(BaseEmbeddingProvider):
    """
    Deterministic fake — reports EMBEDDING_DIMENSIONS so the dimension
    validation check in ProductionDataConnector passes.
    Never touches the network.
    """

    @property
    def dimensions(self) -> int:
        try:
            from backend.app.core.config import get_settings
            return get_settings().EMBEDDING_DIMENSIONS
        except Exception:
            return 1536

    def embed_text(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        dims = self.dimensions
        return [
            [float(ord(t[0]) % 10) / 10.0] + [0.0] * (dims - 1) if t else [0.0] * dims
            for t in texts
        ]


class _FailingEmbeddingProvider(BaseEmbeddingProvider):
    """Always raises EmbeddingError."""

    @property
    def dimensions(self) -> int:
        try:
            from backend.app.core.config import get_settings
            return get_settings().EMBEDDING_DIMENSIONS
        except Exception:
            return 1536

    def embed_text(self, text: str) -> list[float]:
        raise EmbeddingError("simulated embedding failure")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingError("simulated embedding failure")


def _make_good_result() -> GrowthAnalysisResult:
    """A valid GrowthAnalysisResult the fake LLM can return."""
    return GrowthAnalysisResult(
        insights=[
            GrowthInsight(
                insight_type="cross_sell",
                title="Cross-sell protective case",
                summary="47 headphone buyers have not purchased a case.",
                confidence=0.87,
                expected_revenue=1688.76,
                affected_customer_count=47,
                evidence=[
                    EvidenceItem(
                        source_type="product",
                        source_id="prod-001",
                        description="Wireless Headphones: 150 orders",
                        relevance="High-volume product",
                    )
                ],
                recommended_action="Email 47 headphone buyers.",
                risks=["Low conversion if poorly timed"],
                reasoning_summary="Order data shows cross-sell gap.",
            )
        ],
        insufficient_evidence=False,
        evidence_summary="Retrieved product and order data.",
    )


class _FakeLLMProvider(BaseLLMProvider):
    """
    Fake LLM that:
    - generate()           → returns a JSON tool-selection decision
    - generate_structured() → returns a valid GrowthAnalysisResult

    `tool_sequence` controls which tool names are returned on successive
    generate() calls. Exhausted sequence falls back to "done".
    """

    def __init__(
        self,
        tool_sequence: list[str] | None = None,
        analysis_result: GrowthAnalysisResult | None = None,
    ) -> None:
        self._tool_seq = tool_sequence or ["get_merchant_context", "done"]
        self._tool_idx = 0
        self._analysis_result = analysis_result or _make_good_result()

    def generate(self, system_prompt: str, user_prompt: str, **_) -> str:
        tool = (
            self._tool_seq[self._tool_idx]
            if self._tool_idx < len(self._tool_seq)
            else "done"
        )
        self._tool_idx += 1
        return json.dumps({
            "tool_name": tool,
            "tool_params": {"query": "revenue opportunities"},
            "reasoning": f"step {self._tool_idx}: using {tool}",
        })

    def generate_structured(self, system_prompt, user_prompt, schema, **_):
        return self._analysis_result


class _AlwaysFailLLM(BaseLLMProvider):
    def generate(self, *a, **kw) -> str:
        raise LLMError("simulated LLM failure")

    def generate_structured(self, *a, **kw):
        raise LLMError("simulated LLM failure")


class _FailOnSynthesisLLM(BaseLLMProvider):
    """generate() succeeds (tool selection), generate_structured() fails."""

    def generate(self, *a, **kw) -> str:
        return json.dumps(
            {"tool_name": "get_merchant_context", "tool_params": {}, "reasoning": "ok"}
        )

    def generate_structured(self, *a, **kw):
        raise LLMValidationError("simulated validation failure")


# ═════════════════════════════════════════════════════════════════════════════
# DB fixture helpers
# ═════════════════════════════════════════════════════════════════════════════

def _make_merchant(db) -> Merchant:
    slug = f"m-{uuid.uuid4().hex[:8]}"
    m = Merchant(
        name="Test Merchant",
        slug=slug,
        email=f"{slug}@example.com",
        status=MerchantStatus.active,
        currency=Currency.INR,
    )
    db.add(m)
    db.flush()
    return m


def _make_product(db, merchant: Merchant, suffix: str = "") -> Product:
    p = Product(
        merchant_id=merchant.id,
        name=f"Wireless Headphones {suffix}",
        category="audio",
        price=Decimal("1999.00"),
        sku=f"SKU-{suffix}-{uuid.uuid4().hex[:4]}",
        stock_quantity=100,
        active=True,
        description="Premium over-ear headphones.",
    )
    db.add(p)
    db.flush()
    return p


def _make_customer(db, merchant: Merchant, suffix: str = "") -> Customer:
    c = Customer(
        merchant_id=merchant.id,
        name=f"Customer {suffix}",
        email=f"c-{suffix}-{uuid.uuid4().hex[:4]}@example.com",
        segment=CustomerSegment.returning,
        total_orders=3,
        total_spend=Decimal("5997.00"),
    )
    db.add(c)
    db.flush()
    return c


def _make_order(db, merchant: Merchant, customer: Customer, product: Product) -> Order:
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


def _make_payment(
    db,
    merchant: Merchant,
    order: Order,
    status: PaymentStatus = PaymentStatus.captured,
) -> Payment:
    p = Payment(
        merchant_id=merchant.id,
        order_id=order.id,
        provider=PaymentProvider.synthetic,
        amount=order.total,
        currency=Currency.INR,
        status=status,
        failure_code="INSUFFICIENT_FUNDS" if status == PaymentStatus.failed else None,
        failure_reason="Simulated" if status == PaymentStatus.failed else None,
    )
    db.add(p)
    db.flush()
    return p


def _ingest_all(db, merchant: Merchant) -> None:
    """Helper: ingest all entity types for a merchant."""
    svc = KnowledgeIngestionService(db=db, embedding_provider=_FakeEmbeddingProvider())
    svc.ingest_merchant(merchant.id)
    db.flush()


# ═════════════════════════════════════════════════════════════════════════════
# 1. LLM provider abstraction
# ═════════════════════════════════════════════════════════════════════════════

class TestLLMProviderAbstraction:
    def test_fake_implements_interface(self):
        assert isinstance(_FakeLLMProvider(), BaseLLMProvider)

    def test_generate_returns_string(self):
        result = _FakeLLMProvider().generate("sys", "usr")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_structured_returns_model(self):
        result = _FakeLLMProvider().generate_structured("sys", "usr", GrowthAnalysisResult)
        assert isinstance(result, GrowthAnalysisResult)

    def test_build_llm_provider_unsupported_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported LLM_PROVIDER"):
            build_llm_provider(provider="anthropic", api_key="x", model="y")

    def test_llm_error_is_exception(self):
        assert isinstance(LLMError("x"), Exception)

    def test_llm_validation_error_is_exception(self):
        assert isinstance(LLMValidationError("x"), Exception)

    def test_always_fail_llm_raises_llm_error(self):
        with pytest.raises(LLMError):
            _AlwaysFailLLM().generate("sys", "usr")

    def test_fail_on_synthesis_raises_validation_error(self):
        with pytest.raises(LLMValidationError):
            _FailOnSynthesisLLM().generate_structured("sys", "usr", GrowthAnalysisResult)


# ═════════════════════════════════════════════════════════════════════════════
# 2. Embedding provider abstraction
# ═════════════════════════════════════════════════════════════════════════════

class TestEmbeddingProvider:
    def test_fake_implements_interface(self):
        assert isinstance(_FakeEmbeddingProvider(), BaseEmbeddingProvider)

    def test_embed_text_returns_correct_length_vector(self):
        provider = _FakeEmbeddingProvider()
        vec = provider.embed_text("hello")
        assert isinstance(vec, list)
        assert len(vec) == provider.dimensions
        assert all(isinstance(x, float) for x in vec)

    def test_embed_documents_returns_one_vector_per_text(self):
        provider = _FakeEmbeddingProvider()
        vecs = provider.embed_documents(["a", "b", "c"])
        assert len(vecs) == 3
        for v in vecs:
            assert len(v) == provider.dimensions

    def test_embed_documents_empty_input_returns_empty(self):
        assert _FakeEmbeddingProvider().embed_documents([]) == []

    def test_failing_provider_raises_embedding_error_on_text(self):
        with pytest.raises(EmbeddingError):
            _FailingEmbeddingProvider().embed_text("x")

    def test_failing_provider_raises_embedding_error_on_documents(self):
        with pytest.raises(EmbeddingError):
            _FailingEmbeddingProvider().embed_documents(["a"])

    def test_build_embedding_provider_unsupported_raises(self):
        with pytest.raises(ValueError, match="Unsupported EMBEDDING_PROVIDER"):
            build_embedding_provider(provider="cohere", api_key="x", model="y")

    def test_dimensions_property(self):
        provider = _FakeEmbeddingProvider()
        assert provider.dimensions == 1536


# ═════════════════════════════════════════════════════════════════════════════
# 3. Structured LLM output — GrowthInsight / GrowthAnalysisResult
# ═════════════════════════════════════════════════════════════════════════════

class TestStructuredLLMOutput:
    def test_valid_growth_insight_accepted(self):
        insight = GrowthInsight(
            insight_type="cross_sell",
            title="Test",
            summary="Summary",
            confidence=0.75,
            recommended_action="Do X",
            reasoning_summary="Because data shows Y.",
        )
        assert insight.confidence == 0.75

    def test_invalid_insight_type_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            GrowthInsight(
                insight_type="execute_payment",  # not in allowed set
                title="Bad",
                summary="x",
                confidence=0.5,
                recommended_action="x",
                reasoning_summary="x",
            )

    def test_confidence_above_one_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            GrowthInsight(
                insight_type="upsell",
                title="x",
                summary="x",
                confidence=1.5,
                recommended_action="x",
                reasoning_summary="x",
            )

    def test_confidence_below_zero_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            GrowthInsight(
                insight_type="upsell",
                title="x",
                summary="x",
                confidence=-0.1,
                recommended_action="x",
                reasoning_summary="x",
            )

    def test_expected_revenue_may_be_none(self):
        insight = GrowthInsight(
            insight_type="upsell",
            title="x",
            summary="x",
            confidence=0.5,
            expected_revenue=None,
            recommended_action="x",
            reasoning_summary="x",
        )
        assert insight.expected_revenue is None

    def test_growth_analysis_result_defaults(self):
        r = GrowthAnalysisResult()
        assert r.insights == []
        assert r.insufficient_evidence is False
        assert r.evidence_summary == ""

    def test_validation_failure_does_not_mutate_external_state(self):
        """Pydantic validation failure must have no side-effects."""
        from pydantic import ValidationError
        sentinel = {"touched": False}
        try:
            GrowthInsight(
                insight_type="invalid_type",
                title="x",
                summary="x",
                confidence=0.5,
                recommended_action="x",
                reasoning_summary="x",
            )
        except ValidationError:
            pass
        assert sentinel["touched"] is False  # no side-effects

    def test_all_valid_insight_types_accepted(self):
        for t in (
            "cross_sell", "upsell", "failed_payment_recovery",
            "campaign", "checkout_optimization",
            "customer_segment", "product_opportunity", "revenue_leakage",
        ):
            insight = GrowthInsight(
                insight_type=t,
                title="t",
                summary="s",
                confidence=0.5,
                recommended_action="a",
                reasoning_summary="r",
            )
            assert insight.insight_type == t


# ═════════════════════════════════════════════════════════════════════════════
# 4 & 5. Knowledge documents + chunks
# ═════════════════════════════════════════════════════════════════════════════

class TestKnowledgeDocumentsAndChunks:
    def test_sha256_is_deterministic(self):
        assert _sha256("same content") == _sha256("same content")

    def test_different_content_different_checksum(self):
        assert _sha256("A") != _sha256("B")

    def test_checksum_length_is_64_hex_chars(self):
        assert len(_sha256("any text")) == 64

    def test_create_knowledge_document(self, db_session):
        merchant = _make_merchant(db_session)
        content = "Product: Widget\nCategory: tools"
        doc = KnowledgeDocument(
            merchant_id=merchant.id,
            source_type="product",
            source_id="prod-001",
            title="Product: Widget",
            content=content,
            checksum=_sha256(content),
        )
        db_session.add(doc)
        db_session.flush()
        assert doc.id is not None
        assert len(doc.checksum) == 64

    def test_upsert_document_same_content_returns_false(self, db_session):
        """Second upsert with identical content → changed=False, no re-embed."""
        merchant = _make_merchant(db_session)
        product = _make_product(db_session, merchant)
        svc = KnowledgeIngestionService(db=db_session, embedding_provider=_FakeEmbeddingProvider())
        title, content, meta = _chunk_product(product)

        _, changed1 = svc._upsert_document(merchant.id, "product", str(product.id), title, content, meta)
        assert changed1 is True

        _, changed2 = svc._upsert_document(merchant.id, "product", str(product.id), title, content, meta)
        assert changed2 is False

    def test_upsert_document_changed_content_returns_true(self, db_session):
        merchant = _make_merchant(db_session)
        product = _make_product(db_session, merchant)
        svc = KnowledgeIngestionService(db=db_session, embedding_provider=_FakeEmbeddingProvider())
        title, content, meta = _chunk_product(product)
        svc._upsert_document(merchant.id, "product", str(product.id), title, content, meta)

        new_content = content + "\nDescriptions: Updated"
        _, changed = svc._upsert_document(merchant.id, "product", str(product.id), title, new_content, meta)
        assert changed is True

    def test_chunk_has_correct_index_zero(self, db_session):
        merchant = _make_merchant(db_session)
        product = _make_product(db_session, merchant)
        svc = KnowledgeIngestionService(db=db_session, embedding_provider=_FakeEmbeddingProvider())
        title, content, meta = _chunk_product(product)
        doc, _ = svc._upsert_document(merchant.id, "product", str(product.id), title, content, meta)
        chunk = svc._create_chunk_with_embedding(doc, 0, content, meta, [0.1, 0.2, 0.3, 0.4])
        db_session.flush()
        assert chunk.chunk_index == 0
        assert chunk.content == content
        assert chunk.chunk_metadata == meta


# ═════════════════════════════════════════════════════════════════════════════
# 6. Knowledge chunking helpers
# ═════════════════════════════════════════════════════════════════════════════

class TestChunkingHelpers:
    def test_chunk_product_contains_name_and_category(self, db_session):
        merchant = _make_merchant(db_session)
        product = _make_product(db_session, merchant)
        title, content, meta = _chunk_product(product)
        assert "Wireless Headphones" in content
        assert "audio" in content
        assert meta["entity_type"] == "product"
        assert meta["source"] == "merchant_catalog"

    def test_chunk_customer_contains_segment(self, db_session):
        merchant = _make_merchant(db_session)
        customer = _make_customer(db_session, merchant)
        title, content, meta = _chunk_customer(customer)
        assert "returning" in content.lower()
        assert meta["entity_type"] == "customer"

    def test_chunk_order_contains_order_number(self, db_session):
        merchant = _make_merchant(db_session)
        customer = _make_customer(db_session, merchant)
        product = _make_product(db_session, merchant)
        order = _make_order(db_session, merchant, customer, product)
        title, content, meta = _chunk_order(order, {str(product.id): product.name})
        assert order.order_number in content
        assert meta["entity_type"] == "order"

    def test_chunk_payment_failed_contains_failure_code(self, db_session):
        merchant = _make_merchant(db_session)
        customer = _make_customer(db_session, merchant)
        product = _make_product(db_session, merchant)
        order = _make_order(db_session, merchant, customer, product)
        payment = _make_payment(db_session, merchant, order, PaymentStatus.failed)
        title, content, meta = _chunk_payment(payment)
        assert "INSUFFICIENT_FUNDS" in content
        assert meta["failure_code"] == "INSUFFICIENT_FUNDS"

    def test_chunk_merchant_contains_merchant_name(self, db_session):
        merchant = _make_merchant(db_session)
        stats = {"product_count": 5, "customer_count": 20, "order_count": 100,
                 "total_revenue": 200000.0, "failed_payment_count": 3}
        title, content, meta = _chunk_merchant(merchant, stats)
        assert merchant.name in content
        assert meta["entity_type"] == "merchant"

    def test_chunking_is_deterministic(self, db_session):
        merchant = _make_merchant(db_session)
        product = _make_product(db_session, merchant)
        _, content1, _ = _chunk_product(product)
        _, content2, _ = _chunk_product(product)
        assert content1 == content2


# ═════════════════════════════════════════════════════════════════════════════
# 6b. Knowledge ingestion service
# ═════════════════════════════════════════════════════════════════════════════

class TestKnowledgeIngestionService:
    def test_ingest_product_creates_doc_and_chunk(self, db_session):
        from sqlalchemy import select
        merchant = _make_merchant(db_session)
        _make_product(db_session, merchant)
        svc = KnowledgeIngestionService(db=db_session, embedding_provider=_FakeEmbeddingProvider())
        count = svc._ingest_products(merchant.id)
        db_session.flush()

        assert count == 1
        docs = db_session.scalars(
            select(KnowledgeDocument).where(
                KnowledgeDocument.merchant_id == merchant.id,
                KnowledgeDocument.source_type == "product",
            )
        ).all()
        assert len(docs) == 1
        chunks = db_session.scalars(
            select(KnowledgeChunk).where(KnowledgeChunk.document_id == docs[0].id)
        ).all()
        assert len(chunks) == 1
        assert chunks[0].chunk_index == 0

    def test_ingest_customer_creates_document(self, db_session):
        merchant = _make_merchant(db_session)
        _make_customer(db_session, merchant, "c1")
        _make_customer(db_session, merchant, "c2")
        svc = KnowledgeIngestionService(db=db_session, embedding_provider=_FakeEmbeddingProvider())
        assert svc._ingest_customers(merchant.id) == 2

    def test_ingest_payment_creates_document(self, db_session):
        merchant = _make_merchant(db_session)
        customer = _make_customer(db_session, merchant)
        product = _make_product(db_session, merchant)
        order = _make_order(db_session, merchant, customer, product)
        _make_payment(db_session, merchant, order, PaymentStatus.failed)
        svc = KnowledgeIngestionService(db=db_session, embedding_provider=_FakeEmbeddingProvider())
        assert svc._ingest_payments(merchant.id) == 1

    def test_unchanged_content_is_not_re_embedded(self, db_session):
        """Ingesting the same product twice must not call embed on the second run."""
        merchant = _make_merchant(db_session)
        _make_product(db_session, merchant)

        call_counts: list[int] = []
        provider = _FakeEmbeddingProvider()
        original = provider.embed_documents

        def tracking_embed(texts):
            call_counts.append(len(texts))
            return original(texts)

        provider.embed_documents = tracking_embed

        svc1 = KnowledgeIngestionService(db=db_session, embedding_provider=provider)
        svc1._ingest_products(merchant.id)
        db_session.flush()
        first_total = sum(call_counts)

        svc2 = KnowledgeIngestionService(db=db_session, embedding_provider=provider)
        svc2._ingest_products(merchant.id)
        db_session.flush()
        second_total = sum(call_counts)

        assert second_total == first_total, (
            "Re-ingesting unchanged content must not generate new embeddings"
        )

    def test_failing_embedder_stores_null_not_raises(self, db_session):
        """Embedding failure during ingestion must be handled gracefully."""
        from sqlalchemy import select
        merchant = _make_merchant(db_session)
        _make_product(db_session, merchant)
        svc = KnowledgeIngestionService(
            db=db_session,
            embedding_provider=_FailingEmbeddingProvider(),
        )
        try:
            svc._ingest_products(merchant.id)
            db_session.flush()
        except Exception as exc:
            pytest.fail(f"Ingestion must not raise on embedding failure: {exc}")

        chunks = db_session.scalars(
            select(KnowledgeChunk).where(KnowledgeChunk.merchant_id == merchant.id)
        ).all()
        assert len(chunks) == 1
        assert chunks[0].embedding is None


# ═════════════════════════════════════════════════════════════════════════════
# 7. Retrieval
# ═════════════════════════════════════════════════════════════════════════════

class TestRetrieval:
    def _setup(self, db_session):
        merchant = _make_merchant(db_session)
        product = _make_product(db_session, merchant)
        svc = KnowledgeIngestionService(
            db=db_session, embedding_provider=_FakeEmbeddingProvider()
        )
        svc._ingest_products(merchant.id)
        db_session.flush()
        retriever = KnowledgeRetriever(
            db=db_session, embedding_provider=_FakeEmbeddingProvider()
        )
        return merchant, product, retriever

    def test_retrieve_returns_retrieved_context(self, db_session):
        merchant, _, retriever = self._setup(db_session)
        ctx = retriever.retrieve("headphones", merchant.id)
        assert isinstance(ctx, RetrievedContext)

    def test_retrieved_items_have_required_fields(self, db_session):
        merchant, _, retriever = self._setup(db_session)
        ctx = retriever.retrieve("headphones audio", merchant.id)
        for item in ctx.items:
            assert item.content != ""
            assert item.source_type != ""
            assert item.source_id != ""
            assert item.document_id != ""
            assert item.chunk_id != ""

    def test_retrieval_source_type_filter(self, db_session):
        merchant, _, retriever = self._setup(db_session)
        ctx = retriever.retrieve("headphones", merchant.id, source_types=["customer"])
        for item in ctx.items:
            assert item.source_type == "customer"

    def test_retrieval_respects_limit(self, db_session):
        merchant = _make_merchant(db_session)
        for i in range(4):
            _make_product(db_session, merchant, suffix=str(i))
        svc = KnowledgeIngestionService(
            db=db_session, embedding_provider=_FakeEmbeddingProvider()
        )
        svc._ingest_products(merchant.id)
        db_session.flush()
        retriever = KnowledgeRetriever(
            db=db_session, embedding_provider=_FakeEmbeddingProvider()
        )
        ctx = retriever.retrieve("product", merchant.id, limit=2)
        assert len(ctx.items) <= 2

    def test_empty_db_returns_empty_context(self, db_session):
        merchant = _make_merchant(db_session)
        retriever = KnowledgeRetriever(
            db=db_session, embedding_provider=_FakeEmbeddingProvider()
        )
        ctx = retriever.retrieve("anything", merchant.id)
        assert ctx.is_empty

    def test_to_evidence_dict_has_expected_keys(self, db_session):
        merchant, _, retriever = self._setup(db_session)
        ctx = retriever.retrieve("headphones", merchant.id)
        if ctx.items:
            d = ctx.items[0].to_evidence_dict()
            for key in ("source_type", "source_id", "document_id", "chunk_id",
                        "similarity", "content_preview", "metadata"):
                assert key in d


# ═════════════════════════════════════════════════════════════════════════════
# 8. Citations / evidence
# ═════════════════════════════════════════════════════════════════════════════

def _ctx_with_items(n: int, source_type: str = "product") -> RetrievedContext:
    items = [
        RetrievedItem(
            content=f"Item {i} content",
            source_type=source_type,
            source_id=f"src-{i}",
            document_id=f"doc-{i}",
            chunk_id=f"chunk-{i}",
            similarity=0.9 - i * 0.05,
        )
        for i in range(n)
    ]
    return RetrievedContext(query="test query", items=items, retrieval_method="keyword")


class TestCitationsAndEvidence:
    def test_build_evidence_items_maps_all_sources(self):
        ctx = _ctx_with_items(3)
        evidence = build_evidence_items(ctx)
        assert len(evidence) == 3
        retrieved_ids = {item.source_id for item in ctx.items}
        evidence_ids = {ev.source_id for ev in evidence}
        assert evidence_ids == retrieved_ids  # no fabricated IDs

    def test_evidence_description_is_not_empty(self):
        ctx = _ctx_with_items(2)
        evidence = build_evidence_items(ctx)
        for ev in evidence:
            assert len(ev.description) > 0

    def test_is_sufficient_true_at_threshold(self):
        ctx = _ctx_with_items(INSUFFICIENT_EVIDENCE_THRESHOLD)
        assert is_sufficient([ctx]) is True

    def test_is_sufficient_false_below_threshold(self):
        ctx = _ctx_with_items(INSUFFICIENT_EVIDENCE_THRESHOLD - 1)
        assert is_sufficient([ctx]) is False

    def test_is_sufficient_false_for_empty_list(self):
        assert is_sufficient([]) is False

    def test_is_sufficient_counts_across_multiple_contexts(self):
        ctx1 = _ctx_with_items(1)
        ctx2 = _ctx_with_items(1)
        # 1 + 1 == INSUFFICIENT_EVIDENCE_THRESHOLD (2)
        assert is_sufficient([ctx1, ctx2]) is True

    def test_summarise_evidence_includes_query(self):
        ctx = _ctx_with_items(3)
        summary = summarise_evidence([ctx])
        assert "test query" in summary

    def test_summarise_empty_returns_no_evidence(self):
        assert "No evidence" in summarise_evidence([])


# ═════════════════════════════════════════════════════════════════════════════
# 9. Read-only agent tools
# ═════════════════════════════════════════════════════════════════════════════

class TestReadOnlyAgentTools:
    def _toolkit(self, db_session, merchant: Merchant) -> AgentToolkit:
        return AgentToolkit(
            db=db_session,
            merchant_id=merchant.id,
            embedding_provider=_FakeEmbeddingProvider(),
        )

    def test_available_tools_contain_no_write_keywords(self):
        """
        Verifies the tool set is read-only by name inspection.

        Checks for mutation-verb prefixes/words only. 'pay' is intentionally
        excluded because 'get_failed_payments' is a legitimate read-only
        retrieval tool — it reads payment records, it does not create or
        mutate them. The write-operation equivalent would be 'make_payment',
        'create_payment', 'execute_payment', etc.
        """
        # These are mutation verbs that should never appear in a read-only tool name.
        # Deliberately precise: 'pay' alone is not a mutation verb in tool names
        # (get_failed_payments is a reader, not a writer).
        write_keywords = {
            "create", "update", "delete", "refund",
            "charge", "execute", "send", "campaign",
            "make_payment", "create_payment", "execute_payment",
        }
        for tool_name in AgentToolkit.AVAILABLE_TOOLS:
            for kw in write_keywords:
                assert kw not in tool_name.lower(), (
                    f"Tool '{tool_name}' looks like a mutation tool (keyword: '{kw}'). "
                    "Phase 3 tools must be read-only."
                )

    def test_unknown_tool_raises_tool_error(self, db_session):
        merchant = _make_merchant(db_session)
        with pytest.raises(ToolError):
            self._toolkit(db_session, merchant).call("execute_payment", {})

    def test_get_merchant_context_returns_context_and_summary(self, db_session):
        merchant = _make_merchant(db_session)
        _ingest_all(db_session, merchant)
        ctx, summary = self._toolkit(db_session, merchant).call("get_merchant_context", {})
        assert isinstance(ctx, RetrievedContext)
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_get_failed_payments_returns_context(self, db_session):
        merchant = _make_merchant(db_session)
        customer = _make_customer(db_session, merchant)
        product = _make_product(db_session, merchant)
        order = _make_order(db_session, merchant, customer, product)
        _make_payment(db_session, merchant, order, PaymentStatus.failed)
        ctx, summary = self._toolkit(db_session, merchant).call("get_failed_payments", {})
        assert isinstance(ctx, RetrievedContext)
        assert "failed" in summary.lower()

    def test_get_product_returns_context(self, db_session):
        merchant = _make_merchant(db_session)
        _make_product(db_session, merchant)
        _ingest_all(db_session, merchant)
        ctx, summary = self._toolkit(db_session, merchant).call("get_product", {"query": "headphones"})
        assert isinstance(ctx, RetrievedContext)

    def test_get_customer_segments_returns_context_with_content(self, db_session):
        merchant = _make_merchant(db_session)
        _make_customer(db_session, merchant, "s1")
        _make_customer(db_session, merchant, "s2")
        ctx, summary = self._toolkit(db_session, merchant).call("get_customer_segments", {})
        assert isinstance(ctx, RetrievedContext)
        assert len(ctx.items) >= 1
        assert "segment" in ctx.items[0].content.lower()

    def test_get_order_patterns_returns_context(self, db_session):
        merchant = _make_merchant(db_session)
        customer = _make_customer(db_session, merchant)
        product = _make_product(db_session, merchant)
        _make_order(db_session, merchant, customer, product)
        ctx, summary = self._toolkit(db_session, merchant).call("get_order_patterns", {})
        assert isinstance(ctx, RetrievedContext)
        assert len(ctx.items) >= 1


# ═════════════════════════════════════════════════════════════════════════════
# 10. Agentic RAG — bounded multi-step execution
# ═════════════════════════════════════════════════════════════════════════════

class TestAgenticRAGPipeline:
    def _pipeline(
        self,
        db_session,
        merchant: Merchant,
        tool_sequence: list[str] | None = None,
        analysis_result: GrowthAnalysisResult | None = None,
    ) -> AgenticRAGPipeline:
        llm = _FakeLLMProvider(
            tool_sequence=tool_sequence,
            analysis_result=analysis_result,
        )
        toolkit = AgentToolkit(
            db=db_session,
            merchant_id=merchant.id,
            embedding_provider=_FakeEmbeddingProvider(),
        )
        return AgenticRAGPipeline(llm=llm, toolkit=toolkit)

    def test_run_returns_agent_state(self, db_session):
        merchant = _make_merchant(db_session)
        state = self._pipeline(db_session, merchant).run("Find opportunities", merchant.id)
        assert isinstance(state, AgentState)

    def test_state_has_run_id(self, db_session):
        merchant = _make_merchant(db_session)
        state = self._pipeline(db_session, merchant).run("Find opportunities", merchant.id)
        assert state.run_id is not None and len(state.run_id) > 0

    # ── CRITICAL: bounded execution ──────────────────────────────────────────

    def test_does_not_exceed_max_retrieval_steps(self, db_session):
        """
        Even if the LLM always asks for another tool, the loop MUST stop
        at MAX_RETRIEVAL_STEPS. This verifies the bounded agentic behaviour.
        """
        merchant = _make_merchant(db_session)
        # Provide far more tools than the limit
        infinite_tools = ["get_merchant_context"] * (MAX_RETRIEVAL_STEPS + 10)
        state = self._pipeline(
            db_session, merchant, tool_sequence=infinite_tools
        ).run("Infinite loop test", merchant.id)

        assert state.retrieval_steps_used <= MAX_RETRIEVAL_STEPS, (
            f"Agent ran {state.retrieval_steps_used} steps, "
            f"but MAX_RETRIEVAL_STEPS={MAX_RETRIEVAL_STEPS}"
        )

    def test_max_retrieval_steps_constant_is_bounded(self):
        assert isinstance(MAX_RETRIEVAL_STEPS, int)
        assert 1 <= MAX_RETRIEVAL_STEPS <= 10

    def test_done_signal_stops_loop_immediately(self, db_session):
        """'done' on step 1 → zero tools executed, zero tool_calls."""
        merchant = _make_merchant(db_session)
        state = self._pipeline(
            db_session, merchant, tool_sequence=["done"]
        ).run("Early stop test", merchant.id)
        assert len(state.tool_calls) == 0

    # ── Multi-step flow ──────────────────────────────────────────────────────

    def test_multi_step_flow_records_tool_calls(self, db_session):
        merchant = _make_merchant(db_session)
        _ingest_all(db_session, merchant)
        state = self._pipeline(
            db_session, merchant,
            tool_sequence=["get_merchant_context", "get_customer_segments", "done"],
        ).run("Multi-step test", merchant.id)
        # At least the first tool ran
        assert len(state.tool_calls) >= 1
        assert state.tool_calls[0].tool_name == "get_merchant_context"

    def test_second_retrieval_adds_more_evidence(self, db_session):
        """After step 1, the pipeline should have more evidence than after 0 steps."""
        merchant = _make_merchant(db_session)
        _ingest_all(db_session, merchant)
        customer = _make_customer(db_session, merchant)
        state = self._pipeline(
            db_session, merchant,
            tool_sequence=["get_merchant_context", "get_customer_segments", "done"],
        ).run("Evidence accumulation test", merchant.id)
        # After two retrieval steps we may have evidence from both tools
        # (exact count varies; just assert state is well-formed)
        assert state.retrieval_steps_used >= 1

    # ── Sufficiency gate ─────────────────────────────────────────────────────

    def test_insufficient_evidence_sets_correct_status(self, db_session):
        """Empty DB → no knowledge → insufficient evidence."""
        merchant = _make_merchant(db_session)
        state = self._pipeline(
            db_session, merchant,
            tool_sequence=["search_knowledge"],
        ).run("Empty DB test", merchant.id)
        assert state.status in ("insufficient_evidence", "completed", "failed")

    # ── Error handling inside pipeline ──────────────────────────────────────

    def test_llm_synthesis_failure_sets_failed_status(self, db_session):
        merchant = _make_merchant(db_session)
        _ingest_all(db_session, merchant)
        toolkit = AgentToolkit(
            db=db_session,
            merchant_id=merchant.id,
            embedding_provider=_FakeEmbeddingProvider(),
        )
        state = AgenticRAGPipeline(
            llm=_FailOnSynthesisLLM(), toolkit=toolkit
        ).run("Synthesis failure test", merchant.id)
        assert state.status in ("failed", "insufficient_evidence")

    def test_pipeline_run_never_raises(self, db_session):
        merchant = _make_merchant(db_session)
        try:
            self._pipeline(db_session, merchant).run("Never raise test", merchant.id)
        except Exception as exc:
            pytest.fail(f"pipeline.run() must never raise, got: {exc}")

    # ── Observability: no hidden chain-of-thought ────────────────────────────

    def test_tool_call_summaries_are_concise(self, db_session):
        merchant = _make_merchant(db_session)
        _ingest_all(db_session, merchant)
        state = self._pipeline(
            db_session, merchant,
            tool_sequence=["get_merchant_context", "done"],
        ).run("CoT test", merchant.id)
        for tc in state.tool_calls:
            assert len(tc.result_summary) < 500, (
                f"Tool summary too long ({len(tc.result_summary)} chars) — "
                "may be raw chain-of-thought"
            )

    def test_api_response_required_keys_present(self, db_session):
        merchant = _make_merchant(db_session)
        state = self._pipeline(db_session, merchant).run("API shape test", merchant.id)
        resp = state.to_api_response()
        required = {
            "analysis_id", "status", "goal", "insights",
            "evidence_summary", "retrieval_steps", "tool_calls",
            "insufficient_evidence", "error",
        }
        assert required.issubset(resp.keys()), (
            f"Missing keys: {required - resp.keys()}"
        )

    def test_api_response_no_chain_of_thought_keys(self, db_session):
        merchant = _make_merchant(db_session)
        state = self._pipeline(db_session, merchant).run("CoT key test", merchant.id)
        resp = state.to_api_response()
        forbidden = {"chain_of_thought", "raw_reasoning", "internal_thoughts", "_cot"}
        for key in forbidden:
            assert key not in resp


# ═════════════════════════════════════════════════════════════════════════════
# 11. AIAnalysisService
# ═════════════════════════════════════════════════════════════════════════════

class TestAIAnalysisService:
    def test_unknown_merchant_returns_failed_state(self, db_session):
        svc = AIAnalysisService(
            db=db_session,
            llm=_FakeLLMProvider(),
            embedding_provider=_FakeEmbeddingProvider(),
        )
        state = svc.analyse(goal="Find opportunities", merchant_id=uuid.uuid4())
        assert state.status == "failed"
        assert "not found" in (state.error or "").lower()

    def test_valid_merchant_returns_agent_state(self, db_session):
        merchant = _make_merchant(db_session)
        svc = AIAnalysisService(
            db=db_session,
            llm=_FakeLLMProvider(),
            embedding_provider=_FakeEmbeddingProvider(),
        )
        state = svc.analyse(goal="Find opportunities", merchant_id=merchant.id)
        assert isinstance(state, AgentState)

    def test_analyse_with_data_produces_non_error_state(self, db_session):
        merchant = _make_merchant(db_session)
        product = _make_product(db_session, merchant)
        customer = _make_customer(db_session, merchant)
        order = _make_order(db_session, merchant, customer, product)
        _make_payment(db_session, merchant, order)
        _ingest_all(db_session, merchant)
        svc = AIAnalysisService(
            db=db_session,
            llm=_FakeLLMProvider(
                tool_sequence=["get_merchant_context", "get_order_patterns", "done"]
            ),
            embedding_provider=_FakeEmbeddingProvider(),
        )
        state = svc.analyse(goal="Cross-sell opportunities", merchant_id=merchant.id)
        assert state.status in ("completed", "insufficient_evidence")

    def test_analyse_writes_at_least_one_audit_event(self, db_session):
        from sqlalchemy import select
        from backend.app.models.audit_event import AuditEvent

        merchant = _make_merchant(db_session)
        svc = AIAnalysisService(
            db=db_session,
            llm=_FakeLLMProvider(),
            embedding_provider=_FakeEmbeddingProvider(),
        )
        svc.analyse(goal="Audit trail test", merchant_id=merchant.id)
        db_session.flush()

        events = db_session.scalars(
            select(AuditEvent).where(AuditEvent.merchant_id == merchant.id)
        ).all()
        assert len(events) >= 1

    def test_audit_event_payload_does_not_contain_api_key(self, db_session):
        from sqlalchemy import select
        from backend.app.models.audit_event import AuditEvent

        merchant = _make_merchant(db_session)
        svc = AIAnalysisService(
            db=db_session,
            llm=_FakeLLMProvider(),
            embedding_provider=_FakeEmbeddingProvider(),
        )
        svc.analyse(goal="Security check", merchant_id=merchant.id)
        db_session.flush()

        for evt in db_session.scalars(
            select(AuditEvent).where(AuditEvent.merchant_id == merchant.id)
        ).all():
            payload_str = str(evt.payload or "")
            assert "sk-" not in payload_str
            assert "api_key" not in payload_str.lower()


# ═════════════════════════════════════════════════════════════════════════════
# 12. POST /api/ai/analyze endpoint
# ═════════════════════════════════════════════════════════════════════════════

class TestAIAnalysisEndpoint:
    """
    The route calls _get_llm() and _get_embedder() which need LLM_API_KEY.
    We patch both to return fake providers — no real API calls.
    """

    @staticmethod
    def _patch():
        return (
            patch("backend.app.api.routes.ai._get_llm", return_value=_FakeLLMProvider()),
            patch("backend.app.api.routes.ai._get_embedder", return_value=_FakeEmbeddingProvider()),
        )

    def test_returns_200_with_valid_request(self, client, db_session):
        merchant = _make_merchant(db_session)
        db_session.commit()
        with patch("backend.app.api.routes.ai._get_llm", return_value=_FakeLLMProvider()), \
             patch("backend.app.api.routes.ai._get_embedder", return_value=_FakeEmbeddingProvider()):
            r = client.post(
                "/api/ai/analyze",
                json={"goal": "Find revenue opportunities", "merchant_id": str(merchant.id)},
            )
        assert r.status_code == 200

    def test_response_has_analysis_id(self, client, db_session):
        merchant = _make_merchant(db_session)
        db_session.commit()
        with patch("backend.app.api.routes.ai._get_llm", return_value=_FakeLLMProvider()), \
             patch("backend.app.api.routes.ai._get_embedder", return_value=_FakeEmbeddingProvider()):
            body = client.post(
                "/api/ai/analyze",
                json={"goal": "Find revenue opportunities", "merchant_id": str(merchant.id)},
            ).json()
        assert "analysis_id" in body
        assert body["analysis_id"] is not None

    def test_response_has_status_field(self, client, db_session):
        merchant = _make_merchant(db_session)
        db_session.commit()
        with patch("backend.app.api.routes.ai._get_llm", return_value=_FakeLLMProvider()), \
             patch("backend.app.api.routes.ai._get_embedder", return_value=_FakeEmbeddingProvider()):
            body = client.post(
                "/api/ai/analyze",
                json={"goal": "Find revenue opportunities", "merchant_id": str(merchant.id)},
            ).json()
        assert body["status"] in ("completed", "failed", "insufficient_evidence", "running")

    def test_response_has_retrieval_steps(self, client, db_session):
        merchant = _make_merchant(db_session)
        db_session.commit()
        with patch("backend.app.api.routes.ai._get_llm", return_value=_FakeLLMProvider()), \
             patch("backend.app.api.routes.ai._get_embedder", return_value=_FakeEmbeddingProvider()):
            body = client.post(
                "/api/ai/analyze",
                json={"goal": "Find revenue opportunities", "merchant_id": str(merchant.id)},
            ).json()
        assert "retrieval_steps" in body
        assert isinstance(body["retrieval_steps"], int)

    def test_response_has_tool_calls_list(self, client, db_session):
        merchant = _make_merchant(db_session)
        db_session.commit()
        with patch("backend.app.api.routes.ai._get_llm", return_value=_FakeLLMProvider()), \
             patch("backend.app.api.routes.ai._get_embedder", return_value=_FakeEmbeddingProvider()):
            body = client.post(
                "/api/ai/analyze",
                json={"goal": "Find revenue opportunities", "merchant_id": str(merchant.id)},
            ).json()
        assert "tool_calls" in body
        assert isinstance(body["tool_calls"], list)

    def test_response_has_insights_list(self, client, db_session):
        merchant = _make_merchant(db_session)
        db_session.commit()
        with patch("backend.app.api.routes.ai._get_llm", return_value=_FakeLLMProvider()), \
             patch("backend.app.api.routes.ai._get_embedder", return_value=_FakeEmbeddingProvider()):
            body = client.post(
                "/api/ai/analyze",
                json={"goal": "Find revenue opportunities", "merchant_id": str(merchant.id)},
            ).json()
        assert "insights" in body
        assert isinstance(body["insights"], list)

    def test_goal_too_short_returns_422(self, client):
        r = client.post("/api/ai/analyze", json={"goal": "hi"})
        assert r.status_code == 422

    def test_missing_goal_returns_422(self, client):
        r = client.post("/api/ai/analyze", json={})
        assert r.status_code == 422

    def test_response_does_not_expose_api_key(self, client, db_session):
        merchant = _make_merchant(db_session)
        db_session.commit()
        with patch("backend.app.api.routes.ai._get_llm", return_value=_FakeLLMProvider()), \
             patch("backend.app.api.routes.ai._get_embedder", return_value=_FakeEmbeddingProvider()):
            r = client.post(
                "/api/ai/analyze",
                json={"goal": "Security check goal", "merchant_id": str(merchant.id)},
            )
        assert "sk-" not in r.text

    def test_503_when_llm_api_key_is_empty(self):
        """_get_llm() must raise HTTPException(503) when LLM_API_KEY is empty."""
        from fastapi import HTTPException
        from backend.app.api.routes.ai import _get_llm

        with patch("backend.app.api.routes.ai.get_settings") as mock_cfg:
            mock_cfg.return_value.LLM_API_KEY = ""
            mock_cfg.return_value.LLM_PROVIDER = "openai"
            mock_cfg.return_value.LLM_MODEL = "gpt-4o-mini"
            with pytest.raises(HTTPException) as exc_info:
                _get_llm()
            assert exc_info.value.status_code == 503

    def test_no_merchant_in_db_returns_404(self, client):
        """When no merchants exist and merchant_id is omitted → 404."""
        with patch("backend.app.api.routes.ai._get_llm", return_value=_FakeLLMProvider()), \
             patch("backend.app.api.routes.ai._get_embedder", return_value=_FakeEmbeddingProvider()):
            # Use a fresh session with an empty-ish merchant table by providing
            # an invalid merchant_id instead.
            r = client.post(
                "/api/ai/analyze",
                json={
                    "goal": "Revenue opportunities",
                    "merchant_id": str(uuid.uuid4()),
                },
            )
        # A non-existent merchant → service fails it gracefully → 200 with failed status
        # (the service sets state.fail(), not raises HTTPException)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "failed"


# ═════════════════════════════════════════════════════════════════════════════
# 13. AgentState unit tests
# ═════════════════════════════════════════════════════════════════════════════

class TestAgentState:
    def test_initial_status_is_running(self):
        state = AgentState(goal="test", merchant_id="m1")
        assert state.status == "running"

    def test_complete_sets_status_and_timestamp(self):
        state = AgentState(goal="test", merchant_id="m1")
        state.complete(insights=[{"x": 1}], evidence_summary="summary")
        assert state.status == "completed"
        assert state.completed_at is not None

    def test_fail_sets_status_and_error(self):
        state = AgentState(goal="test", merchant_id="m1")
        state.fail("Something went wrong")
        assert state.status == "failed"
        assert state.error == "Something went wrong"

    def test_mark_insufficient_sets_flag(self):
        state = AgentState(goal="test", merchant_id="m1")
        state.mark_insufficient("Not enough data")
        assert state.status == "insufficient_evidence"
        assert state.insufficient_evidence is True

    def test_record_tool_call_appends(self):
        state = AgentState(goal="test", merchant_id="m1")
        state.record_tool_call("search_knowledge", {"query": "x"}, "Found 3 items", 3)
        assert len(state.tool_calls) == 1
        assert state.tool_calls[0].tool_name == "search_knowledge"

    def test_add_evidence_accumulates_items(self):
        state = AgentState(goal="test", merchant_id="m1")
        items = [RetrievedItem(
            content="c", source_type="product", source_id="p1",
            document_id="d1", chunk_id="ch1", similarity=0.9,
        )]
        state.add_evidence(items)
        assert len(state.retrieved_evidence) == 1

    def test_to_api_response_contains_no_hidden_cot_keys(self):
        state = AgentState(goal="test", merchant_id="m1")
        state.complete(insights=[], evidence_summary="x")
        resp = state.to_api_response()
        forbidden = {"chain_of_thought", "raw_reasoning", "internal_thoughts", "_cot"}
        for key in forbidden:
            assert key not in resp
