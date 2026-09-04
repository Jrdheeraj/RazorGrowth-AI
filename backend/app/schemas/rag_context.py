"""Public contract for evidence-grounded RAG context."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RAGContextRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=500)
    window_days: int = Field(default=30, ge=1, le=365)


class RAGContextResponse(BaseModel):
    merchant_id: str
    query: str
    status: str
    data_sufficiency: dict[str, Any]
    verified_facts: list[dict[str, Any]]
    derived_metrics: dict[str, Any]
    retrieved_context: list[dict[str, Any]]
    inference_allowed: bool