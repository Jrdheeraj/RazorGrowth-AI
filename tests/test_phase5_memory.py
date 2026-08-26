"""Phase 5 — growth memory: retrieval, isolation, learning-from-outcomes."""
from __future__ import annotations

import math
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from backend.app.models.enums import Currency, MemoryType, MerchantStatus
from backend.app.models.merchant import Merchant
from backend.app.services.memory import GrowthMemoryService, _cosine


class FakeEmbeddingProvider:
    """Deterministic embedding: topic-keyword bag-of-words hashing."""

    dimensions = 16

    def embed_text(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        for token in text.lower().split():
            vec[hash(token) % self.dimensions] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts):
        return [self.embed_text(t) for t in texts]


@pytest.fixture()
def merchant(db_session: Session) -> Merchant:
    m = Merchant(
        name=f"P5 Mem {uuid.uuid4().hex[:6]}",
        slug=f"p5-mem-{uuid.uuid4().hex[:10]}",
        email="p5mem@x.com",
        status=MerchantStatus.active,
        currency=Currency.INR,
    )
    db_session.add(m)
    db_session.commit()
    return m


@pytest.fixture()
def svc(db_session: Session) -> GrowthMemoryService:
    return GrowthMemoryService(db_session, embedding_provider=FakeEmbeddingProvider())


class TestMemoryRecordRetrieve:
    def test_record_requires_content(self, db_session, merchant, svc):
        with pytest.raises(ValueError):
            svc.record(merchant_id=merchant.id, memory_type=MemoryType.recommendation, content="  ")

    def test_record_and_retrieve_roundtrip(self, db_session, merchant, svc):
        svc.record(
            merchant_id=merchant.id,
            memory_type=MemoryType.strategy_outcome,
            content="Dormant customer win-back campaign with 10% discount performed well.",
            importance=0.9,
        )
        hits = svc.retrieve(merchant_id=merchant.id, query="dormant discount campaign", k=3)
        assert len(hits) == 1
        assert "dormant".lower() in hits[0]["content"].lower()
        assert hits[0]["memory_type"] == "strategy_outcome"

    def test_semantic_ranking_with_fake_embeddings(self, db_session, merchant, svc):
        svc.record(
            merchant_id=merchant.id,
            memory_type=MemoryType.campaign_performance,
            content="festival email campaign lifted repeat purchases strongly",
        )
        svc.record(
            merchant_id=merchant.id,
            memory_type=MemoryType.campaign_performance,
            content="sms payment recovery nudge converted poorly last spring",
        )
        hits = svc.retrieve(merchant_id=merchant.id, query="email campaign repeat purchases", k=2)
        assert "email campaign" in hits[0]["content"]

    def test_recency_boost_prefers_recent(self, db_session, merchant, svc):
        svc.record(
            merchant_id=merchant.id,
            memory_type=MemoryType.recommendation,
            content="generic recommendation alpha beta gamma",
            importance=0.5,
        )
        svc.record(
            merchant_id=merchant.id,
            memory_type=MemoryType.recommendation,
            content="generic recommendation alpha beta gamma",
            importance=0.5,
        )
        hits = svc.retrieve(
            merchant_id=merchant.id, query="alpha beta gamma recommendation", k=2
        )
        # identical content/importance ⇒ the newer row must rank first
        assert hits[0]["created_at"] >= hits[1]["created_at"]

    def test_importance_influences_ranking(self, db_session, merchant, svc):
        # Identical content ⇒ semantic + recency equal ⇒ only importance differs
        for importance in (0.95, 0.05):
            svc.record(
                merchant_id=merchant.id,
                memory_type=MemoryType.merchant_preference,
                content="prefers whatsapp over email for campaigns",
                importance=importance,
            )
        hits = svc.retrieve(
            merchant_id=merchant.id, query="prefers whatsapp campaigns", k=2
        )
        assert hits[0]["importance"] == pytest.approx(0.95)
        assert hits[1]["importance"] == pytest.approx(0.05)

    def test_keyword_fallback_without_embeddings(self, db_session, merchant):
        plain = GrowthMemoryService(db_session, embedding_provider=None)
        plain.record(
            merchant_id=merchant.id,
            memory_type=MemoryType.opportunity_history,
            content="payment recovery opportunity detected in March window",
        )
        hits = plain.retrieve(merchant_id=merchant.id, query="recovery march", k=1)
        assert len(hits) == 1

    def test_memory_type_filter(self, db_session, merchant, svc):
        svc.record(merchant_id=merchant.id, memory_type=MemoryType.action_result, content="result row")
        svc.record(merchant_id=merchant.id, memory_type=MemoryType.recommendation, content="advice row")
        hits = svc.retrieve(
            merchant_id=merchant.id, query="row", k=10,
            memory_type=MemoryType.action_result,
        )
        assert {h["memory_type"] for h in hits} == {"action_result"}


class TestCrossMerchantIsolation:
    def test_retrieval_never_leaks_across_merchants(self, db_session, merchant, svc):
        other = Merchant(name="Other", slug=f"oth-{uuid.uuid4().hex[:8]}", email="o@x.com",
                         status=MerchantStatus.active, currency=Currency.INR)
        db_session.add(other); db_session.commit()

        secret = "Merchant A private strategy: margin data and VIP list details"
        svc.record(merchant_id=merchant.id, memory_type=MemoryType.strategy_outcome, content=secret)

        # retrieve as the OTHER merchant — must see nothing
        hits = GrowthMemoryService(db_session, embedding_provider=FakeEmbeddingProvider()).retrieve(
            other.id, query="VIP margin strategy private details", k=10
        )
        assert all(secret not in h["content"] for h in hits)

    def test_same_query_scoped_to_own_memory(self, db_session, merchant, svc):
        own_content = "Merchant A prefers discount campaigns during festivals"
        svc.record(merchant_id=merchant.id, memory_type=MemoryType.merchant_preference, content=own_content)
        hits = svc.retrieve(merchant_id=merchant.id, query="discount festival campaigns", k=5)
        assert any("festivals" in h["content"] for h in hits)


class TestLearningFromResults:
    def test_outcome_variance_recorded(self, db_session, merchant, svc):
        mem = svc.record_action_outcome(
            merchant_id=merchant.id,
            action_type="send_campaign",
            strategy_summary="Target dormant customers with 10% discount",
            expected_revenue=100000.0,
            actual_revenue=132000.0,
        )
        assert mem.outcome_variance_pct == pytest.approx(Decimal("32.00"))
        assert "+32" in mem.content
        assert "better than expected" in mem.content

    def test_underperformance_recorded_honestly(self, db_session, merchant, svc):
        mem = svc.record_action_outcome(
            merchant_id=merchant.id,
            action_type="create_discount",
            strategy_summary="Sitewide 20% off",
            expected_revenue=50000.0,
            actual_revenue=25000.0,
        )
        assert mem.outcome_variance_pct == pytest.approx(Decimal("-50.00"))
        assert "underperformed" in mem.content

    def test_pending_measurement_makes_no_claim(self, db_session, merchant, svc):
        mem = svc.record_action_outcome(
            merchant_id=merchant.id,
            action_type="retry_payment",
            strategy_summary="Recover failed payments",
            expected_revenue=80000.0,
            actual_revenue=None,   # measurement_pending from Phase 4 service
        )
        assert mem.outcome_variance_pct is None
        assert "not yet available" in mem.content
        assert "No outcome claim" in mem.content
        assert mem.memory_metadata["measurement_complete"] is False

    def test_learned_evidence_is_retrievable_for_future_runs(self, db_session, merchant, svc):
        svc.record_action_outcome(
            merchant_id=merchant.id,
            action_type="send_campaign",
            strategy_summary="Dormant customers with 10% discount",
            expected_revenue=100000.0,
            actual_revenue=132000.0,
        )
        hits = svc.retrieve(
            merchant_id=merchant.id, query="dormant discount campaign strategy", k=3,
            memory_type=MemoryType.action_result,
        )
        assert hits and "+32" in hits[0]["content"]


def test_cosine_helper():
    assert _cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert _cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert _cosine([], []) is None
    assert _cosine([1, 0], [1, 0, 0]) is None
