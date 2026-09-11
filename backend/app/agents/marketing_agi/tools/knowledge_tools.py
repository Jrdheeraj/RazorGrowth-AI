"""Agentic RAG retrieval tool — knowledge-store search with provenance.

The MarketingAGI agentic RAG loop (backend/app/agents/marketing_agi/rag.py)
uses this tool as one retrieval strategy among several (SQL analytics,
memory recall, campaign history). The knowledge store itself is the
platform's pgvector store with its SQLite keyword fallback for tests.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.app.ai.rag.retriever import KnowledgeRetriever
from backend.app.ai.embeddings.base import BaseEmbeddingProvider
from backend.app.agents.marketing_agi.tools.registry import ToolSpec

log = logging.getLogger(__name__)

KNOWLEDGE_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="search_knowledge_store",
        category="knowledge",
        description=(
            "Semantic search over the merchant's ingested knowledge "
            "(products, customers, orders, payments as documents)."
        ),
        capabilities=["vector_retrieval", "semantic_search"],
    ),
]


def register(registry) -> None:
    from backend.app.agents.marketing_agi.tools.registry import ToolContext

    class _NullEmbedder(BaseEmbeddingProvider):
        """Never used — retriever requires a provider object; the real one
        is preferred and this makes the tool constructible without one."""

        @property
        def dimensions(self) -> int:
            return 1536

        def embed_text(self, text: str) -> list[float]:
            raise RuntimeError("NO_EMBEDDING_PROVIDER")

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("NO_EMBEDDING_PROVIDER")

    def _factory(ctx: ToolContext):
        def call(query: str, limit: int = 8, source_types: list[str] | None = None):
            provider = ctx.embedding_provider or _NullEmbedder()
            retriever = KnowledgeRetriever(ctx.db, provider, default_limit=limit)
            context = retriever.retrieve(
                query, ctx.merchant_id, limit=limit, source_types=source_types
            )
            return {
                "query": query,
                "retrieval_method": context.retrieval_method,
                "item_count": len(context.items),
                "items": [
                    {
                        "content": item.content[:600],
                        "source_type": item.source_type,
                        "source_id": item.source_id,
                        "similarity": item.similarity,
                    }
                    for item in context.items
                ],
            }
        return call

    registry.register(KNOWLEDGE_TOOLS[0], _factory)
