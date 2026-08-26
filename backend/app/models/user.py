"""User model — Phase 6 authentication principal.

A User is a HUMAN account. Agents are never Users: there is no code path
that mints credentials for an agent, and approval/execution endpoints
require a human role via merchant membership.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.app.models.enums import UserStatus

if TYPE_CHECKING:
    from backend.app.models.membership import MerchantMembership


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    An authenticated human user of the platform.

    Security invariants:
      - password_hash stores ONLY a salted scrypt digest — never plaintext.
      - email is the login identifier and is unique across the platform.
      - status == disabled blocks both login and token validation.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[UserStatus] = mapped_column(
        String(20),
        nullable=False,
        default=UserStatus.active,
        server_default=UserStatus.active.value,
    )

    memberships: Mapped[list["MerchantMembership"]] = relationship(
        "MerchantMembership",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="[MerchantMembership.user_id]",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} status={self.status}>"
