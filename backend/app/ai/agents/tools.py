"""
Agentic retrieval tools — ALL read-only.

Each tool uses existing repositories/services so there is no duplicated
database access logic.

Safety contract (Phase 3):
  ✓ Read products, customers, orders, payments, merchant context
  ✗ Create payments, refunds, payment links, orders, campaigns

Financial mutation tools will be added in Phase 4+ behind guardrails.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from backend.app.ai.rag.context import RetrievedContext, RetrievedItem
from backend.app.ai.rag.retriever import KnowledgeRetriever
from backend.app.ai.embeddings.base import BaseEmbeddingProvider
from backend.app.models.enums import PaymentStatus
from backend.app.repositories.customer import CustomerRepository
from backend.app.repositories.merchant import MerchantRepository
from backend.app.repositories.order import OrderRepository
from backend.app.repositories.payment import PaymentRepository
from backend.app.repositories.product import ProductRepository

log = logging.getLogger(__name__)


class AgentToolkit:
    """
    Read-only toolkit for the growth analysis agent.

    All methods return structured data and a human-readable summary.
    They never mutate commerce data.
    """

    def __init__(
        self,
        db: Session,
        merchant_id: uuid.UUID,
        embedding_provider: BaseEmbeddingProvider,
    ) -> None:
        self._db = db
        self._merchant_id = merchant_id
        self._retriever = KnowledgeRetriever(db, embedding_provider)
        self._merchant_repo = MerchantRepository(db)
        self._product_repo = ProductRepository(db)
        self._customer_repo = CustomerRepository(db)
        self._order_repo = OrderRepository(db)
        self._payment_repo = PaymentRepository(db)

    # ------------------------------------------------------------------ #
    # Tool registry — maps tool_name to method
    # ------------------------------------------------------------------ #

    AVAILABLE_TOOLS = {
        "search_knowledge",
        "get_merchant_context",
        "get_failed_payments",
        "get_product",
        "get_customer_segments",
        "get_order_patterns",
    }

    def call(self, tool_name: str, params: dict[str, Any]) -> tuple[RetrievedContext, str]:
        """
        Dispatch to the named tool.

        Returns (RetrievedContext, summary_string).
        Raises ToolError if tool_name is unknown or params are invalid.
        """
        if tool_name not in self.AVAILABLE_TOOLS:
            raise ToolError(f"Unknown tool: {tool_name!r}. Available: {self.AVAILABLE_TOOLS}")

        method = getattr(self, f"_tool_{tool_name}")
        log.info("Tool invocation: %s params=%s", tool_name, {k: v for k, v in params.items() if k != "api_key"})
        return method(**params)

    # ------------------------------------------------------------------ #
    # Tool implementations
    # ------------------------------------------------------------------ #

    def _tool_search_knowledge(
        self,
        query: str,
        limit: int = 8,
        source_types: list[str] | None = None,
    ) -> tuple[RetrievedContext, str]:
        """Semantic search across all merchant knowledge."""
        ctx = self._retriever.retrieve(
            query, self._merchant_id, limit=limit, source_types=source_types
        )
        summary = (
            f"search_knowledge('{query[:60]}'): {len(ctx.items)} items retrieved "
            f"via {ctx.retrieval_method}"
        )
        return ctx, summary

    def _tool_get_merchant_context(self, **_) -> tuple[RetrievedContext, str]:
        """Retrieve the merchant overview knowledge document."""
        ctx = self._retriever.retrieve(
            "merchant overview revenue customers products",
            self._merchant_id,
            limit=1,
            source_types=["merchant"],
        )
        summary = f"get_merchant_context: retrieved {len(ctx.items)} merchant overview doc(s)"
        return ctx, summary

    def _tool_get_failed_payments(self, limit: int = 20, **_) -> tuple[RetrievedContext, str]:
        """Get failed payment knowledge chunks."""
        ctx = self._retriever.retrieve(
            "failed payment insufficient funds error",
            self._merchant_id,
            limit=limit,
            source_types=["payment"],
        )
        # Also query DB directly for count and total at-risk amount
        failed = self._payment_repo.list_failed_by_merchant(self._merchant_id)
        total_at_risk = sum(p.amount for p in failed) if failed else 0
        summary = (
            f"get_failed_payments: {len(failed)} failed payments, "
            f"INR {total_at_risk:.2f} at risk. {len(ctx.items)} knowledge chunks retrieved."
        )
        # Augment context items with structured payment data
        extra_items = []
        for p in failed[:limit]:
            extra_items.append(
                RetrievedItem(
                    content=(
                        f"Failed payment of INR {p.amount} for order {p.order_id}. "
                        f"Failure: {p.failure_code or 'unknown'}. "
                        f"Reason: {p.failure_reason or 'N/A'}"
                    ),
                    source_type="payment",
                    source_id=str(p.id),
                    document_id=str(p.id),
                    chunk_id=str(p.id),
                    similarity=None,
                    metadata={
                        "amount": float(p.amount),
                        "failure_code": p.failure_code,
                        "order_id": str(p.order_id),
                    },
                )
            )
        ctx.items = extra_items or ctx.items
        return ctx, summary

    def _tool_get_product(self, query: str = "", limit: int = 5, **_) -> tuple[RetrievedContext, str]:
        """Retrieve product knowledge by keyword."""
        ctx = self._retriever.retrieve(
            query or "product catalog",
            self._merchant_id,
            limit=limit,
            source_types=["product"],
        )
        summary = f"get_product('{query[:60]}'): {len(ctx.items)} product chunks retrieved"
        return ctx, summary

    def _tool_get_customer_segments(self, limit: int = 10, **_) -> tuple[RetrievedContext, str]:
        """Retrieve customer segment overview."""
        from backend.app.models.enums import CustomerSegment
        from sqlalchemy import func, select
        from backend.app.models.customer import Customer

        # Compute segment stats directly
        rows = self._db.execute(
            select(
                Customer.segment,
                func.count(Customer.id).label("cnt"),
                func.coalesce(func.sum(Customer.total_spend), 0).label("spend"),
            )
            .where(Customer.merchant_id == self._merchant_id)
            .group_by(Customer.segment)
        ).all()

        segment_lines = []
        for row in rows:
            seg = row.segment.value if hasattr(row.segment, "value") else str(row.segment)
            segment_lines.append(f"{seg}: {row.cnt} customers, INR {row.spend:.2f} total spend")

        content = "Customer Segment Overview:\n" + "\n".join(segment_lines)
        item = RetrievedItem(
            content=content,
            source_type="customer_segments",
            source_id=str(self._merchant_id),
            document_id=str(self._merchant_id),
            chunk_id="segment_overview",
            similarity=None,
            metadata={"rows": [{"segment": r.segment, "count": r.cnt, "spend": float(r.spend)} for r in rows]},
        )
        ctx = RetrievedContext(
            query="customer segments",
            items=[item],
            retrieval_method="db_aggregate",
        )
        summary = f"get_customer_segments: {len(rows)} segments aggregated"
        return ctx, summary

    def _tool_get_order_patterns(self, limit: int = 10, **_) -> tuple[RetrievedContext, str]:
        """Retrieve order pattern analysis — top products by volume and AOV."""
        from sqlalchemy import func, select
        from backend.app.models.order import Order, OrderItem
        from backend.app.models.product import Product

        # Top products by order volume
        top_products = self._db.execute(
            select(
                Product.name,
                func.count(OrderItem.id).label("cnt"),
                func.sum(OrderItem.line_total).label("revenue"),
            )
            .join(OrderItem, OrderItem.product_id == Product.id)
            .join(Order, Order.id == OrderItem.order_id)
            .where(Order.merchant_id == self._merchant_id)
            .group_by(Product.name)
            .order_by(func.count(OrderItem.id).desc())
            .limit(limit)
        ).all()

        lines = ["Top products by order volume:"]
        for row in top_products:
            lines.append(f"  {row.name}: {row.cnt} orders, INR {row.revenue:.2f} revenue")

        # AOV
        aov_row = self._db.execute(
            select(func.avg(Order.total).label("aov"))
            .where(Order.merchant_id == self._merchant_id)
        ).first()
        aov = float(aov_row.aov) if aov_row and aov_row.aov else 0.0
        lines.append(f"Average order value: INR {aov:.2f}")

        content = "\n".join(lines)
        item = RetrievedItem(
            content=content,
            source_type="order_patterns",
            source_id=str(self._merchant_id),
            document_id=str(self._merchant_id),
            chunk_id="order_patterns",
            similarity=None,
            metadata={
                "top_products": [{"name": r.name, "order_count": r.cnt, "revenue": float(r.revenue)} for r in top_products],
                "average_order_value": aov,
            },
        )
        ctx = RetrievedContext(
            query="order patterns",
            items=[item],
            retrieval_method="db_aggregate",
        )
        summary = f"get_order_patterns: {len(top_products)} top products, AOV INR {aov:.2f}"
        return ctx, summary


class ToolError(Exception):
    """Raised when a tool call fails."""
