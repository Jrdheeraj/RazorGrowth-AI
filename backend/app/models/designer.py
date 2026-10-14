"""Designer Agent persistence — the creative workspace the agent actually owns.

The Designer Agent is the only platform agent whose product IS an artefact.
Before this module the agent produced a handful of ``AgentFinding`` rows inside
an Agent Debate and nothing else: no project, no brief, no version history, and
no record of what was produced outside a debate. In ``team`` mode it produced
no persistence at all.

Four tables, each with exactly one job:

  ``design_projects``        a durable unit of design work (the container)
  ``creative_briefs``        the validated, structured creative brief
  ``design_assets``          a versioned artefact of a given type
  ``design_asset_versions``  an immutable snapshot of one asset revision

Two deliberate absences:

  * There is NO ``design_approvals`` table. Review state lives on the asset /
    brief (``review_status``) and any action a design output implies becomes
    work through the platform's existing ``agent_actions`` pipeline, so
    approval, execution and audit stay in exactly one place.
  * There is NO image binary. The backend stores no rendered image and has no
    image-generation provider configured; ``design_assets.kind`` makes the
    difference between a *brief*, a *specification* and a *rendered image*
    explicit, and ``image_generation`` status is a real, honest state rather
    than a fabricated URL.

IMMUTABILITY
------------
``design_asset_versions`` is append-only. A new revision writes a NEW row with
an incremented ``version``; it never mutates or deletes the previous one, so
the design history a merchant approved against cannot silently change
underneath them. ``design_assets.current_version_id`` points at the newest
accepted version and is the only mutable pointer.

TENANT SCOPING
--------------
Identical to the rest of the platform: every row is bound to exactly one
merchant and every repository query filters ``merchant_id`` in SQL. Nothing
here reads a merchant from a request body or from model output.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.app.models.enums import (
    DesignAssetKind,
    DesignAssetStatus,
    DesignProjectStatus,
    DesignReviewStatus,
    ImageGenerationStatus,
)

#: Every Designer lifecycle column is a uniform VARCHAR(32).
#:
#: Alembic autogenerate compares column TYPES as well as values, so if each
#: enum inferred its own width (``active`` -> VARCHAR(8), ``changes_requested``
#: -> VARCHAR(18)) the schema would carry a permanent "type changed" diff
#: against its own migration. One shared width removes that entirely, and 32
#: comfortably exceeds the longest member.
#:
#: ``create_constraint=False`` matches the platform's existing convention for
#: lifecycle enums (see ``DebateStatus`` / ``FindingType``): the Python-side
#: ``validate_strings`` is the check, and no per-enum CHECK constraint has to
#: be hand-named and hand-dropped on a future migration.
_ENUM_LENGTH = 32


def _lifecycle(enum_cls: type[enum.Enum]) -> Enum:
    """A VARCHAR(32) lifecycle column, identical to the migration."""
    return Enum(
        enum_cls,
        native_enum=False,
        validate_strings=True,
        create_constraint=False,
        length=_ENUM_LENGTH,
    )


class DesignProject(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A durable unit of design work."""

    __tablename__ = "design_projects"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    #: Free-form kind chosen by the Designer Agent from its objective, e.g.
    #: "brand_identity", "campaign_creative", "checkout_ux".
    project_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    status: Mapped[DesignProjectStatus] = mapped_column(
        _lifecycle(DesignProjectStatus),
        nullable=False,
        default=DesignProjectStatus.active,
        server_default=DesignProjectStatus.active.value,
        index=True,
    )

    #: The REAL shared AI Team analysis cycle this work belongs to. A design
    #: request dispatched through ``POST /api/agents/run`` reuses that cycle
    #: rather than starting a second one, so this is the correlation id.
    analysis_cycle_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True,
    )
    #: The Agent Debate this work belongs to, when produced inside one.
    debate_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_debates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: Growth Radar signal / opportunity this work was prompted by, when the
    #: objective can be traced back to one. Stored, never invented.
    source_signal_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    source_signal_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True,
    )
    source_opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("growth_opportunities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    briefs: Mapped[list["CreativeBrief"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="CreativeBrief.version",
    )
    assets: Mapped[list["DesignAsset"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="DesignAsset.created_at",
    )

    __table_args__ = (
        Index("ix_design_projects_merchant_status", "merchant_id", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<DesignProject {self.project_type} status={self.status}>"


class CreativeBrief(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A validated, structured creative brief.

    ``version`` starts at 1 and increments on every revision. Earlier versions
    are retained: a revision writes a NEW row rather than overwriting, so a
    merchant can always see what changed and why.
    """

    __tablename__ = "creative_briefs"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("design_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    #: False while this is the newest draft; True once superseded.
    is_current: Mapped[bool] = mapped_column(
        Integer, nullable=False, default=1, server_default="1", index=True,
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel: Mapped[str | None] = mapped_column(String(120), nullable=True)
    format_spec: Mapped[str | None] = mapped_column(String(120), nullable=True)
    brand_constraints: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    content_requirements: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    layout_direction: Mapped[str | None] = mapped_column(Text, nullable=True)
    color_guidance: Mapped[str | None] = mapped_column(Text, nullable=True)
    typography_guidance: Mapped[str | None] = mapped_column(Text, nullable=True)
    accessibility_considerations: Mapped[list[Any] | None] = mapped_column(
        JSONB, nullable=True,
    )
    dependencies: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    open_questions: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    assumptions: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)

    #: Provenance. ``evidence`` carries Observed/Derived/Hypothesis/Unknown
    #: tagged statements; ``radar_references`` links back to real signals.
    evidence: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    radar_references: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    #: Structured variants proposed by the agent (not yet separate assets).
    variants: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)

    review_status: Mapped[DesignReviewStatus] = mapped_column(
        _lifecycle(DesignReviewStatus),
        nullable=False,
        default=DesignReviewStatus.draft,
        server_default=DesignReviewStatus.draft.value,
        index=True,
    )
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    confidence: Mapped[float | None] = mapped_column(
        Numeric(5, 4), nullable=True,
    )
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    llm_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    analysis_cycle_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True,
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True,
    )

    project: Mapped[DesignProject] = relationship(back_populates="briefs")

    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_creative_briefs_project_version"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_creative_briefs_confidence_range",
        ),
        Index("ix_creative_briefs_project_current", "project_id", "is_current"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<CreativeBrief v{self.version} {self.title!r}>"


class DesignAsset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A versioned design artefact.

    ``kind`` is the honest discriminator: a *brief*, a *specification* and a
    *rendered image* are different things and are never conflated. An asset of
    kind ``rendered_image`` only exists if a real image was produced — this
    build has no image-generation provider, so none can be created, and
    ``image_generation.status`` reports ``unavailable`` honestly.
    """

    __tablename__ = "design_assets"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("design_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    brief_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("creative_briefs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    kind: Mapped[DesignAssetKind] = mapped_column(
        _lifecycle(DesignAssetKind),
        nullable=False,
        default=DesignAssetKind.brief,
        server_default=DesignAssetKind.brief.value,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    variant_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[DesignAssetStatus] = mapped_column(
        _lifecycle(DesignAssetStatus),
        nullable=False,
        default=DesignAssetStatus.draft,
        server_default=DesignAssetStatus.draft.value,
        index=True,
    )
    review_status: Mapped[DesignReviewStatus] = mapped_column(
        _lifecycle(DesignReviewStatus),
        nullable=False,
        default=DesignReviewStatus.draft,
        server_default=DesignReviewStatus.draft.value,
        index=True,
    )

    #: Newest version. Deliberately NOT a foreign key.
    #:
    #: Declaring it as one creates a circular constraint (asset -> versions
    #: -> asset), which SQLite cannot drop in order and which makes the schema
    #: harder to reason about for no integrity gain: the service that writes
    #: both rows is the only writer, and it always sets the pointer to a
    #: version it has just inserted for THIS asset. A plain indexed UUID keeps
    #: the pointer without the cycle.
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True,
    )
    version_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )

    #: Honest image-generation state. ``unavailable`` means no provider is
    #: configured — it never means "we drew a placeholder".
    image_generation: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True,
    )

    project: Mapped[DesignProject] = relationship(back_populates="assets")
    versions: Mapped[list["DesignAssetVersion"]] = relationship(
        back_populates="asset",
        cascade="all, delete-orphan",
        order_by="DesignAssetVersion.version",
        # Stated explicitly so the owning side is unambiguous even though
        # ``current_version_id`` is no longer a foreign key.
        foreign_keys="DesignAssetVersion.asset_id",
    )

    __table_args__ = (
        Index(
            "ix_design_assets_project_kind", "project_id", "kind",
        ),
        Index("ix_design_assets_merchant_status", "merchant_id", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<DesignAsset {self.kind} {self.title!r} v{self.version_count}>"


class DesignAssetVersion(UUIDPrimaryKeyMixin, Base):
    """One immutable revision of a design asset.

    Append-only. Rows are never updated in place and never deleted while the
    parent asset exists, so a revision cannot rewrite history.
    """

    __tablename__ = "design_asset_versions"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("design_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: The full structured content of this revision.
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)

    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    #: The parent asset. ``asset_id`` is the owning side — NOT
    #: ``design_assets.current_version_id``, which is a forward pointer to
    #: the newest version and would otherwise create an ambiguous join.
    asset: Mapped[DesignAsset] = relationship(
        back_populates="versions",
        foreign_keys="DesignAssetVersion.asset_id",
    )
    __table_args__ = (
        UniqueConstraint("asset_id", "version", name="uq_design_asset_versions_asset_version"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<DesignAssetVersion asset={self.asset_id} v{self.version}>"


#: The image-generation state a Designer asset carries when no provider is
#: configured. Exposed by the service so the dashboard can render a truthful
#: "setup required" state instead of implying a rendered creative exists.
IMAGE_GENERATION_UNAVAILABLE: dict[str, Any] = {
    "status": ImageGenerationStatus.unavailable.value,
    "provider": None,
    "reason": (
        "No image-generation provider is configured for this workspace. "
        "RazorGrowth AI ships no image model by default; briefs, "
        "specifications and variants are produced as structured text."
    ),
    "asset_reference": None,
}


__all__ = [
    "IMAGE_GENERATION_UNAVAILABLE",
    "CreativeBrief",
    "DesignAsset",
    "DesignAssetVersion",
    "DesignProject",
]
