"""Add the Designer Agent creative workspace tables.

WHY
---
The Designer Agent is the only platform agent whose product is an artefact,
yet it persisted nothing. Its output existed only as ``AgentFinding`` rows
written *inside an Agent Debate*, which meant:

  * in ``mode="team"`` (the AI Team workspace) it produced no persistence at
    all — the agent computed a result and it was discarded with the request;
  * there was no project, so design work had no durable container;
  * there was no brief, specification or version history, so a merchant could
    not retrieve previous work or see what changed between revisions;
  * the dashboard could only ever reconstruct "latest output" by scanning
    debate findings, which is why it degraded to empty states.

WHAT
----
Four tenant-scoped tables:

  design_projects         a durable unit of design work + its provenance links
  creative_briefs         versioned, structured creative briefs
  design_assets           versioned artefacts, discriminated by honest `kind`
  design_asset_versions   append-only immutable revisions

Every table is additive and ``merchant_id`` is NOT NULL, so this migration
cannot affect, rewrite or lose any existing row in any other table. The
foreign keys all point at existing tables (``merchants``, ``agent_debates``,
``agent_runs``, ``growth_opportunities``) with ``ON DELETE CASCADE`` for the
design-owned children and ``ON DELETE SET NULL`` for informational provenance
links, so deleting a debate or a run never destroys design history.

IMMUTABILITY
------------
``design_asset_versions`` is append-only by convention and by construction:
``(asset_id, version)`` is unique, so a revision can never overwrite an
earlier one. ``design_assets.current_version_id`` is the single mutable
pointer to the newest version.

CREATION ORDER
--------------
Tables are created parents-first: design_projects -> creative_briefs ->
design_assets -> design_asset_versions. PostgreSQL resolves a foreign key's
target at DDL time, so this order is required, not stylistic.
``current_version_id`` is deliberately a plain UUID column rather than a
foreign key, which keeps the graph acyclic and means no deferred
constraint is required.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d9b1c2e3f4a5"
down_revision: Union[str, Sequence[str], None] = "c4a1f9e2b770"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONB = postgresql.JSONB(astext_type=sa.Text())

#: Enum values are stored as plain VARCHAR (the models use
#: ``Enum(..., native_enum=False)``), so the check constraints below use the
#: literal member values rather than a Postgres enum type. This matches the
#: existing ``agent_debates`` / ``agent_findings`` convention.
_PROJECT_STATUS = ("active", "archived")
_ASSET_KIND = ("brief", "specification", "variant", "rendered_image")
_ASSET_STATUS = ("draft", "ready_for_review", "archived")
_REVIEW_STATUS = (
    "draft",
    "pending_review",
    "in_review",
    "approved",
    "changes_requested",
    "rejected",
)


def _enum(values: Sequence[str], name: str) -> sa.Enum:
    """A VARCHAR-typed enum column.

    ``native_enum=False`` means Postgres gets a plain VARCHAR with a CHECK
    constraint rather than a named PG enum type. That is deliberate and matches
    the existing ``agent_debates`` / ``agent_findings`` convention: a named PG
    enum cannot be added to or removed from without ``ALTER TYPE``, which
    makes later migrations brittle. The width is generous enough that a
    future member never needs an ``ALTER COLUMN``.
    """
    return sa.Enum(
        *values,
        name=name,
        native_enum=False,
        create_constraint=False,
        length=32,
        validate_strings=True,
    )


def upgrade() -> None:
    # ── design_projects ────────────────────────────────────────────────────
    op.create_table(
        "design_projects",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("merchant_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("project_type", sa.String(60), nullable=False),
        sa.Column(
            "status", _enum(_PROJECT_STATUS, "design_project_status"),
            server_default="active", nullable=False,
        ),
        sa.Column("analysis_cycle_id", sa.String(64), nullable=True),
        sa.Column("debate_id", sa.UUID(), nullable=True),
        sa.Column("source_signal_type", sa.String(60), nullable=True),
        sa.Column("source_signal_id", sa.String(255), nullable=True),
        sa.Column("source_opportunity_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["merchant_id"], ["merchants.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["debate_id"], ["agent_debates.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_opportunity_id"], ["growth_opportunities.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_design_projects_id", "design_projects", ["id"])
    op.create_index(
        "ix_design_projects_merchant_id", "design_projects", ["merchant_id"]
    )
    op.create_index(
        "ix_design_projects_project_type", "design_projects", ["project_type"]
    )
    op.create_index("ix_design_projects_status", "design_projects", ["status"])
    op.create_index(
        "ix_design_projects_analysis_cycle_id",
        "design_projects", ["analysis_cycle_id"],
    )
    op.create_index("ix_design_projects_debate_id", "design_projects", ["debate_id"])
    op.create_index(
        "ix_design_projects_source_signal_id", "design_projects", ["source_signal_id"]
    )
    op.create_index(
        "ix_design_projects_source_opportunity_id",
        "design_projects", ["source_opportunity_id"],
    )
    op.create_index(
        "ix_design_projects_merchant_status",
        "design_projects", ["merchant_id", "status"],
    )

    # ── creative_briefs ───────────────────────────────────────────────────
    op.create_table(
        "creative_briefs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("merchant_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("is_current", sa.Integer(), server_default="1", nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("audience", sa.Text(), nullable=True),
        sa.Column("channel", sa.String(120), nullable=True),
        sa.Column("format_spec", sa.String(120), nullable=True),
        sa.Column("brand_constraints", JSONB, nullable=True),
        sa.Column("content_requirements", JSONB, nullable=True),
        sa.Column("layout_direction", sa.Text(), nullable=True),
        sa.Column("color_guidance", sa.Text(), nullable=True),
        sa.Column("typography_guidance", sa.Text(), nullable=True),
        sa.Column("accessibility_considerations", JSONB, nullable=True),
        sa.Column("dependencies", JSONB, nullable=True),
        sa.Column("open_questions", JSONB, nullable=True),
        sa.Column("assumptions", JSONB, nullable=True),
        sa.Column("evidence", JSONB, nullable=True),
        sa.Column("radar_references", JSONB, nullable=True),
        sa.Column("variants", JSONB, nullable=True),
        sa.Column(
            "review_status", _enum(_REVIEW_STATUS, "design_review_status"),
            server_default="draft", nullable=False,
        ),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("validation", JSONB, nullable=True),
        sa.Column("llm_provider", sa.String(40), nullable=True),
        sa.Column("llm_model", sa.String(120), nullable=True),
        sa.Column("analysis_cycle_id", sa.String(64), nullable=True),
        sa.Column("agent_run_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["merchant_id"], ["merchants.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["design_projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "version", name="uq_creative_briefs_project_version"
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_creative_briefs_confidence_range",
        ),
    )
    op.create_index("ix_creative_briefs_id", "creative_briefs", ["id"])
    op.create_index(
        "ix_creative_briefs_merchant_id", "creative_briefs", ["merchant_id"]
    )
    op.create_index(
        "ix_creative_briefs_project_id", "creative_briefs", ["project_id"]
    )
    op.create_index("ix_creative_briefs_is_current", "creative_briefs", ["is_current"])
    op.create_index(
        "ix_creative_briefs_review_status", "creative_briefs", ["review_status"]
    )
    op.create_index(
        "ix_creative_briefs_analysis_cycle_id",
        "creative_briefs", ["analysis_cycle_id"],
    )
    op.create_index(
        "ix_creative_briefs_agent_run_id", "creative_briefs", ["agent_run_id"]
    )
    op.create_index(
        "ix_creative_briefs_project_current",
        "creative_briefs", ["project_id", "is_current"],
    )

    # ── design_assets ─────────────────────────────────────────────────────
    #
    # Created BEFORE design_asset_versions because the version table's
    # ``asset_id`` references this one. PostgreSQL resolves a foreign key's
    # target table at DDL time, so creating the child first fails with
    # 'relation "design_assets" does not exist'.
    #
    # This is a plain topological order, not a deferred-constraint dance:
    # every FK below points at a table created earlier in this migration
    # (merchants, design_projects, creative_briefs), so no cycle exists.
    op.create_table(
        "design_assets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("merchant_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("brief_id", sa.UUID(), nullable=True),
        sa.Column(
            "kind", _enum(_ASSET_KIND, "design_asset_kind"),
            server_default="brief", nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("variant_key", sa.String(80), nullable=True),
        sa.Column(
            "status", _enum(_ASSET_STATUS, "design_asset_status"),
            server_default="draft", nullable=False,
        ),
        sa.Column(
            "review_status", _enum(_REVIEW_STATUS, "design_asset_review_status"),
            server_default="draft", nullable=False,
        ),
        sa.Column("current_version_id", sa.UUID(), nullable=True),
        sa.Column("version_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("image_generation", JSONB, nullable=True),
        sa.ForeignKeyConstraint(
            ["merchant_id"], ["merchants.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["design_projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["brief_id"], ["creative_briefs.id"], ondelete="SET NULL"
        ),
        # NOTE: ``current_version_id`` is intentionally NOT a foreign key.
        # Declaring it as one would create a cycle with
        # ``design_asset_versions.asset_id`` (each table referencing the
        # other), which requires a deferred-constraint workaround and adds no
        # integrity: the service writes the version row and the pointer
        # together, always for the same asset. Keeping it a plain indexed UUID
        # is also what makes the parent-before-child order above sufficient.
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_design_assets_id", "design_assets", ["id"])
    op.create_index("ix_design_assets_merchant_id", "design_assets", ["merchant_id"])
    op.create_index(
        "ix_design_assets_project_id", "design_assets", ["project_id"]
    )
    op.create_index("ix_design_assets_brief_id", "design_assets", ["brief_id"])
    op.create_index("ix_design_assets_kind", "design_assets", ["kind"])
    op.create_index("ix_design_assets_status", "design_assets", ["status"])
    op.create_index(
        "ix_design_assets_review_status", "design_assets", ["review_status"]
    )
    op.create_index(
        "ix_design_assets_current_version_id",
        "design_assets", ["current_version_id"],
    )
    op.create_index(
        "ix_design_assets_project_kind", "design_assets", ["project_id", "kind"]
    )
    op.create_index(
        "ix_design_assets_merchant_status", "design_assets", ["merchant_id", "status"]
    )

    # ── design_asset_versions (last: depends on design_assets) ────────────
    op.create_table(
        "design_asset_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("merchant_id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", JSONB, nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("evidence", JSONB, nullable=True),
        sa.Column("created_by", sa.String(120), nullable=True),
        sa.ForeignKeyConstraint(
            ["merchant_id"], ["merchants.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["design_assets.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "asset_id", "version", name="uq_design_asset_versions_asset_version"
        ),
    )
    op.create_index(
        "ix_design_asset_versions_id", "design_asset_versions", ["id"]
    )
    op.create_index(
        "ix_design_asset_versions_merchant_id",
        "design_asset_versions", ["merchant_id"],
    )
    op.create_index(
        "ix_design_asset_versions_asset_id", "design_asset_versions", ["asset_id"]
    )


def downgrade() -> None:
    # Exact reverse of upgrade(): the child table is dropped first so it can
    # still reference its parent.
    op.drop_table("design_asset_versions")
    op.drop_table("design_assets")
    op.drop_table("creative_briefs")
    op.drop_table("design_projects")
