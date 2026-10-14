"""Add the rendered_assets table — image bytes for Designer Agent outputs.

WHY
---
The Designer Agent stores structured briefs, specifications and variants as
text. When image generation is enabled it also produces an actual JPEG, and
that JPEG has to go somewhere durable.

It does NOT go into ``design_assets`` or ``design_asset_versions``. Those two
tables are append-only, JSONB-shaped records kept cheap to list, diff and
version; a 1024x1024 JPEG is ~100-200 KB and would bloat every brief query
in the product. So the bytes live in this dedicated table, linked to BOTH the
asset and the exact immutable version that produced them.

WHAT
----
One new table:

  rendered_assets   merchant-scoped image bytes + the metadata needed to
                    describe, verify and serve them (content type, size,
                    SHA-256, width/height, provider, model, steps)

RELATIONSHIP TO THE EXISTING DESIGN TABLES
------------------------------------------
  design_assets   1 --- n rendered_assets
  design_asset_versions 1 --- 1 rendered_assets   (uq_rendered_assets_version_id)

The 1:1 with a version is what keeps bytes and metadata consistent: an image
can only exist for a version that already exists, and a version owns at most
one image. Regenerating an image creates a NEW version plus a NEW row, so
earlier bytes are never overwritten — the append-only semantics of
``design_asset_versions`` are preserved rather than bypassed.

SAFETY ON EXISTING DATA
-----------------------
Purely additive. This migration creates one new table and touches no existing
table, column, row or index, so it cannot affect, rewrite or lose any
merchant data. Every FK uses ON DELETE CASCADE so a deleted design project
takes its images with it — no orphaned blob, no orphan row.

CREATION ORDER
--------------
This table references ``design_assets`` and ``design_asset_versions``, both of
which are created by revision d9b1c2e3f4a5 (the immediate parent). PostgreSQL
resolves a foreign key's target at DDL time, so a single top-level CREATE is
correct here — there is no intra-migration ordering to get wrong and no
circular dependency, because nothing in this file references back into it.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c2e7a41f9b60"
down_revision: Union[str, Sequence[str], None] = "d9b1c2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rendered_assets",
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
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("version_id", sa.UUID(), nullable=False),
        # BYTEA, not TEXT/base64: the payload is binary end to end and is only
        # base64-encoded again at the HTTP response boundary, if ever.
        sa.Column("image_bytes", sa.LargeBinary(), nullable=False),
        sa.Column(
            "content_type", sa.String(60),
            server_default="image/jpeg", nullable=False,
        ),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column(
            "provider", sa.String(60),
            server_default="cloudflare", nullable=False,
        ),
        sa.Column(
            "model", sa.String(120),
            server_default="cloudflare-flux-1-schnell", nullable=False,
        ),
        sa.Column("steps", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(120), nullable=True),
        sa.ForeignKeyConstraint(
            ["merchant_id"], ["merchants.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["design_assets.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["version_id"], ["design_asset_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        # One image per version — the constraint that makes "bytes match
        # metadata" enforceable.
        sa.UniqueConstraint("version_id", name="uq_rendered_assets_version_id"),
    )
    op.create_index("ix_rendered_assets_id", "rendered_assets", ["id"])
    op.create_index(
        "ix_rendered_assets_merchant_id", "rendered_assets", ["merchant_id"]
    )
    op.create_index(
        "ix_rendered_assets_asset_id", "rendered_assets", ["asset_id"]
    )
    op.create_index(
        "ix_rendered_assets_version_id", "rendered_assets", ["version_id"]
    )
    op.create_index("ix_rendered_assets_sha256", "rendered_assets", ["sha256"])
    op.create_index(
        "ix_rendered_assets_merchant_created",
        "rendered_assets", ["merchant_id", "created_at"],
    )
    op.create_index(
        "ix_rendered_assets_merchant_sha",
        "rendered_assets", ["merchant_id", "sha256"],
    )


def downgrade() -> None:
    # Single table, no children of its own: nothing else references it, so
    # dropping it removes every stored image cleanly and leaves the Designer
    # Agent text records exactly as they were.
    op.drop_table("rendered_assets")