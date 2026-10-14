"""Rendered creative assets — the image BYTES behind a design asset.

WHY A SEPARATE TABLE
--------------------
``design_assets`` and ``design_asset_versions`` are append-only, JSONB-shaped
records whose whole design purpose is to be cheap to read, diff and version.
Image bytes are none of those things: a single 1024x1024 JPEG is ~100-200 KB,
so storing them inline would bloat every brief listing and every version
history query in the product.

They therefore live here, one row per generated image, linked to BOTH the
asset and the exact version that produced it. Two consequences matter:

  * ``design_assets`` / ``design_asset_versions`` stay byte-free and remain
    purely append-only, exactly as their invariants require.
  * Deleting a design project still removes its images: this table's foreign
    keys cascade, so there is no orphaned blob and no orphan row.

STORAGE IS AN ABSTRACTION, NOT A COMMITMENT
-------------------------------------------
Nothing outside :mod:`backend.app.services.design_asset_storage` should know
these bytes are in PostgreSQL. That module is the only writer and the only
reader, and it exposes plain ``bytes``. Moving the payloads to object storage
later is therefore a change to that one module, not a redesign of the
Designer Agent.

There is no publicly reachable URL for an image. Bytes are served only
through an authenticated, merchant-scoped route.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RenderedAsset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One generated image, durably stored and ownership-scoped.

    The ``asset_id`` and ``version_id`` pair is what keeps bytes and metadata
    consistent: a row can only exist for a version that already exists, and
    the unique constraint means one version owns at most one image. A
    regenerated image becomes a NEW version with its own row, so the previous
    bytes are never overwritten.
    """

    __tablename__ = "rendered_assets"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: The design asset this image realises.
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("design_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: The exact immutable version that produced these bytes.
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("design_asset_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: The image itself. ``BYTEA`` — binary, never base64-encoded on the way
    #: in; the provider's base64 is decoded once, in memory, before insert.
    image_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(60), nullable=False, default="image/jpeg", server_default="image/jpeg"
    )
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)

    #: SHA-256 of the decoded bytes. Lets a caller detect a truncated or
    #: tampered download without re-hashing the whole payload client-side,
    #: and gives deduplication a stable key later.
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    #: Dimensions read by the bounded JPEG parser at write time. Stored so a
    #: read never has to re-parse the header just to describe the image.
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)

    provider: Mapped[str] = mapped_column(
        String(60), nullable=False, default="cloudflare", server_default="cloudflare"
    )
    model: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        default="cloudflare-flux-1-schnell",
        server_default="cloudflare-flux-1-schnell",
    )
    #: Diffusion steps actually used, for reproducibility/audit.
    steps: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: Created while persisting, so a failed generation can be identified.
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    version: Mapped["Any"] = relationship(
        "DesignAssetVersion",
        primaryjoin="RenderedAsset.version_id == foreign(DesignAssetVersion.id)",
        viewonly=True,
    )

    __table_args__ = (
        # One image per version. This is the constraint that makes "bytes and
        # metadata agree" enforceable rather than aspirational.
        UniqueConstraint(
            "version_id", name="uq_rendered_assets_version_id"
        ),
        # Quota accounting scans by merchant + day.
        Index("ix_rendered_assets_merchant_created", "merchant_id", "created_at"),
        Index("ix_rendered_assets_merchant_sha", "merchant_id", "sha256"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"<RenderedAsset asset={self.asset_id} v={self.version_id} "
            f"{self.width}x{self.height} {self.byte_size}B>"
        )


__all__ = ["RenderedAsset", "_utcnow"]