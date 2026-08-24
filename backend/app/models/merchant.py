"""Merchant model — top-level tenant for all commerce data."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.app.models.enums import Currency, MerchantStatus

if TYPE_CHECKING:
    from backend.app.models.product import Product
    from backend.app.models.customer import Customer
    from backend.app.models.order import Order
    from backend.app.models.payment import Payment
    from backend.app.models.opportunity import GrowthOpportunity
    from backend.app.models.campaign import Campaign
    from backend.app.models.agent_action import AgentAction
    from backend.app.models.audit_event import AuditEvent


class Merchant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    A Razorpay merchant account.

    All commerce entities (products, customers, orders …) are scoped to a
    single merchant so the platform can support multiple tenants.
    """
    __tablename__ = "merchants"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[MerchantStatus] = mapped_column(
        String(20),
        nullable=False,
        default=MerchantStatus.active,
        server_default=MerchantStatus.active.value,
    )
    currency: Mapped[Currency] = mapped_column(
        String(3),
        nullable=False,
        default=Currency.INR,
        server_default=Currency.INR.value,
    )

    # ------------------------------------------------------------------ #
    # Relationships (back-populated from child tables)
    # ------------------------------------------------------------------ #
    products: Mapped[list[Product]] = relationship(
        "Product", back_populates="merchant", cascade="all, delete-orphan"
    )
    customers: Mapped[list[Customer]] = relationship(
        "Customer", back_populates="merchant", cascade="all, delete-orphan"
    )
    orders: Mapped[list[Order]] = relationship(
        "Order", back_populates="merchant", cascade="all, delete-orphan"
    )
    payments: Mapped[list[Payment]] = relationship(
        "Payment", back_populates="merchant", cascade="all, delete-orphan"
    )
    opportunities: Mapped[list[GrowthOpportunity]] = relationship(
        "GrowthOpportunity", back_populates="merchant", cascade="all, delete-orphan"
    )
    campaigns: Mapped[list[Campaign]] = relationship(
        "Campaign", back_populates="merchant", cascade="all, delete-orphan"
    )
    agent_actions: Mapped[list[AgentAction]] = relationship(
        "AgentAction", back_populates="merchant", cascade="all, delete-orphan"
    )
    audit_events: Mapped[list[AuditEvent]] = relationship(
        "AuditEvent", back_populates="merchant", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # email and status use index=True on mapped_column above.
    )

    def __repr__(self) -> str:
        return f"<Merchant id={self.id} slug={self.slug!r}>"
