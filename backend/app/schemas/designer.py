"""Designer Agent contracts — structured LLM output AND API request/response.

Two distinct concerns live here because they must never be confused:

  1. ``CreativeBriefSpec`` and friends are STRUCTURED OUTPUT contracts. The
     Designer Agent's model is asked to reason over real observations and its
     answer is parsed into one of these before anything is persisted. A parse
     failure means the run records an error — it never means a partial or
     invented brief is stored.

  2. The ``*Request`` / ``*Response`` models are the HTTP surface. They mirror
     the ORM models with ``ConfigDict(from_attributes=True)``, matching the
     convention in every other schema module.

EVIDENCE IS TYPED, NOT FREE TEXT
--------------------------------
Every claim carries a ``basis`` from ``EvidenceBasis``:

  observed  directly supported by a stored record or real tool output
  derived   calculated from observed values
  hypothesis a proposed explanation that has NOT been measured
  unknown   information the agent does not have

This is what makes "do not state that a design change increases conversion"
enforceable rather than aspirational: a model asked for an expected-impact
claim must mark it ``hypothesis``, and validation rejects a measured claim
with no observed backing.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator

from backend.app.models.enums import (
    DesignAssetKind,
    DesignAssetStatus,
    DesignProjectStatus,
    DesignReviewStatus,
    ImageGenerationStatus,
)

EvidenceBasis = Literal["observed", "derived", "hypothesis", "unknown"]

#: The design work types the agent can classify an objective into.
DesignProjectType = Literal[
    "brand_identity",
    "campaign_creative",
    "social_content",
    "advertising_concept",
    "landing_page",
    "product_page",
    "checkout_ux",
    "messaging",
    "design_experiment",
]


# ══════════════════════════════════════════════════════════════════════════
# Structured model output
# ══════════════════════════════════════════════════════════════════════════


class Evidence(BaseModel):
    """One provenance-tagged statement.

    ``basis`` is the single most important field in this module: it is what
    separates a fact the platform can prove from a guess the model likes.
    """

    statement: str = Field(
        max_length=600,
        description=(
            "One sentence. If observed, it must restate a number or record you "
            "were given — do not paraphrase into something stronger."
        ),
    )
    basis: EvidenceBasis = Field(
        description=(
            "observed = directly supported by a supplied record or tool "
            "output; derived = calculated from observed values; "
            "hypothesis = proposed, NOT measured; unknown = not available."
        ),
    )
    source: str | None = Field(
        default=None,
        max_length=200,
        description="Where the observation came from, e.g. 'payments', 'radar'.",
    )
    value: float | None = Field(
        default=None, description="The measured number, when there is exactly one.",
    )

    @field_validator("statement")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("statement must not be blank")
        return v.strip()

    @field_validator("basis")
    @classmethod
    def _valid_basis(cls, v: str) -> str:
        if v not in {"observed", "derived", "hypothesis", "unknown"}:
            raise ValueError(f"unsupported evidence basis: {v!r}")
        return v


class ColorGuidance(BaseModel):
    """Colour direction. Only populated when brand context actually exists."""

    palette: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Hex tokens you were given. Do not invent brand colours.",
    )
    rationale: str | None = Field(default=None, max_length=400)
    basis: EvidenceBasis = "unknown"

    @field_validator("palette")
    @classmethod
    def _hex_only(cls, v: list[str]) -> list[str]:
        for c in v:
            if not (len(c) in (4, 7, 9) and c.startswith("#")):
                raise ValueError(f"colour must be a hex token, got {c!r}")
        return v


class DesignVariant(BaseModel):
    """One structured creative or UX variant."""

    variant_key: str = Field(
        max_length=80,
        description="Short stable key, e.g. 'control', 'variant_a'.",
    )
    title: str = Field(max_length=200)
    objective: str = Field(max_length=600)
    differences: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="What actually differs from the baseline concept.",
    )
    intended_audience: str | None = Field(default=None, max_length=300)
    channel: str | None = Field(default=None, max_length=120)
    rationale: str = Field(max_length=800)
    trade_offs: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Honest costs of this variant, not just benefits.",
    )
    evaluation_method: str = Field(
        max_length=500,
        description=(
            "How this should be evaluated. Never state an expected result — "
            "propose the measurement."
        ),
    )
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_refs: list[int] = Field(
        default_factory=list,
        max_length=20,
        description="Indices into the supplied observation list, 0-based.",
    )

    @field_validator("variant_key", "title", "objective", "rationale", "evaluation_method")
    @classmethod
    def _required(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


class UXFinding(BaseModel):
    """A structured UX observation.

    ``expected_impact_direction`` is deliberately coarse (helps / hurts /
    neutral). The model may NOT assert a conversion lift, because a design
    change that has not shipped cannot have a measured effect.
    """

    title: str = Field(max_length=200)
    observed_issue: str = Field(max_length=800)
    affected_experience: str = Field(max_length=200)
    user_impact_hypothesis: str = Field(
        max_length=600,
        description="Why this may hurt users. A hypothesis, not a measurement.",
    )
    proposed_improvement: str = Field(max_length=800)
    expected_impact_direction: Literal["helps", "hurts", "neutral"] = "neutral"
    expected_impact_magnitude: Literal["low", "medium", "high"] = "low"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_refs: list[int] = Field(default_factory=list, max_length=20)
    validation_recommendation: str | None = Field(default=None, max_length=500)
    product_handoff: str | None = Field(
        default=None,
        max_length=600,
        description="What the Product Agent would need to evaluate this.",
    )

    @field_validator("title", "observed_issue", "proposed_improvement")
    @classmethod
    def _required(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


class CreativeBriefSpec(BaseModel):
    """The validated structured brief the Designer Agent produces.

    The model is asked to fill this in from real supplied observations. Every
    field is optional except the ones that make a brief a brief; anything the
    agent does not know stays ``None`` or an empty list rather than being
    invented, and lands in ``unknown_context`` so the gap is visible.
    """

    title: str = Field(max_length=200)
    objective: str = Field(max_length=800)
    project_type: DesignProjectType
    audience: str | None = Field(default=None, max_length=500)
    channel: str | None = Field(default=None, max_length=120)
    format_spec: str | None = Field(default=None, max_length=120)
    brand_constraints: list[str] = Field(default_factory=list, max_length=12)
    content_requirements: list[str] = Field(default_factory=list, max_length=12)
    layout_direction: str | None = Field(default=None, max_length=800)
    color_guidance: ColorGuidance | None = Field(default=None)
    typography_guidance: str | None = Field(default=None, max_length=400)
    accessibility_considerations: list[str] = Field(default_factory=list, max_length=12)
    variants: list[DesignVariant] = Field(
        default_factory=list,
        max_length=6,
        description="Distinct creative directions. Empty is honest and valid.",
    )
    ux_findings: list[UXFinding] = Field(default_factory=list, max_length=10)
    dependencies: list[str] = Field(default_factory=list, max_length=12)
    open_questions: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="What must be answered before this can be built.",
    )
    assumptions: list[str] = Field(default_factory=list, max_length=12)
    unknown_context: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="Required information the agent did not have.",
    )
    evidence: list[Evidence] = Field(default_factory=list, max_length=30)
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Confidence in the BRIEF, not in a business outcome. Omit when the "
            "observations were too thin to justify any number."
        ),
    )

    @field_validator("title", "objective")
    @classmethod
    def _required(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be blank")
        return v.strip()

    @field_validator("variants")
    @classmethod
    def _distinct_variant_keys(cls, v: list[DesignVariant]) -> list[DesignVariant]:
        keys = [x.variant_key for x in v]
        if len(keys) != len(set(keys)):
            raise ValueError("variant_key values must be unique within a brief")
        return v

    @field_validator("evidence")
    @classmethod
    def _at_least_one_observed_or_derived(
        cls, v: list[Evidence]
    ) -> list[Evidence]:
        """A brief asserting only hypotheses/unknowns is not a brief.

        Requiring at least one grounded statement is the structural guard
        against a model producing confident output from nothing. When the
        agent genuinely has no observations the run records
        ``INSUFFICIENT_EVIDENCE`` instead of persisting this.
        """
        if v and not any(e.basis in ("observed", "derived") for e in v):
            raise ValueError(
                "a brief needs at least one observed or derived evidence "
                "statement; hypotheses and unknowns alone are not a brief"
            )
        return v


class DesignerAnalysis(BaseModel):
    """Root wrapper: the agent's complete structured answer for one run.

    ``RootModel`` is required because ``generate_structured`` calls
    ``schema.model_json_schema()``, which only exists on a Pydantic model —
    and the agent needs a single object (brief + optional UX findings), not a
    bare list.
    """

    brief: CreativeBriefSpec
    handoff_notes: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Free-form notes per receiving agent. Content only — never an "
            "instruction to execute anything."
        ),
    )


class DesignerOutput(BaseModel):
    """Bounded structured output for the brief-generation call."""

    brief: CreativeBriefSpec


class UXAuditResult(BaseModel):
    """Bounded structured output for the UX audit call.

    An empty ``findings`` list is a legitimate, honest answer meaning "the
    observations do not support a UX finding", so it is not coerced into an
    error — but it is never padded with invented issues to look productive.
    """

    findings: list[UXFinding] = Field(default_factory=list, max_length=10)


# ══════════════════════════════════════════════════════════════════════════
# HTTP request / response
# ══════════════════════════════════════════════════════════════════════════


class DesignProjectCreate(BaseModel):
    objective: str = Field(min_length=8, max_length=2000)
    title: str | None = Field(default=None, max_length=200)
    project_type: DesignProjectType | None = None
    analysis_cycle_id: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Existing AI Team cycle to attach this to. Never starts a new "
            "cycle — the orchestrator owns cycle creation."
        ),
    )

    @field_validator("objective")
    @classmethod
    def _objective_meaningful(cls, v: str) -> str:
        if len(v.strip()) < 8:
            raise ValueError("objective must describe an actual design request")
        return v.strip()


class DesignProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    objective: str | None = Field(default=None, min_length=8, max_length=2000)
    status: DesignProjectStatus | None = None


class DesignProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    merchant_id: uuid.UUID
    title: str
    objective: str
    project_type: str
    status: DesignProjectStatus
    analysis_cycle_id: str | None
    debate_id: uuid.UUID | None
    source_signal_type: str | None
    source_signal_id: str | None
    source_opportunity_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class DesignProjectListResponse(BaseModel):
    projects: list[DesignProjectResponse]
    total: int


class CreativeBriefResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    version: int
    is_current: int
    title: str
    objective: str
    audience: str | None
    channel: str | None
    format_spec: str | None
    brand_constraints: list[Any] | None
    content_requirements: list[Any] | None
    layout_direction: str | None
    color_guidance: str | None
    typography_guidance: str | None
    accessibility_considerations: list[Any] | None
    dependencies: list[Any] | None
    open_questions: list[Any] | None
    assumptions: list[Any] | None
    evidence: list[Any] | None
    radar_references: list[Any] | None
    variants: list[Any] | None
    review_status: DesignReviewStatus
    review_notes: str | None
    confidence: float | None
    validation: dict[str, Any] | None
    llm_provider: str | None
    llm_model: str | None
    analysis_cycle_id: str | None
    agent_run_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class CreativeBriefListResponse(BaseModel):
    briefs: list[CreativeBriefResponse]
    total: int


class DesignAssetVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_id: uuid.UUID
    version: int
    content: dict[str, Any]
    rationale: str | None
    change_summary: str | None
    evidence: list[Any] | None
    created_by: str | None
    created_at: datetime


class DesignAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    merchant_id: uuid.UUID
    project_id: uuid.UUID
    brief_id: uuid.UUID | None
    kind: DesignAssetKind
    title: str
    variant_key: str | None
    status: DesignAssetStatus
    review_status: DesignReviewStatus
    current_version_id: uuid.UUID | None
    version_count: int
    image_generation: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class DesignAssetVersionListResponse(BaseModel):
    asset: DesignAssetResponse
    versions: list[DesignAssetVersionResponse]


class DesignAssetListResponse(BaseModel):
    assets: list[DesignAssetResponse]
    total: int


class AssetRevisionRequest(BaseModel):
    """Create a NEW immutable revision of an existing asset."""

    content: dict[str, Any] = Field(min_length=1)
    change_summary: str = Field(min_length=3, max_length=600)
    rationale: str | None = Field(default=None, max_length=1000)


class ReviewDecisionRequest(BaseModel):
    """A human review decision.

    Recorded through the existing review conventions. The agent can never
    call this — a review decision is always a human act.
    """

    decision: Literal["approved", "changes_requested", "rejected"]
    notes: str | None = Field(default=None, max_length=1000)


class UXAuditRequest(BaseModel):
    """Run a UX audit over whatever authorized context exists."""

    objective: str = Field(min_length=8, max_length=2000)
    project_id: uuid.UUID | None = None
    window_days: int = Field(default=30, ge=1, le=365)


class UXAuditResponse(BaseModel):
    findings: list[UXFinding]
    evidence: list[Evidence]
    #: Real signals/opportunities the audit drew on, when any existed.
    radar_references: list[dict[str, Any]]
    #: True only when real authorized observations backed the findings.
    sufficient_context: bool
    #: Why an audit could not produce findings, when it could not. None means
    #: the audit ran on real context and returned whatever it honestly found —
    #: including an empty list.
    unavailable_reason: str | None = None
    data_sufficiency: dict[str, Any] | None = None


class DesignerMetric(BaseModel):
    key: str
    label: str
    value: int
    hint: str


class DesignerStatusResponse(BaseModel):
    """Dashboard status. Every value is derived from persisted records."""

    agent_registered: bool
    agent_description: str | None
    capabilities: list[dict[str, Any]]
    #: Honest external-integration state per provider. A provider is never
    #: reported connected unless a real IntegrationConnection row says so.
    integrations: list[dict[str, Any]]
    image_generation: dict[str, Any]
    latest_project: DesignProjectResponse | None
    latest_brief: CreativeBriefResponse | None
    metrics: list[DesignerMetric]
    counts: dict[str, int]
    last_updated: datetime


class DesignerActivityItem(BaseModel):
    id: str
    kind: Literal["project", "brief", "asset", "run", "review"]
    title: str
    detail: str | None
    status: str | None
    at: datetime | None


class DesignerActivityResponse(BaseModel):
    items: list[DesignerActivityItem]


class HandoffRequest(BaseModel):
    """Hand a structured brief to another workflow.

    The target must be an EXISTING platform destination. There is no Designer
    Agent approval engine here: a handoff creates a structured record and, for
    the action types the platform actually supports, a proposed
    ``agent_actions`` row that faces the normal approval gate.
    """

    target: Literal["marketing_agent", "product_agent", "software_agent", "manager_agent"]
    brief_id: uuid.UUID
    note: str | None = Field(default=None, max_length=1000)
    #: Only these action types exist in the platform; anything else is
    #: refused rather than invented.
    proposed_action_type: Literal["generate_opportunity"] | None = None


class HandoffResponse(BaseModel):
    handoff_id: uuid.UUID
    target: str
    status: str
    brief_id: uuid.UUID
    created_at: datetime
    #: The proposed action id, when one was created. The action still faces
    #: the full approval + EXECUTION_ENABLED gate.
    action_id: uuid.UUID | None = None


__all__ = [
    "AssetRevisionRequest",
    "ColorGuidance",
    "CreativeBriefListResponse",
    "CreativeBriefResponse",
    "CreativeBriefSpec",
    "DesignAssetKind",
    "DesignAssetListResponse",
    "DesignAssetResponse",
    "DesignAssetVersionListResponse",
    "DesignAssetVersionResponse",
    "DesignProjectCreate",
    "DesignProjectListResponse",
    "DesignProjectResponse",
    "DesignProjectType",
    "DesignProjectUpdate",
    "DesignVariant",
    "DesignerActivityItem",
    "DesignerActivityResponse",
    "DesignerAnalysis",
    "DesignerMetric",
    "DesignerOutput",
    "DesignerStatusResponse",
    "Evidence",
    "EvidenceBasis",
    "HandoffRequest",
    "HandoffResponse",
    "ImageGenerationStatus",
    "ReviewDecisionRequest",
    "UXAuditRequest",
    "UXAuditResponse",
    "UXAuditResult",
    "UXFinding",
]
