"""
Pydantic schemas for the knowledge ingestion API.

These are the only new types introduced for Task 23 — they define
the request and response shapes for POST /api/ai/ingest.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class IngestRequest(BaseModel):
    """
    Request body for POST /api/ai/ingest.

    merchant_id is optional. When omitted the endpoint uses the first
    available merchant in the database (single-tenant mode).
    """
    merchant_id: uuid.UUID | None = Field(
        default=None,
        description="Merchant UUID to ingest. Omit to use the first merchant.",
    )
    force_reingest: bool = Field(
        default=False,
        description=(
            "When True, re-embed all content even if checksums match. "
            "Useful after embedding model changes. Defaults to False."
        ),
    )


class IngestionSourceCounts(BaseModel):
    """Per-entity-type document counts from one ingestion run."""
    model_config = ConfigDict(from_attributes=False)

    merchant: int = Field(ge=0, description="Merchant overview documents processed")
    product: int = Field(ge=0, description="Product documents processed")
    customer: int = Field(ge=0, description="Customer documents processed")
    order: int = Field(ge=0, description="Order documents processed")
    payment: int = Field(ge=0, description="Payment documents processed")

    @property
    def total(self) -> int:
        return self.merchant + self.product + self.customer + self.order + self.payment


class IngestResponse(BaseModel):
    """Response body for POST /api/ai/ingest."""
    model_config = ConfigDict(from_attributes=False)

    status: str = Field(description="'completed' or 'failed'")
    merchant_id: uuid.UUID = Field(description="Merchant whose data was ingested")
    merchant_name: str = Field(description="Merchant display name")
    documents_processed: IngestionSourceCounts
    message: str = Field(description="Human-readable outcome message")
    completed_at: datetime
