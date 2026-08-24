"""
SQLAlchemy declarative base and shared model mixins.

All ORM models must inherit from Base.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Project-wide declarative base."""
    pass


class TimestampMixin:
    """
    Adds created_at / updated_at columns to any model.

    server_default handles the DB side; onupdate handles SQLAlchemy-level
    updates so in-process mutations also refresh updated_at.
    """
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UUIDPrimaryKeyMixin:
    """Adds a UUID primary key column."""
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
