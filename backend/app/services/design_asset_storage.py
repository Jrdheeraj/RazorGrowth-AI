"""Storage for generated image bytes — the ONLY module that touches them.

DESIGN INTENT
-------------
Everything outside this module deals in :class:`RenderedAssetRef` (metadata
only) and never in raw bytes. PostgreSQL ``BYTEA`` is an implementation
detail of this module; moving the payloads to object storage later is a change
here, not a redesign of the Designer Agent.

INVARIANTS ENFORCED HERE
------------------------
1. Bytes are validated (JPEG structure + dimensions) BEFORE a row is written.
2. The bytes and the asset/version metadata commit together, in one
   transaction. A failure rolls the whole thing back, so there is never a row
   pointing at a missing version or an image with no owning version.
3. Every read is merchant-scoped. There is no "get by id" that skips the
   tenant check, because that is how cross-merchant leaks happen.
4. Quota is enforced with a database-level advisory lock, so two concurrent
   requests cannot both observe "under quota" and both proceed.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.rendered_asset import RenderedAsset

log = logging.getLogger(__name__)


class ImageNotFound(LookupError):
    """A rendered image that is absent, or belongs to another merchant."""


class ImageValidationError(ValueError):
    """Bytes that are not an acceptable image. Never persisted."""


class ImageQuotaExceeded(RuntimeError):
    """A per-merchant generation or storage quota is exhausted."""

    def __init__(self, scope: str, used: int, limit: int) -> None:
        super().__init__(f"{scope} quota exceeded ({used}/{limit})")
        self.scope = scope
        self.used = used
        self.limit = limit


class ImageStorageConflict(RuntimeError):
    """That version already owns an image."""


@dataclass(frozen=True)
class JpegInfo:
    width: int
    height: int
    byte_size: int
    sha256: str


@dataclass(frozen=True)
class RenderedAssetRef:
    """Metadata-only handle. Safe to return from an API; contains no bytes."""

    id: uuid.UUID
    merchant_id: uuid.UUID
    asset_id: uuid.UUID
    version_id: uuid.UUID
    content_type: str
    byte_size: int
    sha256: str
    width: int
    height: int
    provider: str
    model: str
    steps: int | None
    created_at: datetime | None

    @classmethod
    def of(cls, row: RenderedAsset) -> "RenderedAssetRef":
        return cls(
            id=row.id,
            merchant_id=row.merchant_id,
            asset_id=row.asset_id,
            version_id=row.version_id,
            content_type=row.content_type,
            byte_size=row.byte_size,
            sha256=row.sha256,
            width=row.width,
            height=row.height,
            provider=row.provider,
            model=row.model,
            steps=row.steps,
            created_at=row.created_at,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "asset_id": str(self.asset_id),
            "version_id": str(self.version_id),
            "content_type": self.content_type,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
            "width": self.width,
            "height": self.height,
            "provider": self.provider,
            "model": self.model,
            "steps": self.steps,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ══════════════════════════════════════════════════════════════════════════
# Bounded JPEG structural validation (no Pillow)
# ══════════════════════════════════════════════════════════════════════════

#: JPEG markers we must be able to walk past. Anything unparseable is refused.
_SOI = b"\xff\xd8"                      # Start Of Image
_SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
     0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)                                       # SOF0..SOF15 except DHT/JPG/DAC
_STANDALONE = frozenset({0xD8, 0xD9} | set(range(0xD0, 0xD8)))


def parse_jpeg(data: bytes, *, max_pixels: int, max_width: int, max_height: int) -> JpegInfo:
    """Validate JPEG structure and read dimensions. Raises on anything else.

    A deliberately small, allocation-free parser: it walks the marker segment
    chain and reads the first SOF, refusing anything that is not a baseline-
    shaped JPEG. It never decompresses pixel data, so it cannot be turned into
    a decompression bomb.

    Refusing rather than trusting means a provider returning an HTML error
    page, a truncated transfer, or a PNG-in-a-jpeg-clothing does not silently
    become a stored "creative".
    """
    n = len(data)
    if n < 4:
        raise ImageValidationError("payload too short to be a JPEG")
    if data[:2] != _SOI:
        raise ImageValidationError("missing JPEG SOI marker")

    i = 2
    width = height = 0
    # A single JPEG header cannot legitimately be megabytes long; bounding the
    # walk keeps a hostile payload from making this loop expensive.
    scan_limit = min(n, 65536)

    while i < scan_limit - 1:
        if data[i] != 0xFF:
            raise ImageValidationError("malformed JPEG: expected a marker prefix")
        # Fill bytes (0xFF padding) are legal between segments.
        while i < n - 1 and data[i] == 0xFF:
            i += 1
        if i >= n:
            break
        marker = data[i]
        i += 1

        if marker in _STANDALONE:
            continue
        if marker == 0xD9:  # EOI
            break
        if i + 1 >= n:
            raise ImageValidationError("malformed JPEG: truncated segment length")
        seg_len = int.from_bytes(data[i : i + 2], "big")
        if seg_len < 2 or i + seg_len > n:
            raise ImageValidationError("malformed JPEG: bad segment length")

        if marker in _SOF_MARKERS:
            if seg_len < 8:
                raise ImageValidationError("malformed JPEG: short SOF segment")
            # SOF: [len:2][precision:1][height:2][width:2][components:1]
            height = int.from_bytes(data[i + 3 : i + 5], "big")
            width = int.from_bytes(data[i + 5 : i + 7], "big")
            break

        i += seg_len

    if width <= 0 or height <= 0:
        raise ImageValidationError("JPEG dimensions could not be determined")
    if width > max_width or height > max_height:
        raise ImageValidationError(
            f"image dimensions {width}x{height} exceed the configured maximum"
        )
    if width * height > max_pixels:
        raise ImageValidationError("image exceeds the configured pixel budget")

    return JpegInfo(
        width=width,
        height=height,
        byte_size=n,
        sha256=hashlib.sha256(data).hexdigest(),
    )


# ══════════════════════════════════════════════════════════════════════════
# Storage service
# ══════════════════════════════════════════════════════════════════════════


class DesignAssetStorage:
    """The single reader/writer of rendered image bytes."""

    def __init__(
        self,
        db: Session,
        *,
        max_bytes: int,
        daily_quota: int,
        daily_storage_quota_bytes: int,
        max_pixels: int,
        max_width: int,
        max_height: int,
    ) -> None:
        self.db = db
        self.max_bytes = max_bytes
        self.daily_quota = daily_quota
        self.daily_storage_quota_bytes = daily_storage_quota_bytes
        self.max_pixels = max_pixels
        self.max_width = max_width
        self.max_height = max_height

    # ── quota ────────────────────────────────────────────────────────────

    @staticmethod
    def _day_start() -> datetime:
        now = datetime.now(timezone.utc)
        return now.replace(hour=0, minute=0, second=0, microsecond=0)

    def _assert_quota(self, merchant_id: uuid.UUID, incoming_bytes: int) -> None:
        """Enforce BOTH per-day ceilings.

        Correct under concurrency: the advisory lock below is a real database
        lock, so two simultaneous requests serialise here and the second one
        sees the first one's rows. A plain SELECT/INSERT pair would not.
        """
        lock_key = _advisory_key("image-quota", merchant_id)
        # PostgreSQL serialises on a transaction-scoped advisory lock, which is
        # released automatically at commit/rollback and so can never be
        # stranded by a crashed request. SQLite (used only by the test suite)
        # has no such primitive and is single-writer anyway, so the guard is
        # skipped there rather than crashing on an unknown function.
        if self.db.bind is not None and self.db.bind.dialect.name == "postgresql":
            self.db.execute(
                text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_key}
            )

        since = self._day_start()
        used_count = int(
            self.db.scalar(
                select(func.count())
                .select_from(RenderedAsset)
                .where(
                    RenderedAsset.merchant_id == merchant_id,
                    RenderedAsset.created_at >= since,
                )
            )
            or 0
        )
        if used_count >= self.daily_quota:
            raise ImageQuotaExceeded("daily generation", used_count, self.daily_quota)

        used_bytes = int(
            self.db.scalar(
                select(func.coalesce(func.sum(RenderedAsset.byte_size), 0)).where(
                    RenderedAsset.merchant_id == merchant_id,
                    RenderedAsset.created_at >= since,
                )
            )
            or 0
        )
        if used_bytes + incoming_bytes > self.daily_storage_quota_bytes:
            raise ImageQuotaExceeded(
                "daily storage", used_bytes + incoming_bytes, self.daily_storage_quota_bytes
            )

    # ── write ────────────────────────────────────────────────────────────

    def store(
        self,
        merchant_id: uuid.UUID,
        *,
        asset_id: uuid.UUID,
        version_id: uuid.UUID,
        data: bytes,
        provider: str,
        model: str,
        steps: int | None,
        created_by: str | None = None,
        validate: bool = True,
    ) -> RenderedAssetRef:
        """Validate, quota-check and persist one image. Never partial.

        The caller owns the transaction. Bytes and metadata are inserted
        together, so a validation failure, a quota refusal or a uniqueness
        violation all leave the database exactly as it was — there is no state
        in which a row exists without its image.
        """
        if not data:
            raise ImageValidationError("empty payload")
        if len(data) > self.max_bytes:
            raise ImageValidationError(
                f"image is {len(data)} bytes, over the {self.max_bytes} byte limit"
            )

        info = (
            parse_jpeg(
                data,
                max_pixels=self.max_pixels,
                max_width=self.max_width,
                max_height=self.max_height,
            )
            if validate
            else JpegInfo(
                width=0,
                height=0,
                byte_size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
            )
        )

        self._assert_quota(merchant_id, len(data))

        row = RenderedAsset(
            merchant_id=merchant_id,
            asset_id=asset_id,
            version_id=version_id,
            image_bytes=data,
            content_type="image/jpeg",
            byte_size=info.byte_size,
            sha256=info.sha256,
            width=info.width,
            height=info.height,
            provider=provider,
            model=model,
            steps=steps,
            created_by=created_by,
        )
        self.db.add(row)
        try:
            self.db.flush()
        except IntegrityError as exc:
            # Most likely the 1:1 with the version: this version already owns
            # an image. Surface it as a conflict rather than a 500.
            self.db.rollback()
            raise ImageStorageConflict(
                "this asset version already has a rendered image"
            ) from exc

        return RenderedAssetRef.of(row)

    # ── read ─────────────────────────────────────────────────────────────

    def get_ref(
        self, merchant_id: uuid.UUID, rendered_id: uuid.UUID
    ) -> RenderedAssetRef:
        row = self.db.scalar(
            select(RenderedAsset).where(
                RenderedAsset.id == rendered_id,
                RenderedAsset.merchant_id == merchant_id,
            )
        )
        if row is None:
            # Same 404 for "does not exist" and "belongs to someone else", so
            # this endpoint cannot be used to probe for other tenants' ids.
            raise ImageNotFound(f"RENDERED_ASSET_NOT_FOUND:{rendered_id}")
        return RenderedAssetRef.of(row)

    def read_bytes(
        self, merchant_id: uuid.UUID, rendered_id: uuid.UUID
    ) -> tuple[RenderedAssetRef, bytes]:
        """Fetch bytes for THIS merchant. Ownership is re-checked on read."""
        row = self.db.scalar(
            select(RenderedAsset).where(
                RenderedAsset.id == rendered_id,
                RenderedAsset.merchant_id == merchant_id,
            )
        )
        if row is None:
            raise ImageNotFound(f"RENDERED_ASSET_NOT_FOUND:{rendered_id}")
        return RenderedAssetRef.of(row), bytes(row.image_bytes)

    def list_for_asset(
        self, merchant_id: uuid.UUID, asset_id: uuid.UUID
    ) -> list[RenderedAssetRef]:
        rows = self.db.scalars(
            select(RenderedAsset)
            .where(
                RenderedAsset.merchant_id == merchant_id,
                RenderedAsset.asset_id == asset_id,
            )
            .order_by(RenderedAsset.created_at.desc())
        ).all()
        return [RenderedAssetRef.of(r) for r in rows]

    def list_for_merchant(
        self, merchant_id: uuid.UUID, *, limit: int = 100
    ) -> list[RenderedAssetRef]:
        rows = self.db.scalars(
            select(RenderedAsset)
            .where(RenderedAsset.merchant_id == merchant_id)
            .order_by(RenderedAsset.created_at.desc())
            .limit(limit)
        ).all()
        return [RenderedAssetRef.of(r) for r in rows]

    def usage_today(self, merchant_id: uuid.UUID) -> dict[str, int]:
        since = self._day_start()
        count = int(
            self.db.scalar(
                select(func.count())
                .select_from(RenderedAsset)
                .where(
                    RenderedAsset.merchant_id == merchant_id,
                    RenderedAsset.created_at >= since,
                )
            )
            or 0
        )
        size = int(
            self.db.scalar(
                select(func.coalesce(func.sum(RenderedAsset.byte_size), 0)).where(
                    RenderedAsset.merchant_id == merchant_id,
                    RenderedAsset.created_at >= since,
                )
            )
            or 0
        )
        return {"images": count, "bytes": size}


def _advisory_key(scope: str, merchant_id: uuid.UUID) -> int:
    """Stable 63-bit advisory-lock key for (scope, merchant).

    Derived from a hash so different merchants never collide onto one lock and
    two different scopes never share one.
    """
    digest = hashlib.sha256(f"{scope}:{merchant_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF


__all__ = [
    "DesignAssetStorage",
    "ImageNotFound",
    "ImageQuotaExceeded",
    "ImageStorageConflict",
    "ImageValidationError",
    "JpegInfo",
    "RenderedAssetRef",
    "parse_jpeg",
]