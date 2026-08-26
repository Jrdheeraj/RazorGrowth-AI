"""MerchantMembership model — the tenant-isolation join between users and merchants.

Every merchant-scoped request MUST resolve its merchant identity through an
active membership of the authenticated user. A user can never reach data of
a merchant they do not hold a membership with.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.app.models.enums import MembershipStatus, UserRole

if TYPE_CHECKING:
    from backend.app.models.merchant import Merchant
    from backend.app.models.user import User


class MerchantMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    A user's role within exactly one merchant tenant.

    Uniqueness: (user_id, merchant_id) — one role per user per merchant.
    Tenant isolation is enforced by resolving every request's merchant from
    this table, never from client-supplied identifiers alone.
    """

    __tablename__ = "memberships"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[UserRole] = mapped_column(String(20), nullable=False)
    status: Mapped[MembershipStatus] = mapped_column(
        String(20),
        nullable=False,
        default=MembershipStatus.active,
        server_default=MembershipStatus.active.value,
    )

    user: Mapped["User"] = relationship(
        "User", back_populates="memberships", foreign_keys=[user_id]
    )
    merchant: Mapped["Merchant"] = relationship("Merchant", foreign_keys=[merchant_id])

    __table_args__ = (
        UniqueConstraint("user_id", "merchant_id", name="uq_membership_user_merchant"),
    )

    @property
    def is_active(self) -> bool:
        return self.status == MembershipStatus.active

    def __repr__(self) -> str:
        return (
            f"<MerchantMembership user={self.user_id} "
            f"merchant={self.merchant_id} role={self.role}>"
        )
