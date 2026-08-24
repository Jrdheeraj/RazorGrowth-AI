"""
KnowledgeRetriever — semantic vector search against knowledge_chunks.

On PostgreSQL + pgvector: uses cosine similarity (<=> operator) for
nearest-neighbour search with an index.

On SQLite (test environment): falls back to keyword LIKE search since
pgvector operators are unavailable. The fallback path is clearly labelled
and does not claim vector similarity scores.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.app.ai.embeddings.base import BaseEmbeddingProvider, EmbeddingError
from backend.app.ai.rag.context import RetrievedContext, RetrievedItem
from backend.app.models.knowledge import KnowledgeChunk, KnowledgeDocument

log = logging.getLogger(__name__)


class KnowledgeRetriever:
    """
    Retrieves knowledge chunks relevant to a query.

    Uses vector similarity when pgvector is available (PostgreSQL).
    Falls back to keyword search on SQLite (test environment only).
    """

    def __init__(
        self,
        db: Session,
        embedding_provider: BaseEmbeddingProvider,
        default_limit: int = 8,
    ) -> None:
        self._db = db
        self._embedder = embedding_provider
        self._default_limit = default_limit

    def retrieve(
        self,
        query: str,
        merchant_id: uuid.UUID,
        *,
        limit: int | None = None,
        source_types: list[str] | None = None,
    ) -> RetrievedContext:
        """
        Retrieve the most relevant knowledge chunks for `query`.

        Args:
            query:        Natural language query.
            merchant_id:  Scope retrieval to this merchant.
            limit:        Max items to return (default: self.default_limit).
            source_types: Filter to specific source types (e.g. ["product", "order"]).

        Returns:
            RetrievedContext with results and provenance metadata.
        """
        k = limit or self._default_limit

        # Determine dialect — choose vector vs keyword path
        dialect = self._db.bind.dialect.name if self._db.bind else "unknown"
        use_vector = (dialect == "postgresql")

        if use_vector:
            return self._vector_retrieve(query, merchant_id, k, source_types)
        else:
            log.debug("Non-PostgreSQL dialect (%s): using keyword fallback retriever", dialect)
            return self._keyword_retrieve(query, merchant_id, k, source_types)

    # ------------------------------------------------------------------ #
    # Vector retrieval (PostgreSQL + pgvector)
    # ------------------------------------------------------------------ #

    def _vector_retrieve(
        self,
        query: str,
        merchant_id: uuid.UUID,
        limit: int,
        source_types: list[str] | None,
    ) -> RetrievedContext:
        try:
            query_embedding = self._embedder.embed_text(query)
        except EmbeddingError as exc:
            log.warning("Embedding query failed, falling back to keyword: %s", exc)
            return self._keyword_retrieve(query, merchant_id, limit, source_types)

        # pgvector cosine distance: <=> returns 0 (identical) to 2 (opposite)
        # similarity = 1 - distance
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

        # Build the SQL with optional source_type filter
        source_filter = ""
        params: dict[str, Any] = {
            "merchant_id": str(merchant_id),
            "limit": limit,
            "embedding": embedding_str,
        }
        if source_types:
            source_filter = "AND kd.source_type = ANY(:source_types)"
            params["source_types"] = source_types

        sql = text(f"""
            SELECT
                kc.id            AS chunk_id,
                kc.content       AS content,
                kc.metadata      AS chunk_metadata,
                kd.id            AS document_id,
                kd.source_type   AS source_type,
                kd.source_id     AS source_id,
                1 - (kc.embedding::vector <=> :embedding::vector) AS similarity
            FROM knowledge_chunks kc
            JOIN knowledge_documents kd ON kd.id = kc.document_id
            WHERE kc.merchant_id = :merchant_id::uuid
              AND kc.embedding IS NOT NULL
              {source_filter}
            ORDER BY kc.embedding::vector <=> :embedding::vector
            LIMIT :limit
        """)

        try:
            rows = self._db.execute(sql, params).fetchall()
        except Exception as exc:
            log.warning("Vector search failed, falling back to keyword: %s", exc)
            return self._keyword_retrieve(query, merchant_id, limit, source_types)

        items = [
            RetrievedItem(
                content=row.content,
                source_type=row.source_type,
                source_id=row.source_id,
                document_id=str(row.document_id),
                chunk_id=str(row.chunk_id),
                similarity=float(row.similarity),
                metadata=row.chunk_metadata or {},
            )
            for row in rows
        ]
        log.debug(
            "Vector retrieval: query=%r merchant=%s results=%d",
            query[:60], merchant_id, len(items),
        )
        return RetrievedContext(query=query, items=items, retrieval_method="vector")

    # ------------------------------------------------------------------ #
    # Keyword fallback retrieval (SQLite / test environment)
    # ------------------------------------------------------------------ #

    def _keyword_retrieve(
        self,
        query: str,
        merchant_id: uuid.UUID,
        limit: int,
        source_types: list[str] | None,
    ) -> RetrievedContext:
        stmt = (
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(KnowledgeChunk.merchant_id == merchant_id)
        )
        if source_types:
            stmt = stmt.where(KnowledgeDocument.source_type.in_(source_types))

        all_chunks = self._db.execute(stmt).all()

        # Simple keyword scoring — count query word hits in content
        query_words = query.lower().split()

        def score(row) -> int:
            text_lower = row[0].content.lower()
            return sum(1 for w in query_words if w in text_lower)

        scored = sorted(all_chunks, key=score, reverse=True)[:limit]

        items = [
            RetrievedItem(
                content=row[0].content,
                source_type=row[1].source_type,
                source_id=row[1].source_id,
                document_id=str(row[1].id),
                chunk_id=str(row[0].id),
                similarity=None,
                metadata=row[0].chunk_metadata or {},
            )
            for row in scored
        ]
        log.debug(
            "Keyword retrieval: query=%r merchant=%s results=%d",
            query[:60], merchant_id, len(items),
        )
        return RetrievedContext(query=query, items=items, retrieval_method="keyword")
