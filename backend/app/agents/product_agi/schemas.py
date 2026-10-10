"""Structured LLM output contracts for the Product Agent.

Every autonomous decision the model makes is parsed into one of these
schemas, so raw model output can never drive the run directly. The model
is only ever asked to REASON over structured observations that the
deterministic MCP tools produced.

What the model is NEVER asked for, because it is not the model's to give:

    merchant_id, tenant_id, credentials, approval authority, execution
    authority. Those stay in server-side context. ``affected_product_ids``
    below is a naming aid for the human reviewing the card; every id the
    agent persists is re-validated against the tenant's own catalog before
    it is written.
"""
from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field, RootModel, field_validator

FindingType = Literal[
    "catalog",
    "performance",
    "inventory",
    "content",
    "pricing",
    "bundle",
    "research",
    "data_gap",
]

RecommendationType = Literal[
    "inventory",
    "content",
    "pricing",
    "bundle",
    "merchandising",
    "research",
]

Severity = Literal["info", "low", "medium", "high"]


class Finding(BaseModel):
    """One observation worth showing on the dashboard."""

    type: FindingType = Field(description="Category of observation")
    title: str = Field(max_length=200, description="Short, specific headline")
    description: str = Field(
        max_length=1200,
        description=(
            "What was observed, in one or two sentences. Cite the numbers you "
            "were given. Do not speculate beyond the supplied data."
        ),
    )
    severity: Severity = Field(default="info")
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Your confidence in the observation, 0-1. Omit for a plain "
            "measurement — never attach a fake probability to a fact."
        ),
    )
    evidence_refs: list[str] = Field(
        default_factory=list,
        description=(
            "Verbatim evidence statements from the supplied observations. "
            "Only include statements that were actually given to you."
        ),
    )

    @field_validator("title", "description")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


class Recommendation(BaseModel):
    """One evidence-backed proposal for a human to decide on."""

    type: RecommendationType
    title: str = Field(max_length=200)
    problem: str = Field(
        max_length=1200,
        description="The measured problem this addresses. Use real numbers."
    )
    recommendation: str = Field(
        max_length=1200,
        description="The specific action proposed."
    )
    why_now: str = Field(
        max_length=600,
        description="Why this is worth doing now, grounded in the data you were given.",
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence in this recommendation, 0-1.",
    )
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="Verbatim evidence statements supporting this recommendation.",
    )
    affected_products: list[str] = Field(
        default_factory=list,
        description=(
            "Exact product names from the supplied catalog. Use the names as "
            "given; do not invent products."
        ),
    )
    action_required: bool = Field(
        description="True when a human must approve something to make progress.",
    )
    approval_required: bool = Field(default=True)
    risk: str | None = Field(
        default=None,
        max_length=600,
        description="What could go wrong, or why this could be wrong.",
    )
    expected_impact_known: bool = Field(
        default=False,
        description=(
            "Set true ONLY if the supplied observations contained a "
            "measurable impact figure. When false the platform records the "
            "impact as unavailable — do not guess a rupee amount."
        ),
    )
    expected_impact_text: str | None = Field(
        default=None,
        max_length=600,
        description=(
            "The impact, only when it is given in the observations. Leave null "
            "otherwise."
        ),
    )

    @field_validator("title", "problem", "recommendation", "why_now")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


class AnalysisResult(BaseModel):
    """The agent's structured conclusion for one run."""

    findings: list[Finding] = Field(
        default_factory=list,
        max_length=24,
        description="Observations worth reporting, strongest first.",
    )
    recommendations: list[Recommendation] = Field(
        default_factory=list,
        max_length=8,
        description=(
            "Evidence-backed recommendations. Only include ones whose "
            "problem and evidence are real in the supplied observations."
        ),
    )
    knowledge_gaps: list[str] = Field(
        default_factory=list,
        max_length=12,
        description=(
            "Data the platform does not have that limits this analysis. Be "
            "explicit rather than filling gaps with assumptions."
        ),
    )
    summary: str = Field(
        max_length=800,
        description=(
            "One-paragraph honest summary of what the data shows. State "
            "figure-free if there is no measurable impact."
        ),
    )
    reasoning: str = Field(
        max_length=1200,
        description=(
            "Your reasoning chain: what the data shows, why it matters, what "
            "opportunity exists. Facts and reasoning only — no hidden chain of "
            "thought, no private deliberation."
        ),
    )

    @field_validator("summary", "reasoning")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


class ResearchQuestion(BaseModel):
    """One targeted retrieval question derived from what the agent found."""

    question: str = Field(
        max_length=300,
        description=(
            "A specific question the workspace data could answer, phrased so "
            "a retrieval tool can act on it."
        ),
    )
    rationale: str = Field(default="", max_length=300)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


class ResearchQuestions(RootModel[List[ResearchQuestion]]):
    """A list wrapped as a schema the structured-output provider can use.

    ``generate_structured`` calls ``schema.model_json_schema()``, which only
    exists on pydantic models — a bare ``list[...]`` raises AttributeError.
    ``root`` carries the questions.
    """


__all__ = [
    "AnalysisResult",
    "Finding",
    "FindingType",
    "Recommendation",
    "RecommendationType",
    "ResearchQuestion",
    "ResearchQuestions",
    "Severity",
]